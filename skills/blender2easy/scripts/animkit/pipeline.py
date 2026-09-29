"""Versioned native builds, source-image caching, and checked video composition.

Public calls assume the CLI owns the project lock. Nothing here edits an input
asset; every generated file belongs to the project's .animation directory.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from functools import lru_cache
import math
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

from PIL import Image, ImageDraw, __version__ as PILLOW_VERSION

from .common import digest, read_json, resolve_tool, run_logged, sha256, valid_png, write_json


WORKER = Path(__file__).resolve().parents[1] / "blender_worker.py"
ENCODER_PROFILE = {
    "codec": "libx264", "preset": "fast", "crf": 18,
    "pixel_format": "yuv420p", "audio": False, "threads": 2,
    "movflags": "+faststart",
}
_IMAGEIO_ENV_LOCK = threading.Lock()


def _state(project):
    root = Path(project["_root"]).resolve()
    state = Path(project["_state"]).resolve()
    if state != (root / ".animation").resolve() or state == root:
        raise ValueError("Project state must be its .animation directory")
    state.mkdir(parents=True, exist_ok=True)
    return state


def _output(state, *parts):
    path = state.joinpath(*map(str, parts)).resolve()
    if not path.is_relative_to(state) or path == state:
        raise ValueError("Generated path escapes the project state directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _safe_id(value):
    value = str(value)
    if not value or value in {".", ".."} or any(c in value for c in '/\\<>:"|?*\0'):
        raise ValueError("Invalid artifact ID: " + repr(value))
    return value


def _short(value):
    """Keep Windows paths short; reports always retain and compare full digests."""
    return value[:20]


def _bound_directory(state, category, key, inputs):
    """Short disk paths with an explicit full-digest binding, never silent aliasing."""
    binding = _output(state, category, _short(key), "identity.json")
    expected = {"key": key, "inputs": inputs}
    if binding.exists():
        if read_json(binding) != expected:
            raise RuntimeError("Short " + category + " key collision; refusing to replace another version")
    else:
        write_json(binding, expected)
    return binding.parent


def _video_name(value):
    value = _safe_id(value)
    return value if len(value) <= 32 else value[:24] + "-" + digest(value)[:8]


def _verify_assets(project):
    for name, expected in project.get("_asset_hashes", {}).items():
        path = Path(name)
        if not path.is_absolute() or not path.is_file() or sha256(path) != expected:
            raise RuntimeError("Input asset changed or disappeared: " + str(path))


def _status(project, phase, **fields):
    write_json(_state(project) / "status.json", {
        "schema_version": 1, "phase": phase,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **fields,
    })


def _creation_flags():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


@lru_cache(maxsize=16)
def _version_cached(executable, argument, stamp):
    del stamp
    result = subprocess.run(
        [executable, argument], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", timeout=30,
        creationflags=_creation_flags(), check=False,
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if result.returncode or not lines:
        raise RuntimeError("Could not read tool version: " + executable)
    return lines[0]


def _tool(name, explicit=None):
    executable = str(resolve_tool(name, explicit))
    try:
        stat = Path(executable).stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    return executable, _version_cached(executable, "--version" if name == "blender" else "-version", stamp)


def _worker_args(executable, job):
    return [executable, "--background", "--factory-startup", "--python-exit-code", "1",
            "--python", str(WORKER), "--", "--job", str(job)]


def _build_return(record, report_path, reused):
    return {key: record[key] for key in ("key", "blend", "blend_sha256", "blender_version")} | {
        "status": "PASS", "report": str(report_path), "reused": reused,
        "scene": record.get("scene", "Animation"),
    }


def build_project(project, blender=None):
    """Build once per native-affecting input, leaving camera layout/timing out."""
    state = _state(project)
    executable, version = _tool("blender", blender)
    _verify_assets(project)
    worker_hash = sha256(WORKER)
    inputs = {
        "schema_version": 1, "units": project.get("units", "m"),
        "scene": project.get("scene") if not project.get("source") else None,
        "source": project.get("source"), "assets": project.get("assets", []),
        "asset_hashes": project.get("_asset_hashes", {}),
        "fps": project["render"]["fps"], "blender_version": version,
        "blender_worker_sha256": worker_hash,
    }
    key = digest(inputs)
    blend = _bound_directory(state, "builds", key, inputs) / "scene.blend"
    report_path = blend.parent / "build.json"
    try:
        previous = read_json(report_path)
        if (previous.get("status") == "PASS" and previous.get("key") == key
                and previous.get("inputs") == inputs and blend.is_file()
                and previous.get("blend_sha256") == sha256(blend)):
            _status(project, "BUILT", build_key=key, reused=True)
            return _build_return(previous, report_path, True)
    except (OSError, ValueError, KeyError):
        pass
    for source in project.get("_asset_hashes", {}):
        if Path(source).resolve() == blend:
            raise ValueError("A build output must never replace its source")
    worker_report = blend.parent / "worker_build.json"
    job = blend.parent / "build_job.json"
    write_json(job, {"operation": "build", "project": project,
                     "output": str(blend), "report": str(worker_report)})
    _status(project, "BUILDING", build_key=key)
    try:
        run_logged(_worker_args(executable, job), blend.parent / "build.log", cwd=project["_root"])
        result = read_json(worker_report)
        if result.get("status") != "PASS" or not blend.is_file():
            raise RuntimeError("Blender did not produce a successful native build")
        if Path(result.get("output", "")).resolve() != blend:
            raise RuntimeError("Blender build report names an unexpected output")
        _verify_assets(project)
        if sha256(WORKER) != worker_hash:
            raise RuntimeError("Blender worker changed during build")
        record = {"status": "PASS", "key": key, "inputs": inputs, "blend": str(blend),
                  "blend_sha256": sha256(blend), "blender_version": version,
                  "scene": result.get("scene", "Animation"), "worker_report": str(worker_report),
                  "warnings": result.get("warnings", [])}
        write_json(report_path, record)  # PASS is published only after verification.
        _status(project, "BUILT", build_key=key, reused=False)
        return _build_return(record, report_path, False)
    except Exception as exc:
        _status(project, "FAILED", operation="build", build_key=key, error=str(exc))
        raise


def _native(project, plan):
    state = _state(project)
    expected = _output(state, "builds", _short(plan["build_key"]), "scene.blend")
    if Path(plan["blend"]).resolve() != expected:
        raise ValueError("Plan native does not belong to the declared build")
    record = read_json(expected.parent / "build.json")
    if (record.get("status") != "PASS" or record.get("key") != plan["build_key"]
            or record.get("blend_sha256") != sha256(expected)):
        raise RuntimeError("Native build is missing, changed, or unverified; build again")
    return record


def _rows(plan, frames=None):
    rows = plan["frames"]
    if not rows or [r["frame"] for r in rows] != list(range(1, len(rows) + 1)):
        raise ValueError("Plan output frame indices must be consecutive, starting at 1")
    if frames is None:
        return rows
    values = list(frames)
    if not values or any(type(f) is not int or not 1 <= f <= len(rows) for f in values):
        raise ValueError("Preview frames must be existing output frame numbers")
    return [rows[f - 1] for f in sorted(set(values))]


def _dependencies(plan, rows):
    requests = defaultdict(set)
    for row in rows:
        for part in row["main"] + row.get("overlays", []):
            if part.get("weight", part.get("alpha", 1)) <= 0:
                continue
            label, source = part["plate"], part["source"]
            if label not in plan["plates"] or type(source) is not int or source < 1:
                raise ValueError("Invalid plate/source dependency")
            requests[label].add(source)
    if not requests:
        raise ValueError("Plan selection has no image dependencies")
    return requests


def _cache_layout(project, plan, rows, native, render_version, worker_hash):
    state = _state(project)
    paths, keys, physical = {}, {}, {}
    for label, sources in sorted(_dependencies(plan, rows).items()):
        cfg = plan["plates"][label]
        inputs = {
            "schema_version": 1, "build_key": plan["build_key"],
            "native_sha256": native["blend_sha256"], "scene": plan.get("scene", native.get("scene")),
            "camera": cfg["camera"], "size": cfg["size"],
            "engine": plan["engine"], "samples": plan["samples"], "fps": plan["fps"],
            "transparent": plan["transparent"], "blender_version": render_version,
            "blender_worker_sha256": worker_hash,
        }
        key = digest(inputs)
        keys[label] = key
        paths[label] = {}
        folder = _bound_directory(state, "cache", key, inputs)
        for source in sorted(sources):
            path = folder / f"{source:06d}.png"
            paths[label][str(source)] = str(path)
            # Identical camera/settings may appear under two logical plate IDs.
            physical.setdefault((key, source), {"plate": label, "source": source,
                                                "path": path, "size": cfg["size"], "camera": cfg["camera"]})
    return paths, keys, physical


def _render_report_path(project, plan, rows):
    selection = digest([row["frame"] for row in rows])
    return _output(_state(project), "render_reports", _short(digest(plan)), _short(selection) + ".json")


def _run_render(project, argv, log, progress_path, reused, total, missing, shot):
    """Observe a worker without exposing long Blender output to CLI stdout."""
    with Path(log).open("wb") as output:
        proc = subprocess.Popen(argv, stdout=output, stderr=subprocess.STDOUT,
                                cwd=project["_root"], env=dict(os.environ, PYTHONUTF8="1"),
                                creationflags=_creation_flags())
        latest = None
        try:
            while proc.poll() is None:
                try:
                    event = read_json(progress_path)
                except (OSError, ValueError):
                    event = {}
                finished = min(missing, max(0, int(event.get("rendered", event.get("completed", 0)))))
                update = (finished, event.get("plate"), event.get("source", event.get("frame")))
                if update != latest:
                    _status(project, "RENDERING", shot=shot, pid=proc.pid,
                            rendered=finished, reused=reused, completed=reused + finished, total=total,
                            plate=update[1], source_frame=update[2], counter_unit="unique_source_png")
                    latest = update
                time.sleep(0.2)
            if proc.returncode:
                raise RuntimeError(f"Blender render failed ({proc.returncode}); see {log}")
        except BaseException:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait()
            raise


def render_plan(project, plan, blender=None, frames=None):
    """Render missing source images; layout/retiming do not enter plate keys."""
    state = _state(project)
    _verify_assets(project)
    rows = _rows(plan, frames)
    native = _native(project, plan)
    executable, version = _tool("blender", blender)
    worker_hash = sha256(WORKER)
    paths, keys, physical = _cache_layout(project, plan, rows, native, version, worker_hash)
    absent = [r for r in physical.values() if not valid_png(r["path"], r["size"])]
    total = len(physical)
    reused = total - len(absent)
    run_id = uuid.uuid4().hex[:12]
    job_path = _output(state, "jobs", "render", run_id, "job.json")
    report_path = _render_report_path(project, plan, rows)
    progress_path = job_path.parent / "worker_progress.json"
    worker_report = job_path.parent / "worker_report.json"
    _status(project, "RENDERING", shot=plan["id"], rendered=0, reused=reused,
            completed=reused, total=total, counter_unit="unique_source_png")
    try:
        if absent:
            groups = {}
            for record in absent:
                key = (record["plate"], tuple(record["size"]))
                groups.setdefault(key, {"id": record["plate"], "camera": record["camera"],
                                        "size": record["size"], "requests": []})["requests"].append(
                                            {"frame": record["source"], "path": str(record["path"])})
            write_json(job_path, {
                "operation": "render", "blend": plan["blend"],
                "scene": plan.get("scene", native.get("scene")), "fps": plan["fps"],
                "engine": plan["engine"], "samples": plan["samples"], "transparent": plan["transparent"],
                "plates": list(groups.values()), "progress": str(progress_path), "report": str(worker_report),
            })
            _run_render(project, _worker_args(executable, job_path), job_path.parent / "render.log",
                        progress_path, reused, total, len(absent), plan["id"])
            worker_result = read_json(worker_report)
            if worker_result.get("status") != "PASS" or worker_result.get("rendered") != len(absent):
                raise RuntimeError("Worker render count/status does not match the submitted job")
        for record in physical.values():
            if not valid_png(record["path"], record["size"]):
                raise RuntimeError("Missing or corrupt rendered PNG: " + str(record["path"]))
        if sha256(WORKER) != worker_hash or sha256(plan["blend"]) != native["blend_sha256"]:
            raise RuntimeError("Native or worker changed during render")
        _verify_assets(project)
        report = {
            "status": "PASS", "plan_digest": digest(plan), "build_key": plan["build_key"],
            "native_sha256": native["blend_sha256"], "render_blender_version": version,
            "worker_sha256": worker_hash, "selected_frames": [r["frame"] for r in rows],
            "rendered": len(absent), "reused": reused, "total": total,
            "counter_unit": "unique_source_png", "logical_requests": sum(len(p) for p in paths.values()),
            "plate_keys": keys, "plate_paths": paths, "report": str(report_path),
        }
        report["inputs_digest"] = digest({k: report[k] for k in (
            "plan_digest", "native_sha256", "render_blender_version", "worker_sha256", "selected_frames", "plate_keys")})
        if report_path.exists():
            prior = read_json(report_path)
            if prior.get("plan_digest") != report["plan_digest"] or prior.get("selected_frames") != report["selected_frames"]:
                raise RuntimeError("Short render-report key collision; refusing to replace another selection")
        write_json(report_path, report)
        _status(project, "RENDERED", shot=plan["id"], rendered=len(absent), reused=reused,
                completed=total, total=total, counter_unit="unique_source_png", report=str(report_path))
        return report
    except Exception as exc:
        _status(project, "FAILED", operation="render", shot=plan["id"], error=str(exc))
        raise


def _validate_render_report(project, plan, report, rows):
    native = _native(project, plan)
    selected = [r["frame"] for r in rows]
    if report.get("status") != "PASS" or report.get("plan_digest") != digest(plan):
        raise RuntimeError("Render report belongs to a different plan; render this plan first")
    if not set(selected).issubset(report.get("selected_frames", [])):
        raise RuntimeError("Render report does not cover the requested output frames")
    worker_hash = sha256(WORKER)
    if report.get("worker_sha256") != worker_hash or report.get("native_sha256") != native["blend_sha256"]:
        raise RuntimeError("Render report is stale; render with the current inputs first")
    paths, keys, physical = _cache_layout(project, plan, rows, native,
                                         report["render_blender_version"], worker_hash)
    for label, entries in paths.items():
        if report.get("plate_keys", {}).get(label) != keys[label]:
            raise RuntimeError("Render plate key does not match its settings")
        if any(report.get("plate_paths", {}).get(label, {}).get(f) != path for f, path in entries.items()):
            raise RuntimeError("Render report names an unexpected cache path")
    return paths, keys, physical


def load_render_report(project, plan, frames=None):
    """Find a report without starting Blender; full renders can supply previews."""
    rows = _rows(plan, frames)
    candidates = [_render_report_path(project, plan, rows)]
    if frames is not None:
        candidates.append(_render_report_path(project, plan, _rows(plan)))
    for path in candidates:
        try:
            report = read_json(path)
        except (OSError, ValueError):
            continue
        _validate_render_report(project, plan, report, rows)
        return report
    raise RuntimeError("No render report for this plan/selection; run render or preview first")


def _atomic_image(image, path, format="PNG"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".t-" + uuid.uuid4().hex[:12] + ".tmp")
    try:
        image.save(temporary, format=format)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _background(plan):
    color = plan.get("background", [1, 1, 1])
    if len(color) not in (3, 4) or any(not math.isfinite(float(v)) or not 0 <= v <= 1 for v in color):
        raise ValueError("Background must contain RGB values between 0 and 1")
    return tuple(round(float(v) * 255) for v in color[:3])


def _composer(plan, paths):
    background = _background(plan)

    @lru_cache(maxsize=8)
    def flattened(label, source):
        path = paths[label][str(source)]
        with Image.open(path) as loaded:
            rgba = loaded.convert("RGBA")
        canvas = Image.new("RGBA", rgba.size, background + (255,))
        canvas.alpha_composite(rgba)
        return canvas.convert("RGB")

    def composite(row):
        main = [p for p in row["main"] if p.get("weight", 1) > 0]
        weights = [float(p.get("weight", 1)) for p in main]
        if not weights or any(not math.isfinite(v) for v in weights) or abs(sum(weights) - 1) > 1e-6:
            raise ValueError("Positive main weights must sum to 1")
        image = flattened(main[0]["plate"], main[0]["source"]).copy()
        accumulated = weights[0]
        for part, weight in zip(main[1:], weights[1:]):
            # Pillow blends in 8-bit display RGB, matching the PNG composition space.
            image = Image.blend(image, flattened(part["plate"], part["source"]), weight / (accumulated + weight))
            accumulated += weight
        if list(image.size) != list(plan["resolution"]):
            raise ValueError("Main plate dimensions do not match the output canvas")
        for overlay in row.get("overlays", []):
            alpha = float(overlay.get("alpha", 1))
            if not math.isfinite(alpha) or not 0 <= alpha <= 1:
                raise ValueError("Overlay alpha must be between 0 and 1")
            if alpha == 0:
                continue
            x, y, width, height = overlay["rect"]
            if any(type(v) is not int for v in (x, y, width, height)) or width < 1 or height < 1:
                raise ValueError("Overlay rectangles require integer coordinates and positive dimensions")
            if x < 0 or y < 0 or x + width > image.width or y + height > image.height:
                raise ValueError("Overlay lies outside the output canvas")
            tile = flattened(overlay["plate"], overlay["source"]).resize((width, height), Image.Resampling.LANCZOS)
            radius, border = int(overlay.get("radius", 0)), int(overlay.get("border", 0))
            if radius < 0 or border < 0:
                raise ValueError("Overlay border and radius must be nonnegative")
            if border:
                ImageDraw.Draw(tile).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius,
                    outline=tuple(overlay.get("border_rgb", [215, 220, 223])), width=border)
            mask = Image.new("L", tile.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=round(255 * alpha))
            image.paste(tile, (x, y), mask)
        return image
    return composite


def _sample_positions(count, limit=5):
    return sorted({round((count - 1) * i / max(1, min(limit, count) - 1)) for i in range(min(limit, count))})


def _contact_sheet(images, path):
    # images is a small list of (output-frame number, original-frame number, RGB image).
    width = 320
    aspect = images[0][2].height / images[0][2].width
    height = max(1, round(width * aspect))
    sheet = Image.new("RGB", (width * min(2, len(images)), (height + 26) * ((len(images) + 1) // 2)), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (frame, original, image) in enumerate(images):
        x, y = (i % 2) * width, (i // 2) * (height + 26)
        sheet.paste(image.resize((width, height), Image.Resampling.LANCZOS), (x, y))
        draw.text((x + 6, y + height + 6), f"output {frame} / original {original}", fill="black")
    _atomic_image(sheet, path)
    return list(sheet.size)


@contextmanager
def _imageio_executable(executable):
    # imageio-ffmpeg chooses its executable via an environment variable.
    with _IMAGEIO_ENV_LOCK:
        previous = os.environ.get("IMAGEIO_FFMPEG_EXE")
        os.environ["IMAGEIO_FFMPEG_EXE"] = str(executable)
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("IMAGEIO_FFMPEG_EXE", None)
            else:
                os.environ["IMAGEIO_FFMPEG_EXE"] = previous


def _strict_decode(executable, video, rows, plan, log):
    import imageio_ffmpeg
    run_logged([executable, "-hide_banner", "-v", "error", "-xerror", "-err_detect", "explode",
                "-i", str(video), "-map", "0:v:0", "-an", "-f", "null", "-"], log)
    if Path(log).read_bytes().strip():
        raise RuntimeError("Strict decoder reported an error; see " + str(log))
    samples, images, count = set(_sample_positions(len(rows))), [], 0
    with _imageio_executable(executable):
        reader = imageio_ffmpeg.read_frames(str(video), pix_fmt="rgb24")
        try:
            metadata = next(reader)
            if list(metadata["size"]) != list(plan["resolution"]) or abs(metadata["fps"] - plan["fps"]) > 0.001:
                raise RuntimeError("Decoded video resolution or frame rate differs from the plan")
            for index, raw in enumerate(reader):
                count += 1
                if index >= len(rows) or len(raw) != plan["resolution"][0] * plan["resolution"][1] * 3:
                    raise RuntimeError("Unexpected decoded frame count or byte size")
                if index in samples:
                    row = rows[index]
                    images.append((row["frame"], row.get("original_output_frame", row["frame"]),
                                   Image.frombytes("RGB", tuple(plan["resolution"]), raw)))
        finally:
            reader.close()
    if count != len(rows):
        raise RuntimeError(f"Decoded {count} frames, expected {len(rows)}")
    return images, {"frame_count": count, "fps": metadata["fps"], "resolution": list(metadata["size"])}


def _encode(project, plan, rows, composite, executable, temporary, log):
    width, height = plan["resolution"]
    if width % 2 or height % 2:
        raise ValueError("H.264/yuv420p output width and height must be even")
    cmd = [executable, "-hide_banner", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s:v", f"{width}x{height}", "-r", str(plan["fps"]), "-i", "pipe:0", "-an",
           "-c:v", ENCODER_PROFILE["codec"], "-preset", ENCODER_PROFILE["preset"],
           "-crf", str(ENCODER_PROFILE["crf"]), "-threads", str(ENCODER_PROFILE["threads"]),
           "-pix_fmt", ENCODER_PROFILE["pixel_format"], "-movflags", ENCODER_PROFILE["movflags"], str(temporary)]
    with Path(log).open("wb") as stderr:
        writer = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=stderr,
                                  creationflags=_creation_flags())
        last = 0.0
        try:
            for index, row in enumerate(rows, 1):
                writer.stdin.write(composite(row).tobytes())
                if time.monotonic() - last >= 0.5 or index == len(rows):
                    _status(project, "ENCODING", shot=plan["id"], encoded_input_frames=index,
                            total_video_frames=len(rows), pid=writer.pid)
                    last = time.monotonic()
            writer.stdin.close()
            if writer.wait():
                raise RuntimeError("FFmpeg encoding failed; see " + str(log))
        except BaseException:
            if writer.poll() is None:
                writer.kill()
            writer.wait()
            raise


def _compose_return(record, reused):
    keep = ("status", "kind", "video", "check", "contact_sheet", "frame_count", "fps", "resolution",
            "duration_s", "shot_duration_s", "selected_sample_count", "video_sha256", "full_decode",
            "plan_digest", "inputs_digest", "previews")
    return {k: record[k] for k in keep if k in record} | {"reused": reused}


def _existing_composition(path, inputs_digest):
    try:
        report = read_json(path)
        if (report.get("status") != "PASS" or report.get("inputs_digest") != inputs_digest
                or digest(report["inputs"]) != inputs_digest or not report["artifacts"]
                or digest(report["plan_snapshot"]) != report["plan_digest"]):
            return None
        for entry in report["artifacts"]:
            if not Path(entry["path"]).is_file() or sha256(entry["path"]) != entry["sha256"]:
                return None
        if report["kind"] == "VIDEO" and not (report.get("full_decode") and report.get("strict_decode_exit_code") == 0):
            return None
        return report
    except (OSError, ValueError, KeyError):
        return None


def compose_plan(project, plan, render_report, ffmpeg=None, frames=None):
    """Compose previews or a versioned, strictly decoded H.264 short video."""
    state = _state(project)
    rows = _rows(plan, frames)
    paths, keys, physical = _validate_render_report(project, plan, render_report, rows)
    source_images = []
    # Recheck even when a matching video already exists: compose-only never
    # silently accepts broken source PNGs in the supplied render report.
    for record in sorted(physical.values(), key=lambda r: str(r["path"])):
        if not valid_png(record["path"], record["size"]):
            raise RuntimeError("Missing/corrupt source PNG; run render first: " + str(record["path"]))
        source_images.append({"path": str(record["path"]), "size": record["size"], "sha256": sha256(record["path"])})
    preview = frames is not None
    executable, version = (None, None) if preview else _tool("ffmpeg", ffmpeg)
    if not preview:
        import imageio_ffmpeg
    implementation = sha256(__file__)
    inputs = {"plan_digest": digest(plan), "selected_frames": [r["frame"] for r in rows],
              "plate_keys": keys, "source_images": source_images, "pipeline_sha256": implementation,
              "pillow_version": PILLOW_VERSION, "ffmpeg_version": version,
              "ffmpeg_sha256": sha256(executable) if executable else None,
              "imageio_ffmpeg_version": imageio_ffmpeg.__version__ if not preview else None,
              "encoder_profile": None if preview else ENCODER_PROFILE, "kind": "PNG_PREVIEW" if preview else "VIDEO"}
    inputs_digest = digest(inputs)
    folder = _output(state, "previews" if preview else "outputs", _short(digest(plan)), _short(inputs_digest), "check.json").parent
    check = folder / "check.json"
    if check.exists():
        previous_binding = read_json(check)
        if previous_binding.get("inputs_digest") != inputs_digest:
            raise RuntimeError("Short composition key collision; refusing to replace another version")
    previous = _existing_composition(check, inputs_digest)
    if previous:
        _status(project, "PREVIEW_COMPLETE" if preview else "COMPLETE", shot=plan["id"], reused=True, check=str(check))
        return _compose_return(previous, True)
    composite = _composer(plan, paths)
    sheet = folder / "contact_sheet.png"
    temporary = None
    try:
        artifacts, previews, images = [], [], []
        if preview:
            samples = set(_sample_positions(len(rows), 12))
            for index, row in enumerate(rows):
                image = composite(row)
                path = folder / f"frame_{row['frame']:06d}.png"
                _atomic_image(image, path)
                if not valid_png(path, plan["resolution"]):
                    raise RuntimeError("Generated preview PNG failed CRC validation")
                artifacts.append({"path": str(path), "sha256": sha256(path)})
                previews.append(str(path))
                if index in samples:
                    images.append((row["frame"], row.get("original_output_frame", row["frame"]), image))
                _status(project, "PREVIEWING", shot=plan["id"], completed=index + 1, total=len(rows), counter_unit="preview_png")
            video = None
        else:
            video = folder / (_video_name(plan["id"]) + ".mp4")
            temporary = folder / (".t-" + uuid.uuid4().hex[:12] + ".mp4")
            _encode(project, plan, rows, composite, executable, temporary, folder / "encode.log")
            _status(project, "VERIFYING", shot=plan["id"], total_video_frames=len(rows))
            images, _ = _strict_decode(executable, temporary, rows, plan, folder / "strict_decode.log")
            temporary.replace(video)
            artifacts.append({"path": str(video), "sha256": sha256(video)})
        sheet_size = _contact_sheet(images, sheet)
        if not valid_png(sheet, sheet_size):
            raise RuntimeError("Contact sheet PNG failed validation")
        artifacts.append({"path": str(sheet), "sha256": sha256(sheet)})
        # Inputs are immutable for the entire operation, not merely at startup.
        for entry in source_images:
            if sha256(entry["path"]) != entry["sha256"]:
                raise RuntimeError("A source PNG changed during composition")
        _native(project, plan)
        _verify_assets(project)
        if digest(plan) != inputs["plan_digest"]:
            raise RuntimeError("Plan changed during composition")
        if sha256(__file__) != implementation:
            raise RuntimeError("Pipeline implementation changed during composition")
        record = {
            "status": "PASS", "kind": inputs["kind"], "video": str(video) if video else None,
            "check": str(check), "contact_sheet": str(sheet), "frame_count": len(rows),
            "fps": plan["fps"], "resolution": plan["resolution"],
            "duration_s": None if preview else len(rows) / plan["fps"],
            "shot_duration_s": len(plan["frames"]) / plan["fps"],
            "selected_sample_count": len(rows) if preview else None,
            "full_decode": not preview, "strict_decode_exit_code": 0 if not preview else None,
            "plan_digest": digest(plan), "inputs_digest": inputs_digest, "inputs": inputs,
            "plan_snapshot": plan,
            "artifacts": artifacts, "previews": previews,
            "video_sha256": artifacts[0]["sha256"] if not preview else None,
        }
        write_json(check, record)  # Last publication step: partial files never qualify.
        _status(project, "PREVIEW_COMPLETE" if preview else "COMPLETE", shot=plan["id"], reused=False,
                check=str(check), video=record["video"], frame_count=len(rows))
        return _compose_return(record, False)
    except Exception as exc:
        _status(project, "FAILED", operation="compose", shot=plan["id"], error=str(exc))
        raise
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def verify_output(report, ffmpeg=None):
    """Recheck the delivered version, without claiming it matches later edits."""
    check_path = Path(report["check"]).resolve()
    record = read_json(check_path)
    if record.get("status") != "PASS" or Path(record.get("check", "")).resolve() != check_path:
        raise RuntimeError("The delivery check is missing or does not identify itself")
    for field in ("kind", "plan_digest", "inputs_digest", "video"):
        if report.get(field) != record.get(field):
            raise RuntimeError("Delivery reference differs from its check: " + field)
    if digest(record["inputs"]) != record["inputs_digest"] or record["inputs"].get("plan_digest") != record["plan_digest"]:
        raise RuntimeError("Delivery provenance digest is inconsistent")
    if digest(record["plan_snapshot"]) != record["plan_digest"]:
        raise RuntimeError("Saved plan snapshot does not match the delivered version")
    selection = record["inputs"]["selected_frames"]
    if len(selection) != record["frame_count"] or not selection:
        raise RuntimeError("Delivery frame selection is inconsistent")
    artifacts = record.get("artifacts", [])
    if not artifacts:
        raise RuntimeError("Delivery check contains no artifact hashes")
    for entry in artifacts:
        path = Path(entry["path"]).resolve()
        if not path.is_relative_to(check_path.parent) or not path.is_file() or sha256(path) != entry["sha256"]:
            raise RuntimeError("Delivery artifact is missing or has changed: " + str(path))
    bound = {"status": "PASS", "kind": record["kind"], "check": str(check_path),
             "plan_digest": record["plan_digest"], "inputs_digest": record["inputs_digest"],
             "verification_scope": "delivered_version_only", "source_assets_revalidated": False}
    if record["kind"] == "PNG_PREVIEW":
        previews = record.get("previews", [])
        if len(previews) != record["frame_count"] or any(not valid_png(path, record["resolution"]) for path in previews):
            raise RuntimeError("Preview dimensions/CRC/count failed")
        return bound | {"frame_count": len(previews), "resolution": record["resolution"],
                        "fps": record["fps"], "full_decode": False, "preview_pngs_verified": True}
    if record["kind"] != "VIDEO" or not record.get("full_decode") or record.get("strict_decode_exit_code") != 0:
        raise RuntimeError("Delivery does not contain a successful full video decode")
    video = Path(record["video"]).resolve()
    current_sha = sha256(video)
    matching = [r for r in artifacts if Path(r["path"]).resolve() == video]
    if len(matching) != 1 or current_sha != record["video_sha256"] or matching[0]["sha256"] != current_sha:
        raise RuntimeError("Video hash is not bound by the delivery check")
    executable, version = _tool("ffmpeg", ffmpeg)
    state = next((p for p in check_path.parents if p.name == ".animation"), None)
    if state is None:
        raise ValueError("Verification requires a check in its project .animation directory")
    log = _output(state, "verifications", uuid.uuid4().hex[:12], "strict_decode.log")
    rows = [{"frame": frame, "original_output_frame": frame} for frame in selection]
    _, decoded = _strict_decode(executable, video, rows, record, log)
    return bound | decoded | {"current_sha": current_sha, "video": str(video), "full_decode": True,
                               "strict_decode_exit_code": 0, "ffmpeg_version": version, "log": str(log)}
