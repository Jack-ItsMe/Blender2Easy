"""Real official SDK clients exercise the shipped stdio protocol and job lifetime."""
import asyncio
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'skills' / 'blender2easy'
sys.path.insert(0, str(ROOT / 'scripts'))
from animkit import __version__
from animkit.mcp_tools import TOOLS
from test_studio_mcp import current_snapshot, write_fixture
import studio_mcp

HAS_SDK = (os.environ.get('BLENDER2EASY_TEST_MCP') == '1'
           and importlib.util.find_spec('mcp') is not None)
if HAS_SDK:
    import anyio
    from mcp import Client, MCPError
    from mcp.client.stdio import StdioServerParameters
    from animkit.mcp_runtime import ToolDispatcher, create_server


def parameters(fixture=None):
    env = dict(os.environ, ANIMATION_BLENDER=str(ROOT / 'missing-blender'), ANIMATION_FFMPEG=str(ROOT / 'missing-ffmpeg'))
    args = [str(ROOT / 'scripts/animation.py'), 'mcp']
    if fixture:
        env['MCP_TEST_STATE'] = str(fixture)
        args = [str(Path(__file__).with_name('mcp_process_fixture.py')), 'serve']
    return StdioServerParameters(command=sys.executable, args=['-X', 'utf8', *args], env=env)


