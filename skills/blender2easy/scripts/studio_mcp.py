"""Launch the Blender2Easy MCP server; CLI/config discovery need no MCP install."""
import argparse
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import re
import sys

SCRIPT = Path(__file__).with_name('animation.py')
REQUIREMENTS = Path(__file__).with_name('requirements-mcp.txt')


def required_sdk_version():
    pins = re.findall(r'^mcp==([0-9]+\.[0-9]+\.[0-9]+)\s*$', REQUIREMENTS.read_text(encoding='utf-8'), re.MULTILINE)
    if len(pins) != 1:
        raise ValueError('requirements-mcp.txt must pin exactly one stable mcp version')
    return pins[0]


def dependency_help(reason, required):
    python = str(Path('.venv-mcp') / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python'))
    prefix = '& ' if os.name == 'nt' else ''
    return (f'MCP requires the official Python SDK mcp=={required}: {reason}.\n'
            'Create an isolated environment; the ordinary CLI needs no MCP SDK:\n'
            f'  {prefix}"{sys.executable}" -m venv .venv-mcp\n'
            f'  {prefix}"{python}" -m pip install -r "{REQUIREMENTS}"\n'
            f'  {prefix}"{python}" "{SCRIPT}" mcp --config\n'
            'Use that printed command configuration in your MCP host.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', action='store_true', help='Print configuration for this Python; does not install/register a server')
    args = parser.parse_args(argv)
    if args.config:
        print(json.dumps({'command': sys.executable, 'args': [str(SCRIPT), 'mcp']}, indent=2))
        return 0
    try:
        required = required_sdk_version()
    except (OSError, ValueError) as exc:
        print('MCP dependency configuration error: ' + str(exc), file=sys.stderr)
        return 2
    try:
        installed = version('mcp')
        if installed != required:
            print(dependency_help('found ' + installed, required), file=sys.stderr)
            return 2
        from animkit.mcp_runtime import serve
        import anyio
    except (PackageNotFoundError, ImportError) as exc:
        print(dependency_help(str(exc), required), file=sys.stderr)
        return 2
    try:
        anyio.run(serve)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f'MCP server stopped: {type(exc).__name__}: {str(exc)[:2000]}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
