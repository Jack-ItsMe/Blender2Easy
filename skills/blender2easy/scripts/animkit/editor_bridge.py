"""Local native scene discovery and content-addressed Three.js preview artifacts.

The caller owns the existing project file lock. Source files are opened with
scripts disabled and never saved. Every preview is produced from a verified
Blender build, so native declarative overrides affect previews and final renders.
"""
from pathlib import Path
import subprocess

from .common import digest, read_json, sha256, write_json
from .pipeline import _creation_flags, _output, _state, _tool, build_project

WORKER = Path(__file__).resolve().parents[1] / "editor_preview_worker.py"
BUILD_WORKER = WORKER.with_name("blender_worker.py")


def _run(executable, job, log, cwd):
    with Path(log).open("wb") as stream:
        result = subprocess.run([executable, "--background", "--factory-startup", "--disable-autoexec",
                                 "--python-exit-code", "1", "--python", str(WORKER), "--", "--job", str(job)],
                                cwd=str(cwd), stdout=stream, stderr=subprocess.STDOUT,
                                creationflags=_creation_flags(), shell=False)
    try:
        response = read_json(read_json(job)["report"])
    except (OSError, ValueError):
        response = {}
    if result.returncode or response.get("status") != "PASS":
        detail = response.get("error") or Path(log).read_text(encoding="utf-8", errors="replace")[-1800:]
        raise RuntimeError("Native preview failed: " + str(detail) + "; log: " + str(log))
    return response


def discover_native(path, state_dir, blender=None):
    """Inspect scene/cameras/materials and external dependency paths, read-only."""
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".blend":
        raise ValueError("Native import requires an existing .blend file")
    state = Path(state_dir).resolve()
    state.mkdir(parents=True, exist_ok=True)
    executable, version = _tool("blender", blender)
    source_hash = sha256(source)
    key = digest({"source": str(source), "sha256": source_hash, "version": version,
                  "worker": sha256(WORKER), "build_worker": sha256(BUILD_WORKER)})
    folder = _output(state, "native-discovery", key[:20], "manifest.json").parent
    report = folder / "manifest.json"
    job = folder / "job.json"
    # Always inspect dependencies afresh; their state is not covered by source hash.
    write_json(job, {"operation": "discover", "blend": str(source), "state": str(state), "report": str(report)})
    response = _run(executable, job, folder / "discover.log", state)
    if sha256(source) != source_hash or response.get("source_sha256") != source_hash:
        raise RuntimeError("Native source changed while importing")
    return response["manifest"]


def export_preview(project, blender=None):
    """Export a real animated GLB from the current verified project build."""
    state = _state(project)
    build = build_project(project, blender)
    executable, version = _tool("blender", blender)
    inputs = {"build_key": build["key"], "blend_sha256": build["blend_sha256"],
              "worker_sha256": sha256(WORKER), "blender_version": version,
              "build_worker_sha256": sha256(BUILD_WORKER)}
    key = digest(inputs)
    output = _output(state, "editor-previews", key[:20], "scene.glb")
    record_path = output.with_name("preview.json")
    try:
        record = read_json(record_path)
        if record.get("inputs") == inputs and record.get("sha256") == sha256(output):
            return {"path": str(output), "manifest": record["manifest"]}
    except (OSError, ValueError, KeyError):
        pass
    report = output.with_name("worker_report.json")
    job = output.with_name("job.json")
    write_json(job, {"operation": "export", "blend": build["blend"], "scene": build["scene"],
                     "state": str(state), "output": str(output), "report": str(report)})
    response = _run(executable, job, output.with_name("export.log"), project["_root"])
    if response.get("source_sha256") != build["blend_sha256"] or sha256(build["blend"]) != build["blend_sha256"]:
        raise RuntimeError("Built scene changed while exporting native preview")
    if sha256(WORKER) != inputs["worker_sha256"] or sha256(BUILD_WORKER) != inputs["build_worker_sha256"]:
        raise RuntimeError("Preview worker changed during export; retry")
    record = {"inputs": inputs, "sha256": sha256(output), "manifest": response["manifest"]}
    write_json(record_path, record)
    return {"path": str(output), "manifest": response["manifest"]}
