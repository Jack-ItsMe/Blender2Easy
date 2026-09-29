"""Fresh-file CLI for read-only evaluated scene diagnostics."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from animkit.common import resolve_tool
from animkit.diagnostics import (analyze, compare, describe, file_hash, read_json, validate_snapshot,
                                write_fresh, finite_tree)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot", help="Evaluate an asset in a separate Blender process")
    snapshot.add_argument("asset")
    snapshot.add_argument("--output", required=True)
    snapshot.add_argument("--frames", help="1..32 unique comma-separated source frame numbers")
    snapshot.add_argument("--blender")
    snapshot.add_argument("--timeout", type=float, default=120)
    description = commands.add_parser("describe", help="Return scoped and paginated evaluated scene facts")
    description.add_argument("snapshot")
    description.add_argument("--object", dest="object_id")
    description.add_argument("--descendants", action="store_true")
    description.add_argument("--frame", type=int)
    description.add_argument("--offset", type=int, default=0)
    description.add_argument("--limit", type=int, default=50)
    description.add_argument("--output", help="Optional new JSON file; otherwise print the description")
    for name in ("analyze", "compare"):
        command = commands.add_parser(name)
        if name == "analyze":
            command.add_argument("snapshot")
        else:
            command.add_argument("before")
            command.add_argument("after")
        command.add_argument("--contract")
        command.add_argument("--output", required=True)
    return result


def _read_input(path):
    path = Path(path).expanduser().resolve()
    data = path.read_bytes()
    value = json.loads(data.decode("utf-8-sig"))
    finite_tree(value)
    return value, {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def _verified_snapshot(path, require_current=True):
    value, metadata = _read_input(path)
    snapshot = validate_snapshot(value)
    source = Path(snapshot["source"]["path"])
    if require_current and (not source.is_file() or file_hash(source) != snapshot["source"]["sha256"]):
        raise ValueError(f"Snapshot is stale or its source is unavailable: {source}")
    return snapshot, metadata


def capture(asset, output, frames=None, blender=None, timeout=120):
    source, destination = Path(asset).expanduser().resolve(), Path(output).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in {".blend", ".glb", ".gltf", ".fbx", ".obj"}:
        raise ValueError("Source must be an existing .blend, .glb, .gltf, .fbx or .obj")
    if source == destination or destination.exists():
        raise ValueError("Snapshot output must be a new file distinct from its source")
    finite_tree(timeout)
    if not isinstance(timeout, (float, int)) or not 1 <= timeout <= 3600:
        raise ValueError("timeout must be between 1 and 3600 seconds")
    if frames is not None:
        selected = [int(value.strip()) for value in frames.split(",")]
        if not 1 <= len(selected) <= 32 or len(set(selected)) != len(selected) or any(abs(frame) > 1048574 for frame in selected):
            raise ValueError("Require 1..32 unique Blender integer source frames")
        frames = ",".join(map(str, selected))
    executable = resolve_tool("blender", blender)
    worker = Path(__file__).with_name("diagnostic_worker.py")
    expected = file_hash(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".diagnostic-", dir=destination.parent) as scratch:
        intermediate = Path(scratch) / "snapshot.json"
        argv = [executable, "--background", "--factory-startup", "--disable-autoexec",
                "--python-exit-code", "1", "--python", str(worker), "--",
                "--input", str(source), "--output", str(intermediate)]
        if frames is not None:
            argv.append("--frames=" + frames)
        try:
            completed = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                       timeout=timeout, shell=False,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        finally:
            if not source.is_file() or file_hash(source) != expected:
                raise ValueError("Source changed while Blender evaluated it")
        if completed.returncode or not intermediate.is_file():
            raise RuntimeError(f"Blender diagnostics failed ({completed.returncode}): "
                               + (completed.stdout + completed.stderr)[-2400:])
        snapshot = validate_snapshot(read_json(intermediate))
        if snapshot["source"] != {"path": str(source), "sha256": expected}:
            raise ValueError("Worker source fingerprint did not match the requested asset")
        snapshot["provenance"].update({"created_at": datetime.now(timezone.utc).isoformat(),
                                       "blender_executable": executable, "source_unchanged": True,
                                       "cli_sha256": file_hash(__file__)})
        write_fresh(destination, snapshot)
    return snapshot


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        output = Path(args.output).expanduser().resolve() if args.output else None
        if output is not None and output.exists():
            raise ValueError(f"Output already exists: {output}")
        if args.command == "describe":
            snapshot, snapshot_input = _verified_snapshot(args.snapshot)
            result = describe(snapshot, args.object_id, args.descendants, args.offset, args.limit, args.frame)
            result["provenance"] = {"snapshot_file": snapshot_input,
                                      "current_source_hash_verified": True}
            if file_hash(snapshot["source"]["path"]) != snapshot["source"]["sha256"]:
                raise ValueError("Source changed while its scene description was prepared")
            if output is not None:
                write_fresh(output, result)
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
            return 0
        elif args.command == "snapshot":
            result = capture(args.asset, output, args.frames, args.blender, args.timeout)
            summary = {"status": "SNAPSHOT", "output": str(output), "source": result["source"],
                       "frames": [sample["frame"] for sample in result["frames"]]}
            exit_code = 0
        else:
            contract, contract_input = _read_input(args.contract) if args.contract else (None, None)
            paths = [args.snapshot] if args.command == "analyze" else [args.before, args.after]
            inputs = [_verified_snapshot(path, require_current=(index == len(paths) - 1))
                      for index, path in enumerate(paths)]
            snapshots = [item[0] for item in inputs]
            result = analyze(snapshots[0], contract) if args.command == "analyze" else compare(*snapshots, contract)
            result["provenance"].update({"snapshot_files": [item[1] for item in inputs],
                                       "current_source_hash_verified": True,
                                       "historical_baseline": args.command == "compare",
                                       "contract_file": contract_input})
            # Do not publish a report if a primary asset changed during analysis.
            for snapshot in snapshots[-1:]:
                if file_hash(snapshot["source"]["path"]) != snapshot["source"]["sha256"]:
                    raise ValueError("Source changed while diagnostics were analyzed")
            for metadata in [item[1] for item in inputs] + ([contract_input] if contract_input else []):
                if file_hash(metadata["path"]) != metadata["sha256"]:
                    raise ValueError("Diagnostic input changed while the report was prepared")
            write_fresh(output, result)
            summary = {"status": result["status"], "output": str(output), "sources": result["sources"],
                       "findings": len(result["findings"])}
            exit_code = 2 if result["status"] == "FAIL" else 0
        print(json.dumps(summary, ensure_ascii=False, allow_nan=False))
        return exit_code
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
