"""Official MCP SDK transport with a bounded, cancellable CLI job dispatcher."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import anyio
import mcp.types as types
from mcp import MCPError
from mcp.server import Server
from mcp.server.stdio import stdio_server

from . import __version__
from .mcp_tools import TOOLS, command_for, completed_result, execution_timeout, tool_content

SCRIPT = Path(__file__).resolve().parents[1] / 'animation.py'
MAX_OUTPUT_BYTES = 2_000_000


def stop_process(process):
    """Terminate a CLI and its Blender descendants, including on cancellation."""
    if process is None or process.poll() is not None:
        return
    if os.name == 'nt':
        try:
            stopped = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                     capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
            if stopped.returncode and process.poll() is None:
                process.kill()
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        import signal
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def error_result(error):
    return types.CallToolResult.model_validate({'content': [{'type': 'text', 'text': str(error)[:4000]}], 'isError': True})


class ToolDispatcher:
    """One executing CLI, at most four admitted calls (running plus queued).

    SDK handler cancellation propagates through every await. Shield only the
    bounded process-tree cleanup; never intercept cancellation as a tool error.
    """
    def __init__(self, script=SCRIPT):
        self.script = Path(script)
        self.lock = anyio.Lock()
        self.jobs = 0
        self.processes = set()
        self.closed = False

    async def call(self, name, arguments):
        try:
            argv = command_for(name, arguments)
        except (TypeError, ValueError) as exc:
            raise MCPError(types.INVALID_PARAMS, str(exc)) from exc
        if self.closed or self.jobs >= 4:
            raise MCPError(types.INVALID_PARAMS, 'Tool queue full or server closing (maximum four admitted calls)')
        self.jobs += 1
        try:
            async with self.lock:
                if self.closed:
                    return error_result('Server closing')
                return await self._run(name, arguments, argv)
        except TimeoutError:
            return error_result('Tool execution exceeded server limit')
        except Exception as exc:
            return error_result(exc)
        finally:
            self.jobs -= 1

    async def _run(self, name, arguments, argv):
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen([sys.executable, '-X', 'utf8', str(self.script), *argv],
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                start_new_session=os.name != 'nt')
            self.processes.add(process)
            try:
                with anyio.fail_after(execution_timeout(name, arguments)):
                    while process.poll() is None:
                        await anyio.sleep(.05)
                stdout.seek(0)
                stderr.seek(0)
                raw = stdout.read(MAX_OUTPUT_BYTES + 1)
                if len(raw) > MAX_OUTPUT_BYTES:
                    raise ValueError('Tool output exceeds 2 MB; reduce describe limit/select one frame, or inspect the saved report')
                text = raw.decode('utf-8', errors='replace').strip()
                parse_failed = False
                try:
                    value = {'toolkit_version': text} if name == 'animation_version' and process.returncode == 0 else json.loads(text)
                except ValueError:
                    parse_failed = True
                    value = {'status': 'error', 'error': text[-4000:] or stderr.read(4000).decode('utf-8', errors='replace')}
                value, error = completed_result(name, arguments, value, process.returncode)
                return types.CallToolResult.model_validate({
                    'content': tool_content(value), 'isError': error or parse_failed,
                    **({'structuredContent': value} if isinstance(value, dict) else {})})
            finally:
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(stop_process, process)
                self.processes.discard(process)

    async def close(self):
        self.closed = True
        with anyio.CancelScope(shield=True):
            for process in tuple(self.processes):
                await anyio.to_thread.run_sync(stop_process, process)


def create_server(dispatcher):
    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=[types.Tool.model_validate(tool) for tool in TOOLS])

    async def call_tool(ctx, params):
        return await dispatcher.call(params.name, params.arguments or {})

    return Server('blender2easy', version=__version__, on_list_tools=list_tools, on_call_tool=call_tool)


async def serve():
    dispatcher = ToolDispatcher()
    server = create_server(dispatcher)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        await dispatcher.close()
