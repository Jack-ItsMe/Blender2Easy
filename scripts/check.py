#!/usr/bin/env python3
"""Run the repository's unit and frontend regressions without Blender.

Install skills/blender2easy/scripts/requirements.txt first. Node.js 22+ is
needed for the frontend suite (no npm packages or browser are required).
Use --with-mcp after installing requirements-mcp.txt for real SDK protocol
and process-lifecycle tests. Use --with-blender for the separate tiny Blender
integration fixture; that option is never enabled by the normal CI suite.
"""
import argparse
import importlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "blender2easy"
TESTS = ROOT / "tests"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-only", action="store_true", help="Skip the Node frontend suite")
    parser.add_argument("--require-node", action="store_true", help="Fail instead of skipping when Node is absent")
    parser.add_argument("--node", help="Node executable; defaults to node on PATH")
    parser.add_argument("--with-mcp", action="store_true", help="Run the optional official SDK integration tests")
    parser.add_argument("--with-blender", action="store_true", help="Run the optional Blender import/snapshot fixture")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or newer is required")
    if args.python_only and args.require_node:
        parser.error("--python-only and --require-node cannot be combined")

    missing = [name for name in ("PIL", "imageio_ffmpeg") if importlib.util.find_spec(name) is None]
    if missing:
        parser.error("Missing runtime dependencies: " + ", ".join(missing) +
                     "; run python -m pip install -r skills/blender2easy/scripts/requirements.txt")
    if args.with_mcp and importlib.util.find_spec("mcp") is None:
        parser.error("--with-mcp requires python -m pip install -r skills/blender2easy/scripts/requirements-mcp.txt")

    # Keep checks from creating bytecode or inherited editor state in source.
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PYTHONUTF8"] = "1"
    os.environ["BLENDER2EASY_TEST_MCP"] = "1" if args.with_mcp else "0"
    os.environ["BLENDER2EASY_TEST_BLENDER"] = "1" if args.with_blender else "0"
    for name in ("ANIMATION_BLENDER", "ANIMATION_FFMPEG", "ANIMATION_THREAD_ID", "CODEX_THREAD_ID"):
        if name not in ("ANIMATION_BLENDER", "ANIMATION_FFMPEG") or not args.with_blender:
            os.environ.pop(name, None)
    sys.path.insert(0, str(SKILL / "scripts"))
    sys.path.insert(1, str(TESTS))
    implementation = importlib.import_module("animkit")
    expected = (SKILL / "scripts/animkit/__init__.py").resolve()
    if Path(implementation.__file__).resolve() != expected:
        raise RuntimeError(f"Wrong implementation loaded: {implementation.__file__}")
    print(f"Testing Blender2Easy {implementation.__version__} from {SKILL}", flush=True)
    suite = unittest.defaultTestLoader.discover(str(TESTS), pattern="test_*.py")
    for name, module in list(sys.modules.items()):
        if name.startswith("animkit.") and getattr(module, "__file__", None):
            if not Path(module.__file__).resolve().is_relative_to(SKILL / "scripts"):
                raise RuntimeError(f"External implementation loaded: {name}: {module.__file__}")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"Python: run={result.testsRun}, failures={len(result.failures)}, "
          f"errors={len(result.errors)}, skipped={len(result.skipped)}", flush=True)
    if not result.wasSuccessful():
        return 1
    if args.python_only:
        print("Frontend: SKIPPED (--python-only)")
        return 0

    node = args.node or shutil.which("node")
    if not node:
        print("Frontend: " + ("FAIL" if args.require_node else "SKIPPED") +
              " (Node.js 22+ not found; pass --node or add node to PATH)")
        return 1 if args.require_node else 0
    try:
        version = subprocess.check_output([node, "--version"], text=True).strip()
        if int(version.removeprefix("v").split(".")[0]) < 22:
            print(f"Frontend: FAIL (Node.js 22+ required; found {version})")
            return 1
        suites = sorted((TESTS / "frontend").glob("*-checks.mjs"))
        for path in suites:
            print(f"Frontend: {path.name}", flush=True)
            subprocess.run([node, "--experimental-vm-modules", str(path)], cwd=ROOT, check=True)
        web = SKILL / "editor/web"
        syntax_files = sorted([*web.glob("*.js"), *(web / "locales").glob("*.js")])
        for path in syntax_files:
            subprocess.run([node, "--check", str(path)], cwd=ROOT, check=True, capture_output=True, text=True)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Frontend: FAIL ({exc})", file=sys.stderr)
        if getattr(exc, "stderr", None):
            print(exc.stderr, file=sys.stderr)
        return 1
    print(f"Frontend: PASS ({len(suites)} suites; {len(syntax_files)} JavaScript syntax checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
