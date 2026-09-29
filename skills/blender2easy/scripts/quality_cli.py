"""BAS quality adapters; invoked through animation.py quality."""
import argparse
import json
import sys

from animkit.quality_tools import TOOLS, catalog, run_tool


def main(argv=None):
    parser = argparse.ArgumentParser(prog="animation.py quality", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog", help="List bounded tools, specialist workflows, optional dependencies")
    run = commands.add_parser("run", help="Run a known Blender script from a strict JSON spec")
    run.add_argument("tool", choices=sorted(TOOLS))
    run.add_argument("--spec", required=True)
    run.add_argument("--blender")
    run.add_argument("--timeout", type=int, default=300)
    run.add_argument("--reuse", action="store_true", help="Verify and reuse completed unchanged outputDir; reject stale or partial evidence")
    args = parser.parse_args(argv)
    try:
        result = catalog() if args.command == "catalog" else run_tool(args.tool, args.spec, blender=args.blender, timeout=args.timeout, reuse=args.reuse)
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0 if result.get("status", "complete") == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