def alive(pid):
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class LauncherTests(unittest.TestCase):
    def test_config_needs_no_sdk_and_missing_sdk_stays_off_stdout(self):
        from importlib.metadata import PackageNotFoundError
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(studio_mcp, 'version', side_effect=PackageNotFoundError('mcp')), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(studio_mcp.main(['--config']), 0)
        config = json.loads(stdout.getvalue())
        self.assertEqual(config['command'], sys.executable)
        self.assertEqual(stderr.getvalue(), '')
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(studio_mcp, 'version', side_effect=PackageNotFoundError('mcp')), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(studio_mcp.main([]), 2)
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('-m venv .venv-mcp', stderr.getvalue())
        self.assertIn('requirements-mcp.txt', stderr.getvalue())

    def test_unsupported_sdk_does_not_silently_switch_implementation(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(studio_mcp, 'version', return_value='1.0.0'), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(studio_mcp.main([]), 2)
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('mcp==2.2.0', stderr.getvalue())

    def test_sdk_failure_never_becomes_nonprotocol_stdout(self):
        if not HAS_SDK:
            self.skipTest('Requires the optional SDK runtime')
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch('anyio.run', side_effect=RuntimeError('transport unavailable')), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(studio_mcp.main([]), 1)
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('transport unavailable', stderr.getvalue())


@unittest.skipUnless(HAS_SDK, 'Use scripts/check.py --with-mcp in the requirements-mcp.txt environment')
class SDKProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_official_handshake_can_still_negotiate_original_2025_06_18(self):
        # Drive the official SDK initializer as an old host: its default version
        # constant is replaced only in this test, never in the shipped runtime.
        with patch('mcp.client.session.LATEST_HANDSHAKE_VERSION', '2025-06-18'):
            async with Client(parameters(), mode='legacy') as client:
                self.assertEqual(client.protocol_version, '2025-06-18')
                self.assertEqual(len((await client.list_tools()).tools), 14)
                self.assertFalse((await client.call_tool('animation_version', {})).is_error)

    async def test_official_clients_negotiate_discover_and_initialize_with_exact_tools(self):
        for mode, version in [('auto', '2026-07-28'), ('legacy', '2025-11-25')]:
            with self.subTest(mode=mode):
                async with Client(parameters(), mode=mode) as client:
                    self.assertEqual(client.protocol_version, version)
                    discovered = await client.list_tools()
                    self.assertEqual(len(discovered.tools), 14)
                    self.assertEqual({t.name: t.input_schema for t in discovered.tools}, {t['name']: t['inputSchema'] for t in TOOLS})
                    self.assertEqual((await client.call_tool('animation_version', {})).structured_content['toolkit_version'], __version__)
                    catalog = await client.call_tool('animation_quality_catalog', {})
                    self.assertFalse(catalog.is_error)
                    self.assertEqual(len(catalog.structured_content['commands']), 9)
                    if mode == 'legacy':
                        await client.session.send_ping()
                    for name, arguments in [('execute_python', {'code': 'print(1)'}), ('animation_snapshot', {'asset': 'x', 'output': 'y', 'frames': [True]})]:
                        with self.assertRaises(MCPError) as caught:
                            await client.call_tool(name, arguments)
                        self.assertEqual(caught.exception.code, -32602)
                        self.assertNotIn('Traceback', caught.exception.message)

    async def test_describe_and_diagnostic_fail_are_successful_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            snapshot = current_snapshot(folder)
            contract = write_fixture(folder / 'contract.json', {'schema_version': 'object-animation.diagnostic-contract/1', 'required_objects': ['Missing']})
            async with Client(parameters()) as client:
                doctor = await client.call_tool('animation_doctor', {})
                self.assertFalse(doctor.is_error)
                self.assertEqual(doctor.structured_content['status'], 'MISSING_DEPENDENCIES')
                result = await client.call_tool('animation_describe', {'snapshot': snapshot, 'object_id': 'Base', 'descendants': True, 'frame': -1, 'offset': 1, 'limit': 1})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content['frames'][0]['scope']['total'], 2)
                for name, inputs in [('animation_diagnose', {'snapshot': snapshot}), ('animation_compare', {'before': snapshot, 'after': snapshot})]:
                    result = await client.call_tool(name, {**inputs, 'contract': contract, 'output': str(folder / (name + '.json'))})
                    self.assertFalse(result.is_error)
                    self.assertEqual(result.structured_content['status'], 'FAIL')
                    self.assertEqual(result.structured_content['findings'][0]['object_ids'], ['Missing'])
                (folder / 'source.blend').write_bytes(b'changed')
                self.assertTrue((await client.call_tool('animation_describe', {'snapshot': snapshot})).is_error)

    async def test_shipped_review_create_wait_close_keeps_scope_and_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            project = folder / 'project.json'
            original = (ROOT / 'assets/templates/box.json').read_bytes()
            project.write_bytes(original)
            spec = write_fixture(folder / 'review.json', {
                'title': 'Prepared model', 'question': 'Review the lid?', 'stage': 'model', 'controls': [],
                'segments': [{'id': 'opening', 'title': 'Opening', 'source_range': [1, 48]}],
                'focus': {'shot_id': 'opening', 'segment_id': 'opening', 'object_ids': ['lid'],
                          'source_frame': 1, 'source_range': [1, 48], 'camera_id': 'hero'}})
            async with Client(parameters()) as client:
                created = await client.call_tool('animation_review_create', {'project': str(project), 'spec_path': spec, 'thread_id': 'task'})
                self.assertFalse(created.is_error)
                scope = {'project': str(project), 'thread_id': 'task', 'request_id': created.structured_content['request']['id']}
                polled = await client.call_tool('animation_review_wait', {**scope, 'timeout_seconds': 0})
                self.assertFalse(polled.is_error)
                wrong = await client.call_tool('animation_review_close', {**scope, 'thread_id': 'other'})
                self.assertTrue(wrong.is_error)
                closed = await client.call_tool('animation_review_close', {**scope, 'message': 'Reviewed; no model change'})
                self.assertFalse(closed.is_error)
                state = (await client.call_tool('animation_review_status', {'project': str(project)})).structured_content
                self.assertEqual(state['status'], 'closed')
                self.assertEqual(state['request']['id'], scope['request_id'])
                self.assertEqual(project.read_bytes(), original)

    async def _wait_pids(self, folder):
        for _ in range(100):
            if (folder / 'pids.json').is_file():
                try:
                    return json.loads((folder / 'pids.json').read_text())
                except ValueError:
                    pass
            await asyncio.sleep(.03)
        self.fail('CLI worker did not start')

    async def test_sdk_cancel_kills_cli_tree_and_frees_queue_for_both_eras(self):
        for mode in ('auto', 'legacy'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                async with Client(parameters(folder), mode=mode) as client:
                    task = asyncio.create_task(client.call_tool('animation_review_wait', {'project': 'x', 'thread_id': 't', 'request_id': 'r', 'timeout_seconds': 60}))
                    pids = await self._wait_pids(folder)
                    self.assertTrue(all(alive(pid) for pid in pids.values()))
                    if mode == 'legacy':
                        await client.session.send_ping()
                    else:
                        self.assertEqual(len((await client.list_tools()).tools), 14)
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                    result = await asyncio.wait_for(client.call_tool('animation_version', {}), 6)
                    self.assertFalse(result.is_error)
                    self.assertTrue(all(not alive(pid) for pid in pids.values()))

    async def test_eof_cleans_active_and_queued_jobs(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            tasks = []
            async with Client(parameters(folder), mode='legacy') as client:
                for _ in range(3):
                    tasks.append(asyncio.create_task(client.call_tool('animation_review_wait', {'project': 'x', 'thread_id': 't', 'request_id': 'r', 'timeout_seconds': 60})))
                pids = await self._wait_pids(folder)
            for task in tasks:
                with contextlib.suppress(BaseException):
                    await task
            self.assertTrue((folder / 'clean-eof.json').is_file(), 'SDK server did not finish its own EOF cleanup')
            self.assertEqual(json.loads((folder / 'clean-eof.json').read_text()), {'jobs': 0, 'processes': 0})
            self.assertTrue(all(not alive(pid) for pid in pids.values()))

    async def test_malformed_and_oversized_outputs_are_bounded_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            async with Client(parameters(Path(temporary))) as client:
                for query in ('malformed', 'oversized'):
                    result = await client.call_tool('animation_asset_search', {'provider': 'pixabay', 'query': query})
                    self.assertTrue(result.is_error)
                    self.assertLess(len(result.content[0].text), 5000)
                    self.assertNotIn('Traceback', result.content[0].text)

    async def test_one_executing_cli_four_admitted_jobs_and_timeout_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            script = Path(__file__).with_name('mcp_process_fixture.py')
            dispatcher = ToolDispatcher(script=script)
            with patch.dict(os.environ, MCP_TEST_STATE=str(folder)), patch('animkit.mcp_runtime.execution_timeout', return_value=.6):
                async with Client(create_server(dispatcher)) as client:
                    tasks = [asyncio.create_task(client.call_tool('animation_review_wait', {'project': 'x', 'thread_id': 't', 'request_id': 'r'})) for _ in range(4)]
                    await self._wait_pids(folder)
                    self.assertEqual(dispatcher.jobs, 4)
                    self.assertEqual(len(dispatcher.processes), 1)
                    with self.assertRaises(MCPError) as caught:
                        await client.call_tool('animation_version', {})
                    self.assertEqual(caught.exception.code, -32602)
                    self.assertIn('queue full', caught.exception.message)
                    for task in tasks[1:]:
                        task.cancel()
                    for task in tasks[1:]:
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
                    result = await tasks[0]
                    self.assertTrue(result.is_error)
                    self.assertIn('server limit', result.content[0].text)
                await dispatcher.close()
                self.assertEqual(dispatcher.jobs, 0)
                pids = json.loads((folder / 'pids.json').read_text())
                self.assertTrue(all(not alive(pid) for pid in pids.values()))


if __name__ == '__main__':
    unittest.main()
