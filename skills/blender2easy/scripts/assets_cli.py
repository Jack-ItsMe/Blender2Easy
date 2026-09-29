"""Asset acquisition handoffs and local motion import, without optional Bun."""
import argparse
import json

from animkit.asset_tools import prepare_search


def main(argv=None):
    parser = argparse.ArgumentParser(prog="animation.py assets", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search", help="Prepare a provider browser URL; no live search or download")
    search.add_argument("provider", choices=("mixamo", "pixabay"))
    search.add_argument("--query", required=True)
    motion = commands.add_parser("import-motion", help="Import one local animated FBX into a new Blender candidate")
    motion.add_argument("--spec", required=True)
    motion.add_argument("--blender")
    motion.add_argument("--timeout", type=int, default=300)
    motion.add_argument("--reuse", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "search":
            result = prepare_search(args.provider, args.query)
        else:
            from animkit.quality_tools import run_tool
            result = run_tool("mixamo-import", args.spec, blender=args.blender, timeout=args.timeout, reuse=args.reuse)
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status":"failed", "error":str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    return 0 if result.get("status") in ("browser_required", "complete") else 1


if __name__ == "__main__":
    raise SystemExit(main())
