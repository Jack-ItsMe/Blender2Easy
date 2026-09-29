"""Test-only stdio harness with an observable sleeping CLI and grandchild."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1] / 'skills' / 'blender2easy'
sys.path.insert(0, str(ROOT / 'scripts'))
state = Path(os.environ['MCP_TEST_STATE'])

if sys.argv[1:] == ['serve']:
    import anyio
    from mcp.server.stdio import stdio_server
    from animkit.mcp_runtime import ToolDispatcher, create_server

    async def main():
        dispatcher = ToolDispatcher(script=Path(__file__))
        server = create_server(dispatcher)
        try:
            async with stdio_server() as streams:
                await server.run(*streams, server.create_initialization_options())
        finally:
            await dispatcher.close()
            (state / 'clean-eof.json').write_text(json.dumps({'jobs': dispatcher.jobs, 'processes': len(dispatcher.processes)}))
    anyio.run(main)
elif '--version' in sys.argv:
    from animkit import __version__
    print(__version__)
elif '--query=oversized' in sys.argv:
    print('x' * 2_000_001)
elif '--query=malformed' in sys.argv:
    print('not JSON')
else:
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    (state / 'pids.json').write_text(json.dumps({'worker': os.getpid(), 'child': child.pid}))
    time.sleep(120)
