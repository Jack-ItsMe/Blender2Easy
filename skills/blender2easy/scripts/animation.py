#!/usr/bin/env python3
"""Blender2Easy CLI for parameterized, resumable Blender modeling and animation."""
from pathlib import Path
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

from animkit import __version__
from animkit.common import digest, file_lock, read_json, resolve_tool, sha256, write_json
from animkit.project import compile_plans, load_project, normalize_project, require

ROOT = Path(__file__).resolve().parents[1]


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False))


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    commands = p.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init", help="Create a new project from a starter template")
    initialize.add_argument("path", help="New project directory or .json file (will not overwrite)")
    initialize.add_argument("--template", choices=("blank", "box", "lamp"), default="blank")
    doctor = commands.add_parser("doctor", help="Report local dependencies, without installing")
    doctor.add_argument("--blender")
    doctor.add_argument("--ffmpeg")
    editor = commands.add_parser("editor", help="Start the local Blender2Easy preview and editor")
    editor.add_argument("project", nargs="?")
    editor.add_argument("--port", type=int, default=8766)
    editor.add_argument("--workspace")
    editor.add_argument("--open", action="store_true")
    editor.add_argument("--info-file")
    editor.add_argument("--authoring", action="store_true", help="Explicitly enable full editing tools at /authoring")
    review = commands.add_parser("review", help="Create, receive and apply agent-scoped review requests")
    review.add_argument("arguments", nargs=argparse.REMAINDER)
    for name, help_text in (("quality", "BAS-derived asset, reference and render tools"),
                            ("assets", "Browser asset handoffs and local animated FBX import"),
                            ("diagnose", "Scene snapshots, mechanical checks and revision comparison"),
                            ("mcp", "Expose bounded quality/review tools over local stdio MCP")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("arguments", nargs=argparse.REMAINDER)
    export = commands.add_parser("export", help="Copy project, declared assets and checked deliveries to a new directory")
    export.add_argument("project")
    export.add_argument("--to", required=True, dest="destination")
    export.add_argument("--ffmpeg")
    for name in ("validate", "build", "plan", "preview", "render", "compose", "run", "status", "verify", "change"):
        cmd = commands.add_parser(name)
        cmd.add_argument("project")
        if name in ("build", "plan", "preview", "render", "compose", "run", "verify"):
            cmd.add_argument("--blender")
            cmd.add_argument("--ffmpeg")
            cmd.add_argument("--expected-revision", help=argparse.SUPPRESS)
        if name in ("plan", "preview", "render", "compose", "run", "verify"):
            cmd.add_argument("--shot", help="Process only this shot ID; default all shots")
        if name == "preview":
            cmd.add_argument("--frames", help="Comma-separated 1-based OUTPUT frame numbers; default first/middle/last")
        if name == "change":
            cmd.add_argument("--set", nargs=2, required=True, metavar=("JSON_POINTER", "JSON_VALUE"))
    return p


def compact(report):
    hidden = {"plate_paths", "plate_keys", "selected_frames", "frames", "inputs", "requests", "pngs", "checks"}
    return {key: value for key, value in report.items() if key not in hidden}


def change_project(path, pointer, raw_value):
    path = Path(path).resolve()
    before = read_json(path)
    old_hash = sha256(path)
    value = json.loads(raw_value)
    require(pointer.startswith("/") and pointer != "/", "Use an existing JSON Pointer, e.g. /render/samples")
    parts = [p.replace("~1", "/").replace("~0", "~") for p in pointer[1:].split("/")]
    cursor = before
    for token in parts[:-1]:
        if isinstance(cursor, list):
            require(token.isdigit() and int(token) < len(cursor), f"Invalid list index: {token}")
            cursor = cursor[int(token)]
        else:
            require(isinstance(cursor, dict) and token in cursor, f"Unknown path: {pointer}")
            cursor = cursor[token]
    leaf = parts[-1]
    if isinstance(cursor, list):
        require(leaf.isdigit() and int(leaf) < len(cursor), f"Invalid list index: {leaf}")
        leaf = int(leaf)
    else:
        require(isinstance(cursor, dict) and leaf in cursor, f"Unknown parameter: {pointer}")
    previous = cursor[leaf]
    cursor[leaf] = value
    normalize_project(before, path)  # No mutation if validation fails.
    require(sha256(path) == old_hash, "Project changed while preparing the update")
    state = path.parent / ".animation"
    archive = state / "revisions" / (old_hash + ".json")
    if not archive.exists():
        write_json(archive, read_json(path))
    write_json(path, before)
    new_hash = sha256(path)
    write_json(state / "changes" / (new_hash + ".json"), {
        "time": datetime.now(timezone.utc).isoformat(), "before_sha256": old_hash,
        "after_sha256": new_hash, "pointer": pointer, "previous": previous, "value": value})
    return {"status": "UPDATED", "project": str(path), "pointer": pointer,
            "before_sha256": old_hash, "after_sha256": new_hash, "previous_project": str(archive)}


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("quality", "diagnose", "mcp", "assets"):
        if sys.argv[1] == "quality":
            from quality_cli import main as delegated_main
        elif sys.argv[1] == "diagnose":
            from diagnostics_cli import main as delegated_main
        elif sys.argv[1] == "assets":
            from assets_cli import main as delegated_main
        else:
            from studio_mcp import main as delegated_main
        raise SystemExit(delegated_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "review":
        from review_cli import main as review_main
        raise SystemExit(review_main(sys.argv[2:]))
    args = parser().parse_args()
    if args.command == "editor":
        argv = [sys.executable, str(ROOT / "editor/server.py"), "--port", str(args.port)]
        if args.project:
            argv += ["--project", args.project]
        if args.workspace:
            argv += ["--workspace", args.workspace]
        if args.info_file:
            argv += ["--info-file", args.info_file]
        if args.open:
            argv += ["--open"]
        if args.authoring:
            argv += ["--authoring"]
        raise SystemExit(subprocess.call(argv))
    if args.command == "init":
        target = Path(args.path).expanduser().resolve()
        if target.suffix.lower() != ".json":
            target = target / "project.json"
        require(not target.exists(), f"Project already exists: {target}")
        if target.parent.exists():
            require(not any(target.parent.iterdir()), "Initialize into an empty directory to keep one project per directory")
        data = read_json(ROOT / "assets" / "templates" / (args.template + ".json"))
        normalized = normalize_project(data, target)
        write_json(target, data)
        emit({"status": "CREATED", "project": str(target), "id": normalized["id"], "template": args.template,
              "next": "Edit the project parameters, then run validate and preview."})
        return
    if args.command == "doctor":
        result = {"toolkit_version": __version__, "python": sys.executable,
                  "python_version": sys.version.split()[0], "dependencies": {}, "tools": {}}
        for module in ("PIL", "imageio_ffmpeg"):
            result["dependencies"][module] = importlib.util.find_spec(module) is not None
        for name in ("blender", "ffmpeg"):
            try:
                executable = resolve_tool(name, getattr(args, name))
                version = subprocess.run([executable, "--version" if name == "blender" else "-version"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
                require(version.returncode == 0, f"Unable to execute {name}")
                result["tools"][name] = {"path": executable, "version": version.stdout.splitlines()[0]}
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                result["tools"][name] = {"error": str(exc)}
        result["status"] = "READY" if all(result["dependencies"].values()) and all("error" not in t for t in result["tools"].values()) else "MISSING_DEPENDENCIES"
        emit(result)
        if result["status"] != "READY":
            raise SystemExit(2)
        return
    path = Path(args.project).expanduser().resolve()
    require(path.is_file(), f"Project not found: {path}")
    state = path.parent / ".animation"
    if args.command == "status":
        status_path = state / "status.json"
        emit(read_json(status_path) if status_path.exists() else {"status": "NOT_STARTED", "project": str(path)})
        return
    if args.command == "change":
        with file_lock(state / "project.lock"):
            emit(change_project(path, *args.set))
        return
    if args.command == "validate":
        project = load_project(path)
        emit({"status": "PASS", "id": project["id"], "project": str(path),
              "assets": len(project["_asset_hashes"]), "shots": [{"id": s["id"],
              "source_range": s["source_range"], "output_frames": sum(p["frames"] for p in s["timing"])} for s in project["shots"]],
              "render": project["render"], "validation": "schema_and_declared_files; native cameras checked during build/render"})
        return
    if args.command == "export":
        from animkit.exporter import export_project
        with file_lock(state / "project.lock"):
            emit(export_project(load_project(path), args.destination, args.ffmpeg))
        return
    from animkit import pipeline
    with file_lock(state / "project.lock"):
        expected = getattr(args, "expected_revision", None)
        require(not expected or sha256(path) == expected, "Project changed before job execution; save and retry")
        if args.command == "verify":
            deliveries_path = state / "deliveries.json"
            require(deliveries_path.exists(), "No encoded deliveries recorded; run or compose first")
            deliveries = read_json(deliveries_path)
            entries = {k: v for k, v in deliveries.items() if not args.shot or k == args.shot}
            require(entries, f"Unknown/unproduced shot: {args.shot}")
            results = []
            for shot, entry in entries.items():
                result = pipeline.verify_output(entry["report"], args.ffmpeg)
                results.append({"shot": shot, **compact(result)})
            emit({"status": "PASS", "results": results})
            return
        project = load_project(path)
        selected = [s for s in project["shots"] if not getattr(args, "shot", None) or s["id"] == args.shot]
        require(selected, f"Unknown shot: {getattr(args, 'shot', None)}")
        build = pipeline.build_project(project, args.blender)
        if args.command == "build":
            emit(compact(build))
            return
        plans = [p for p in compile_plans(project, build) if p["id"] in {s["id"] for s in selected}]
        results = []
        for plan in plans:
            plan_key = digest(plan)
            plan_path = state / "plans" / (plan_key + ".json")
            write_json(plan_path, plan)
            if args.command == "plan":
                results.append({"id": plan["id"], "frames": len(plan["frames"]), "plan": str(plan_path)})
                continue
            frames = None
            if args.command == "preview":
                frames = sorted(set(int(f) for f in args.frames.split(","))) if args.frames else sorted({1, (len(plan["frames"])+1)//2, len(plan["frames"])})
                require(frames and all(1 <= f <= len(plan["frames"]) for f in frames), "Preview frames outside output range")
            if args.command == "compose":
                rendering = pipeline.load_render_report(project, plan, frames)
            else:
                rendering = pipeline.render_plan(project, plan, args.blender, frames)
            if args.command == "render":
                results.append({"id": plan["id"], **compact(rendering)})
                continue
            result = pipeline.compose_plan(project, plan, rendering, args.ffmpeg, frames)
            result["native_rendered"] = 0 if args.command == "compose" else rendering.get("rendered", 0)
            result["native_reused"] = rendering.get("total", 0) if args.command == "compose" else rendering.get("reused", 0)
            if args.command != "preview":
                deliveries_path = state / "deliveries.json"
                deliveries = read_json(deliveries_path) if deliveries_path.exists() else {}
                deliveries[plan["id"]] = {"plan_digest": plan_key, "report": result}
                write_json(deliveries_path, deliveries)
            results.append({"id": plan["id"], **compact(result)})
        emit({"status": "PASS", "project": str(path), "operation": args.command, "results": results})


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        main()
    except (ValueError, RuntimeError, OSError, KeyError, ImportError) as exc:
        emit({"status": "ERROR", "error": str(exc), "command": sys.argv[1] if len(sys.argv) > 1 else None})
        raise SystemExit(1)
