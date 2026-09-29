"""Agent-authored, bounded review requests and durable human feedback.

The browser supplies only control values. It cannot choose JSON paths, replace
project structure, or apply a response. Request snapshots and responses are
immutable; mutable lifecycle state is stored separately under the project lock.
"""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path
import re
import tempfile
import time
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .common import digest, file_lock, read_json, sha256, write_json
from .project import normalize_project


class ReviewError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _require(condition, message, status=400):
    if not condition:
        raise ReviewError(message, status)


def _fields(value, allowed, label, required=()):
    _require(isinstance(value, dict), f"{label}: expected object")
    _require(not set(value) - set(allowed), f"{label}: unsupported fields {sorted(set(value)-set(allowed))}")
    _require(set(required).issubset(value), f"{label}: missing fields {sorted(set(required)-set(value))}")


def _text(value, label, maximum=4000, empty=False):
    _require(isinstance(value, str) and (empty or bool(value.strip())) and len(value) <= maximum
             and "\0" not in value, f"{label}: expected {'text' if empty else 'nonempty text'} up to {maximum} characters")
    return value


def _number(value, label):
    _require(type(value) in (int, float) and math.isfinite(value), f"{label}: expected finite number")
    return value


def _id(value, label):
    _text(value, label, 80)
    _require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value), f"{label}: invalid identifier")
    return value


def _now():
    return datetime.now(timezone.utc).isoformat()


def normalize_ui_language(value):
    """Resolve the agent's conversation language without changing authored text."""
    _require(isinstance(value, str), "ui_language must be en, zh-Hans, or zh-Hant")
    tag = value.strip().replace("_", "-").lower()
    aliases = {"english": "en", "chinese": "zh-Hans", "简体中文": "zh-Hans",
               "简体": "zh-Hans", "简中": "zh-Hans", "中文": "zh-Hans",
               "繁體中文": "zh-Hant", "繁体中文": "zh-Hant", "繁體": "zh-Hant",
               "繁体": "zh-Hant", "繁中": "zh-Hant"}
    if tag in aliases:
        return aliases[tag]
    _require(bool(re.fullmatch(r"(?:en|zh)(?:-[a-z0-9]{1,8})*", tag)),
             "ui_language must be en, zh-Hans, or zh-Hant")
    parts = tag.split("-")
    if parts[0] == "en":
        return "en"
    if "hant" in parts:
        return "zh-Hant"
    if "hans" in parts:
        return "zh-Hans"
    return "zh-Hant" if set(parts) & {"tw", "hk", "mo"} else "zh-Hans"


def review_url(request, base_url="http://127.0.0.1:8766"):
    """Build a review link with conversation context, not a manual UI override."""
    base = urlsplit(base_url)
    query = [(key, value) for key, value in parse_qsl(base.query, keep_blank_values=True)
             if key not in {"request", "context_lang"}]
    query.append(("request", request["id"]))
    if "ui_language" in request:
        query.append(("context_lang", normalize_ui_language(request["ui_language"])))
    return urlunsplit((base.scheme, base.netloc, "/preview/" + request["stage"],
                       urlencode(query), base.fragment))


def _clean(project):
    return {key: deepcopy(value) for key, value in project.items() if not key.startswith("_")}


def _normalize(raw, path):
    try:
        return normalize_project(raw, path)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise ReviewError("Invalid review candidate: " + str(exc)) from exc


def _project_path(path):
    path = Path(path).expanduser().resolve()
    _require(path.is_file(), f"Project not found: {path}", 409)
    return path


def _folder(path):
    return path.parent / ".animation" / "review"


@contextmanager
def _locked(path):
    # Read/preview polls and listener heartbeats are short operations. Retry a
    # briefly occupied lock instead of letting normal polling terminate wait.
    deadline = time.monotonic() + 1
    stack = ExitStack()
    while True:
        try:
            stack.enter_context(file_lock(path.parent / ".animation" / "project.lock"))
            break
        except RuntimeError as exc:
            if time.monotonic() >= deadline:
                stack.close()
                raise ReviewError(str(exc), 409) from exc
            time.sleep(.02)
    try:
        with stack:
            yield
    except RuntimeError as exc:
        raise ReviewError(str(exc), 409) from exc


def _pointer(base, pointer):
    _require(isinstance(pointer, str) and pointer.startswith("/") and len(pointer) <= 500,
             "binding.path must be an existing JSON Pointer")
    parts = pointer[1:].split("/")
    # Allowed field names and indices contain no escapes. Reject alternate
    # spellings so prefix/conflict checks cannot be bypassed.
    _require(all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*|0|[1-9][0-9]*", p) for p in parts),
             "binding.path contains an unsupported token")
    cursor = base
    for token in parts:
        if isinstance(cursor, dict):
            _require(token in cursor, "binding.path does not exist: " + pointer)
            cursor = cursor[token]
        elif isinstance(cursor, list):
            _require(token.isdigit() and int(token) < len(cursor), "binding.path index is invalid: " + pointer)
            cursor = cursor[int(token)]
        else:
            raise ReviewError("binding.path traverses a scalar: " + pointer)
    return parts, cursor


def _allowed_path(path, stage):
    index = r"(?:0|[1-9][0-9]*)"
    component = r"(?:/[0-3])?"
    patterns = []
    if stage == "model":
        patterns += [rf"/scene/objects/{index}/(?:location|rotation_deg|scale|dimensions){component}",
                     rf"/scene/objects/{index}/bevel",
                     rf"/(?:scene|source/overrides)/materials/{index}/(?:color{component}|roughness|metallic)",
                     r"/scene/background(?:/[0-2])?", r"/scene/world_strength"]
    if stage in ("model", "motion"):
        patterns += [rf"/source/overrides/objects/{index}/(?:location|rotation_deg|scale){component}"]
    if stage == "motion":
        patterns += [rf"/scene/animation/{index}/keys/{index}/(?:frame|interpolation|value(?:/[0-2])?)",
                     rf"/shots/{index}/timing/{index}/frames"]
    if stage in ("model", "camera"):
        patterns += [rf"/(?:scene|source/overrides)/cameras/{index}/(?:location{component}|target{component}|ortho_scale|lens)",
                     rf"/scene/cameras/{index}/type",
                     rf"/scene/lights/{index}/(?:location{component}|target{component}|energy|size)"]
    if stage == "camera":
        patterns += [rf"/shots/{index}/camera"]
    if stage == "delivery":
        patterns += [r"/render/(?:fps|samples|engine|transparent|resolution(?:/[01])?)",
                     rf"/shots/{index}/timing/{index}/frames"]
    return any(re.fullmatch(pattern, path) for pattern in patterns)


def _set(base, parts, value):
    cursor = base
    for part in parts[:-1]:
        cursor = cursor[int(part)] if isinstance(cursor, list) else cursor[part]
    leaf = int(parts[-1]) if isinstance(cursor, list) else parts[-1]
    cursor[leaf] = deepcopy(value)


def _same_shape(value, original, label):
    if type(original) in (int, float):
        _number(value, label)
        if type(original) is int:
            # Frame counts and resolution require actual ints, but coordinates
            # written as `0` still accept fractions. Final schema validation
            # rejects fractions only where the parameter requires an integer.
            return int(value) if float(value).is_integer() else float(value)
        return float(value)
    if type(original) is bool:
        _require(type(value) is bool, label + ": target requires a boolean")
    elif isinstance(original, str):
        _text(value, label, 1000)
    elif isinstance(original, list):
        _require(isinstance(value, list) and len(value) == len(original)
                 and all(type(x) in (int, float) for x in original), label + ": expected an existing numeric vector")
        return [_same_shape(v, old, label) for v, old in zip(value, original)]
    else:
        raise ReviewError(label + ": only scalar and fixed numeric-vector leaves are editable")
    return deepcopy(value)


def _control_value(control, value):
    name = "control " + control["id"]
    if control["kind"] == "number":
        _number(value, name)
        _require(control["min"] <= value <= control["max"], name + ": value is outside the permitted range")
        ticks = (value - control["min"]) / control["step"]
        _require(abs(ticks - round(ticks)) <= 1e-6, name + ": value does not match the permitted step")
    elif control["kind"] == "color":
        _require(isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value), name + ": expected #rrggbb")
        value = value.lower()
    else:
        _require(isinstance(value, str) and value in [option["value"] for option in control["options"]],
                 name + ": unknown choice")
    return value


def _binding_value(control, binding, value, original):
    if control["kind"] == "number":
        output = value * binding.get("scale", 1) + binding.get("offset", 0)
        return _same_shape(output, original, binding["path"])
    if control["kind"] == "color":
        _require(isinstance(original, list) and len(original) in (3, 4)
                 and all(type(x) in (int, float) for x in original), "Color bindings need a color vector")
        rgb = [int(value[i:i+2], 16) / 255 for i in (1, 3, 5)]
        return rgb + original[3:]
    return _same_shape(binding["choices"][value], original, binding["path"])


def _near(left, right):
    if type(left) in (int, float) and type(right) in (int, float):
        return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_near(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def _controls(raw, base, stage):
    _require(isinstance(raw, list) and len(raw) <= 12,
             "controls: provide 0–12 explicit controls; visual-only reviews may have none")
    result, ids, paths = deepcopy(raw), set(), []
    for control in result:
        kind = control.get("kind") if isinstance(control, dict) else None
        _require(isinstance(kind, str) and kind in ("number", "color", "choice"), "control.kind must be number, color, or choice")
        extra = {"min", "max", "step"} if kind == "number" else {"options"} if kind == "choice" else set()
        _fields(control, {"id", "label", "kind", "unit", "description", "value", "bindings"} | extra,
                "control", {"id", "label", "kind", "value", "bindings"} | extra)
        ident = _id(control["id"], "control.id")
        _require(ident not in ids, "Duplicate control id: " + ident)
        ids.add(ident)
        _text(control["label"], "control.label", 160)
        for key in ("unit", "description"):
            if key in control:
                _text(control[key], "control." + key, 1000, True)
        if kind == "number":
            for key in ("min", "max", "step"):
                _number(control[key], "control." + key)
            _require(control["min"] < control["max"] and control["step"] > 0, "Control range or step is invalid")
            _require((control["max"] - control["min"]) / control["step"] <= 1e9, "Control has too many steps")
        if kind == "choice":
            _require(isinstance(control["options"], list) and 1 <= len(control["options"]) <= 24, "choice.options needs 1–24 options")
            options = set()
            for option in control["options"]:
                _fields(option, {"value", "label"}, "choice option", {"value", "label"})
                _text(option["value"], "option.value", 100)
                _text(option["label"], "option.label", 160)
                _require(option["value"] not in options, "Duplicate option value")
                options.add(option["value"])
        control["value"] = _control_value(control, control["value"])
        bindings = control["bindings"]
        _require(isinstance(bindings, list) and 1 <= len(bindings) <= 100, "control.bindings needs 1–100 explicit bindings")
        for binding in bindings:
            allowed = {"path", "scale", "offset"} if kind == "number" else {"path", "choices"} if kind == "choice" else {"path"}
            _fields(binding, allowed, "binding", {"path", "choices"} if kind == "choice" else {"path"})
            pointer = binding["path"]
            parts, original = _pointer(base, pointer)
            _require(_allowed_path(pointer, stage), f"Binding is not an allowed {stage} parameter: {pointer}")
            _require(not any(pointer == old or pointer.startswith(old + "/") or old.startswith(pointer + "/") for old in paths),
                     "Conflicting or duplicate binding: " + pointer)
            paths.append(pointer)
            if kind == "number":
                _require(type(original) in (int, float), "Number bindings require a numeric leaf")
                for key in ("scale", "offset"):
                    _number(binding.get(key, 1 if key == "scale" else 0), "binding." + key)
                _require(binding.get("scale", 1) != 0, "binding.scale cannot be zero")
            if kind == "color":
                _require(parts[-1] in ("color", "background"), "Color controls can only bind color vectors")
            if kind == "choice":
                _require(isinstance(binding["choices"], dict) and set(binding["choices"]) == options,
                         "binding.choices must map every option, with no extra choices")
                for mapped in binding["choices"].values():
                    _same_shape(mapped, original, pointer)
            mapped = _binding_value(control, binding, control["value"], original)
            # Hex colors are quantized. Permit their rounded display default and
            # retain the exact original vector until the user changes that value.
            if kind == "color":
                expected = "#" + "".join(f"{max(0, min(255, math.floor(x * 255 + .5))):02x}" for x in original[:3])
                _require(control["value"] == expected, "Default color must match the frozen project: " + pointer)
            else:
                _require(_near(mapped, original), "Control default must match the frozen project: " + pointer)
    return result


def _references(base, path, asset_hashes):
    if "scene" in base:
        scene = base["scene"]
        return ({entry["id"] for group in ("objects", "cameras", "lights") for entry in scene[group]},
                {entry["id"] for entry in scene["cameras"]})
    source = base["source"]
    overrides = source.get("overrides", {})
    objects = {entry["id"] for group in ("objects", "cameras") for entry in overrides.get(group, [])}
    cameras = {shot["camera"] for shot in base["shots"]} | {entry["id"] for entry in overrides.get("cameras", [])}
    objects.update(cameras)
    # Never invoke Blender just to create a scope. Existing verified discovery
    # is sufficient; undeclared names require discovery first.
    state = path.parent / ".animation"
    discovery_roots = (state / "native-discovery", state / "editor/import/native-discovery")
    reports = [report for folder in discovery_roots for report in folder.glob("*/manifest.json")]
    for report in reports:
        try:
            data = read_json(report)
            if data.get("source_sha256") != asset_hashes.get(source["blend"]):
                continue
            manifest = data["manifest"]
            if manifest.get("scene") != source["scene"]:
                continue
            for group in ("objects", "cameras", "lights"):
                objects.update(item["id"] for item in manifest.get(group, []))
            cameras.update(item["id"] for item in manifest.get("cameras", []))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return objects, cameras


def _frame_range(value, label):
    _require(isinstance(value, list) and len(value) == 2
             and all(type(x) is int and 1 <= x <= 1000000 for x in value) and value[0] <= value[1],
             label + ": expected ascending positive integer frame range")
    return value


def _evidence(value, path, focus, cameras, base=None, asset_hashes=None):
    _fields(value, {"references", "checkpoints", "findings", "reports"}, "evidence")
    _require(any(key in value for key in ("references", "findings", "reports")),
             "evidence needs references, findings or reports")
    value.setdefault("references", [])
    if "reports" in value:
        from .review_diagnostics import attach_reports
        value = attach_reports(value, {**base, "_review_focus": focus}, path, asset_hashes)
    references = value["references"]
    _require(isinstance(references, list) and len(references) <= 6,
             "evidence.references needs at most 6 images")
    reference_ids = set()
    for reference in references:
        _fields(reference, {"id", "title", "path"}, "reference", {"id", "title", "path"})
        ident = _id(reference["id"], "reference.id")
        _require(ident not in reference_ids, "Duplicate reference id")
        reference_ids.add(ident)
        _text(reference["title"], "reference.title", 200)
        raw_path = _text(reference["path"], "reference.path", 4096)
        # A Windows drive path is a file location; URI schemes are never fetched.
        _require(not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw_path)
                 or re.match(r"^[A-Za-z]:[\\/]", raw_path), "reference.path must be a local image path")
        image_path = Path(raw_path).expanduser()
        image_path = (image_path if image_path.is_absolute() else path.parent / image_path).resolve()
        _require(image_path.is_file() and image_path.suffix.lower() in (".png", ".jpg", ".jpeg"),
                 "reference.path must be an existing PNG or JPG")
        with image_path.open("rb") as stream:
            header = stream.read(8)
        _require(header == b"\x89PNG\r\n\x1a\n" if image_path.suffix.lower() == ".png"
                 else header.startswith(b"\xff\xd8\xff"), "reference.path must contain a PNG or JPG image")
        reference.update(path=str(image_path), sha256=sha256(image_path))
    checkpoints = value.setdefault("checkpoints", [])
    _require(isinstance(checkpoints, list) and len(checkpoints) <= 12,
             "evidence.checkpoints needs at most 12 checkpoints")
    checkpoint_ids = set()
    a, b = focus["source_range"]
    for checkpoint in checkpoints:
        _fields(checkpoint, {"id", "title", "source_frame", "camera_id", "reference_id", "object_ids"},
                "checkpoint", {"id", "title", "source_frame", "camera_id", "reference_id"})
        ident = _id(checkpoint["id"], "checkpoint.id")
        _require(ident not in checkpoint_ids, "Duplicate checkpoint id")
        checkpoint_ids.add(ident)
        _text(checkpoint["title"], "checkpoint.title", 200)
        _require(type(checkpoint["source_frame"]) is int and a <= checkpoint["source_frame"] <= b,
                 "Checkpoint frame lies outside the focus range")
        _require(isinstance(checkpoint["camera_id"], str) and checkpoint["camera_id"] in cameras,
                 "Unknown checkpoint camera")
        _require(isinstance(checkpoint["reference_id"], str) and checkpoint["reference_id"] in reference_ids,
                 "Unknown checkpoint reference")
        if "object_ids" in checkpoint:
            objects = checkpoint["object_ids"]
            _require(isinstance(objects, list) and len(objects) <= 30
                     and all(isinstance(item, str) for item in objects),
                     "checkpoint.object_ids must be a list of focus object ids")
            _require(len(set(objects)) == len(objects) and set(objects).issubset(focus["object_ids"]),
                     "checkpoint.object_ids must be unique and within the review focus")
    findings = value.get("findings", [])
    _require(isinstance(findings, list) and len(findings) <= 24, "evidence.findings needs at most 24 findings")
    finding_ids = set()
    for finding in findings:
        _fields(finding, {"id", "title", "severity", "object_ids", "source_frame", "camera_id", "reference_id"},
                "finding", {"id", "title", "severity", "object_ids", "source_frame", "camera_id"})
        ident = _id(finding["id"], "finding.id")
        _require(ident not in finding_ids, "Duplicate finding id")
        finding_ids.add(ident)
        _text(finding["title"], "finding.title", 200)
        _require(finding["severity"] in ("info", "warning", "error"), "Unknown finding severity")
        ids = finding["object_ids"]
        _require(isinstance(ids, list) and 1 <= len(ids) <= 30 and all(isinstance(item, str) for item in ids)
                 and len(ids) == len(set(ids)) and set(ids).issubset(focus["object_ids"]),
                 "finding.object_ids must be unique and within review focus")
        _require(type(finding["source_frame"]) is int and a <= finding["source_frame"] <= b,
                 "Finding frame lies outside the focus range")
        _require(isinstance(finding["camera_id"], str) and finding["camera_id"] in cameras, "Unknown finding camera")
        if "reference_id" in finding:
            _require(isinstance(finding["reference_id"], str) and finding["reference_id"] in reference_ids,
                     "Unknown finding reference")
    return value


def _check_reference_hashes(request):
    for reference in request.get("evidence", {}).get("references", []):
        _require(Path(reference["path"]).is_file() and sha256(reference["path"]) == reference["sha256"],
                 "Review reference changed; ask the agent for a new review", 409)
    from .review_diagnostics import check_reports
    check_reports(request.get("evidence", {}))


def _validate_spec(spec, base, path, asset_hashes, thread_id):
    _fields(spec, {"title", "question", "context", "thread_id", "stage", "segments", "focus", "controls", "media", "evidence", "inspection", "ui_language"},
            "review spec", {"title", "question", "stage", "segments", "focus", "controls"})
    spec = deepcopy(spec)
    if "ui_language" in spec:
        spec["ui_language"] = normalize_ui_language(spec["ui_language"])
    claimed_thread = spec.get("thread_id")
    if "thread_id" in spec:
        _text(claimed_thread, "spec.thread_id", 160)
    if claimed_thread and thread_id:
        _require(claimed_thread == thread_id, "Spec belongs to a different agent task", 409)
    thread_id = thread_id or claimed_thread
    _text(thread_id, "thread_id", 160)
    _require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", thread_id), "thread_id is invalid")
    spec["thread_id"] = thread_id
    _text(spec["title"], "title", 200)
    _text(spec["question"], "question", 2000)
    _text(spec.setdefault("context", ""), "context", 4000, True)
    stage = spec["stage"]
    _require(isinstance(stage, str) and stage in ("model", "motion", "camera", "delivery"), "Unknown review stage")
    segments = spec["segments"]
    _require(isinstance(segments, list) and 1 <= len(segments) <= 40, "segments needs 1–40 segments")
    segment_ids = set()
    low = min(shot["source_range"][0] for shot in base["shots"])
    high = max(shot["source_range"][1] for shot in base["shots"])
    for segment in segments:
        _fields(segment, {"id", "title", "source_range"}, "segment", {"id", "title", "source_range"})
        ident = _id(segment["id"], "segment.id")
        _require(ident not in segment_ids, "Duplicate segment id")
        segment_ids.add(ident)
        _text(segment["title"], "segment.title", 200)
        a, b = _frame_range(segment["source_range"], "segment.source_range")
        _require(low <= a <= b <= high, "Segment lies outside project shot frames")
    focus = spec["focus"]
    _fields(focus, {"shot_id", "segment_id", "object_ids", "object_labels", "source_frame", "source_range", "camera_id"},
            "focus", {"shot_id", "segment_id", "object_ids", "source_frame", "source_range", "camera_id"})
    shots = {shot["id"]: shot for shot in base["shots"]}
    _require(isinstance(focus["shot_id"], str) and focus["shot_id"] in shots, "focus.shot_id is unknown")
    shot = shots[focus["shot_id"]]
    _require(isinstance(focus["segment_id"], str) and focus["segment_id"] in segment_ids, "focus.segment_id is unknown")
    a, b = _frame_range(focus["source_range"], "focus.source_range")
    _require(shot["source_range"][0] <= a <= b <= shot["source_range"][1], "Focus range lies outside selected shot")
    _require(type(focus["source_frame"]) is int and a <= focus["source_frame"] <= b, "Focus frame lies outside focus range")
    selected_segment = next(item for item in segments if item["id"] == focus["segment_id"])
    _require(a <= selected_segment["source_range"][0] <= selected_segment["source_range"][1] <= b,
             "Focused segment lies outside focus range")
    objects, cameras = _references(base, path, asset_hashes)
    _require(isinstance(focus["object_ids"], list) and len(focus["object_ids"]) <= 30
             and all(isinstance(x, str) for x in focus["object_ids"]), "focus.object_ids must be a list of known ids")
    _require(len(set(focus["object_ids"])) == len(focus["object_ids"]), "Duplicate focus object")
    _require(set(focus["object_ids"]).issubset(objects), "Unknown focus object; discover native objects before reviewing")
    _require(isinstance(focus["camera_id"], str) and focus["camera_id"] in cameras, "Unknown focus camera")
    if "object_labels" in focus:
        labels = focus["object_labels"]
        _require(isinstance(labels, dict) and len(labels) <= 30 and set(labels).issubset(objects),
                 "focus.object_labels must label known objects (at most 30)")
        for label in labels.values():
            _text(label, "focus.object_labels display name", 80)
    spec["controls"] = _controls(spec["controls"], base, stage)
    if "inspection" in spec:
        inspection = spec["inspection"]
        _fields(inspection, {"tools", "object_ids"}, "inspection", {"tools", "object_ids"})
        tools = inspection["tools"]
        _require(isinstance(tools, list) and all(isinstance(item, str) for item in tools)
                 and len(tools) == len(set(tools)) and set(tools).issubset({"point", "measure", "isolate", "xray"}),
                 "inspection.tools must contain unique supported tools")
        ids = inspection["object_ids"]
        _require(isinstance(ids, list) and 1 <= len(ids) <= 30 and all(isinstance(item, str) for item in ids)
                 and len(ids) == len(set(ids)) and set(ids).issubset(focus["object_ids"]),
                 "inspection.object_ids must be unique and within review focus")
    if "evidence" in spec:
        spec["evidence"] = _evidence(spec["evidence"], path, focus, cameras, base, asset_hashes)
    if "media" in spec:
        _fields(spec["media"], {"path"}, "media", {"path"})
        _text(spec["media"]["path"], "media.path", 4096)
        media_path = Path(spec["media"]["path"]).expanduser()
        media_path = (media_path if media_path.is_absolute() else path.parent / media_path).resolve()
        _require(media_path.is_file() and media_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".mp4"),
                 "media.path must be an existing PNG, JPG, or MP4")
        spec["media"] = {"path": str(media_path), "sha256": sha256(media_path)}
    return spec


def _load(path, request_id=None, current_required=True):
    folder = _folder(path)
    current_path = folder / "current.json"
    if not current_path.exists():
        _require(request_id is None, "No current review request", 409)
        return None
    current = read_json(current_path)
    _require(current.get("project") == str(path), "Review belongs to a different project", 409)
    selected = request_id or current["id"]
    _id(selected, "request_id")
    if current_required:
        _require(selected == current["id"], "Review request was superseded; refresh the preview", 409)
    location = folder / "requests" / selected
    _require((location / "request.json").is_file(), "Unknown review request", 409)
    record = read_json(location / "request.json")
    _require(record.get("project") == str(path) and record["request"]["id"] == selected,
             "Review identity mismatch", 409)
    state = read_json(location / "state.json")
    response = read_json(location / "response.json") if (location / "response.json").exists() else None
    if response:
        claimed = response.get("digest")
        _require(claimed == digest({k: v for k, v in response.items() if k != "digest"}), "Review response digest mismatch", 409)
        _require(response["request_id"] == selected and response["thread_id"] == record["request"]["thread_id"]
                 and response["revision"] == record["request"]["revision"] and response["project"] == str(path),
                 "Response belongs to a different review, project, or agent task", 409)
        if state["status"] == "pending":
            # response.json is the commit point for an immutable submission.
            # Recover a process exit before the small state update completed.
            state.update(status="submitted", message="Feedback saved; waiting for the agent to process it")
            write_json(location / "state.json", state)
    if selected != current["id"] and state["status"] in ("pending", "submitted"):
        state.update(status="superseded", message="Agent created a newer review request", superseded_at=_now())
        write_json(location / "state.json", state)
    return record, state, response, location


def _public(data):
    record, state, response, _ = data
    request = deepcopy(record["request"])
    heartbeat = state.get("listener", {})
    listening = heartbeat.get("expires_at", 0) > time.time() and state["status"] == "pending"
    result = {"request": request, "status": state["status"],
              "baseline_project": deepcopy(record["base"]),
              "values": deepcopy(response["values"] if response else {c["id"]: c["value"] for c in request["controls"]}),
              "response": deepcopy(response), "agent_listening": listening,
              "url": review_url(request)}
    for key in ("message", "received_at", "received_by_thread", "applied_at", "applied_revision", "closed_at"):
        if key in state:
            result[key] = state[key]
    if state.get("received_at") and response:
        result["response"]["received_at"] = state["received_at"]
        result["response"]["received_by_thread"] = state["received_by_thread"]
    return result


def _assert_pending_identity(path, data, request_id, revision, statuses=("pending",)):
    record, state, _, _ = data
    _require(record["request"]["id"] == request_id, "Review request identity mismatch", 409)
    _require(isinstance(revision, str) and revision == record["request"]["revision"], "Review revision mismatch", 409)
    _require(state["status"] in statuses, "Review is no longer editable: " + state["status"], 409)
    _require(sha256(path) == revision, "Project changed since this review was created; ask the agent for a fresh review", 409)


def _candidate(record, values, path):
    controls = record["request"]["controls"]
    _require(isinstance(values, dict) and set(values) == {control["id"] for control in controls},
             "Values must contain exactly the allowed control ids")
    candidate = deepcopy(record["base"])
    cleaned, changes = {}, []
    for control in controls:
        value = _control_value(control, values[control["id"]])
        cleaned[control["id"]] = value
        for binding in control["bindings"]:
            parts, before = _pointer(record["base"], binding["path"])
            # No quantization or floating-point drift merely from confirming the
            # default, including a hex view of a high-precision material color.
            after = before if value == control["value"] else _binding_value(control, binding, value, before)
            if not _near(before, after):
                _set(candidate, parts, after)
                changes.append({"path": binding["path"], "before": deepcopy(before), "after": deepcopy(after)})
    normalized = _normalize(candidate, path)
    _require(normalized["_asset_hashes"] == record["asset_hashes"], "A source asset changed since review creation", 409)
    media = record["request"].get("media")
    if media:
        _require(Path(media["path"]).is_file() and sha256(media["path"]) == media["sha256"],
                 "Review media changed; ask the agent for a new review", 409)
    _check_reference_hashes(record["request"])
    return {"project": _clean(normalized), "values": cleaned, "changes": changes}


def create_request(project_path, spec, thread_id=None):
    path = _project_path(project_path)
    with _locked(path):
        revision = sha256(path)
        normalized = _normalize(read_json(path), path)
        base = _clean(normalized)
        request = _validate_spec(spec, base, path, normalized["_asset_hashes"], thread_id)
        _require(sha256(path) == revision, "Project changed during review creation", 409)
        request.update(id="review-" + uuid.uuid4().hex, revision=revision, created_at=_now())
        record = {"schema_version": 1, "project": str(path), "request": request,
                  "base": base, "asset_hashes": normalized["_asset_hashes"]}
        state = {"status": "pending"}
        location = _folder(path) / "requests" / request["id"]
        # Validate the unchanged default candidate before publishing anything.
        _candidate(record, {c["id"]: c["value"] for c in request["controls"]}, path)
        previous = _load(path)
        write_json(location / "request.json", record)
        write_json(location / "state.json", state)
        write_json(_folder(path) / "current.json", {"project": str(path), "id": request["id"]})
        if previous and previous[1]["status"] not in ("applied", "closed", "superseded"):
            previous[1].update(status="superseded", message="Agent created a newer review request", superseded_at=_now())
            write_json(previous[3] / "state.json", previous[1])
        return _public((record, state, None, location))


def get_review(project_path):
    path = _project_path(project_path)
    with _locked(path):
        data = _load(path)
        return _public(data) if data else None


def preview_review(project_path, request_id, revision, values):
    path = _project_path(project_path)
    with _locked(path):
        data = _load(path, request_id)
        _assert_pending_identity(path, data, request_id, revision, ("pending", "submitted"))
        result = _candidate(data[0], values, path)
        _require(sha256(path) == revision, "Project changed while preparing the preview", 409)
        return result


def _annotation(value, request, objects):
    if value is None:
        return None
    _fields(value, {"object_id", "source_frame", "segment_id", "shot_id", "reference_id", "reference_uv", "checkpoint_id", "finding_id", "points", "preview_variant"}, "annotation")
    if "preview_variant" in value:
        _require("points" in value and value["preview_variant"] in ("original", "candidate"),
                 "Surface preview_variant requires points and must be original or candidate")
    _require(bool(value), "annotation must identify an object, frame, segment, shot, reference, or checkpoint")
    if "object_id" in value:
        _require(isinstance(value["object_id"], str) and value["object_id"] in objects, "Unknown annotation object")
    if "source_frame" in value:
        a, b = request["focus"]["source_range"]
        _require(type(value["source_frame"]) is int and a <= value["source_frame"] <= b, "Annotation frame lies outside the review")
    if "segment_id" in value:
        _require(isinstance(value["segment_id"], str) and value["segment_id"] in {item["id"] for item in request["segments"]}, "Unknown annotation segment")
    if "shot_id" in value:
        _require(value["shot_id"] == request["focus"]["shot_id"], "Annotation references another shot")
    evidence = request.get("evidence", {})
    if "reference_id" in value:
        _require(isinstance(value["reference_id"], str)
                 and value["reference_id"] in {item["id"] for item in evidence.get("references", [])},
                 "Unknown annotation reference")
    if "reference_uv" in value:
        uv = value["reference_uv"]
        _require("reference_id" in value, "reference_uv requires reference_id")
        _require(isinstance(uv, list) and len(uv) == 2
                 and all(type(item) in (int, float) and math.isfinite(item) and 0 <= item <= 1 for item in uv),
                 "reference_uv must contain two finite normalized coordinates from 0 to 1")
    if "checkpoint_id" in value:
        checkpoints = {item["id"]: item for item in evidence.get("checkpoints", [])}
        ident = value["checkpoint_id"]
        _require(isinstance(ident, str) and ident in checkpoints, "Unknown annotation checkpoint")
        checkpoint = checkpoints[ident]
        _require(value.get("source_frame") == checkpoint["source_frame"],
                 "Checkpoint annotation requires its exact source_frame")
        _require("reference_id" not in value or value["reference_id"] == checkpoint["reference_id"],
                 "Annotation reference does not match its checkpoint")
    if "finding_id" in value:
        findings = {item["id"]: item for item in evidence.get("findings", [])}
        ident = value["finding_id"]
        _require(isinstance(ident, str) and ident in findings, "Unknown annotation finding")
        finding = findings[ident]
        _require(value.get("source_frame") == finding["source_frame"], "Finding annotation requires its exact source_frame")
        if "reference_id" in value and "reference_id" in finding:
            _require(value["reference_id"] == finding["reference_id"], "Annotation reference does not match its finding")
    result = deepcopy(value)
    if "points" in value:
        inspection = request.get("inspection", {})
        points = value["points"]
        _require(isinstance(points, list) and 1 <= len(points) <= 2, "Surface annotation needs one or two points")
        _require("source_frame" in value, "Surface annotation requires its source frame")
        permitted = set(inspection.get("tools", []))
        _require(bool(permitted & {"point", "measure"}) and (len(points) == 1 or "measure" in permitted),
                 "This review does not permit the requested surface inspection")
        for point in points:
            _fields(point, {"object_id", "local", "world"}, "surface point", {"object_id", "local", "world"})
            _require(isinstance(point["object_id"], str) and point["object_id"] in inspection.get("object_ids", []),
                     "Surface point is outside permitted inspection objects")
            for field in ("local", "world"):
                vector = point[field]
                _require(isinstance(vector, list) and len(vector) == 3
                         and all(type(item) in (int, float) and math.isfinite(item) and abs(item) <= 1e9 for item in vector),
                         "Surface coordinates must be three finite preview coordinates")
        result["coordinate_space"] = "three-preview"
        if len(points) == 2:
            result["measurement"] = {"distance": math.dist(points[0]["world"], points[1]["world"]),
                                     "units": "preview_world_units", "verified_geometry": False}
    return result


def submit_review(project_path, request_id, revision, values, decision, note="", annotation=None):
    path = _project_path(project_path)
    with _locked(path):
        data = _load(path, request_id)
        record, state, previous, location = data
        if previous:
            _require(revision == record["request"]["revision"] and state["status"] in ("submitted", "applied", "closed"),
                     "Review revision or lifecycle no longer permits this submission", 409)
        else:
            _assert_pending_identity(path, data, request_id, revision)
        _require(isinstance(decision, str) and decision in ("confirm", "revise"), "decision must be confirm or revise")
        _text(note, "note", 8000, decision == "confirm")
        candidate = _candidate(record, values, path)
        objects, _ = _references(record["base"], path, record["asset_hashes"])
        annotation = _annotation(annotation, record["request"], objects)
        if annotation and annotation.get("points"):
            variant = annotation.setdefault("preview_variant", "candidate")
            annotation["sampled_values"] = (deepcopy({control["id"]: control["value"] for control in record["request"]["controls"]})
                                             if variant == "original" else deepcopy(candidate["values"]))
        if annotation and annotation.get("measurement") and not record["base"].get("source"):
            # Procedural preview world coordinates use meters, just like the
            # Blender builder. Native exports retain unspecified preview units.
            units = record["base"].get("units", "m")
            measurement = annotation["measurement"]
            measurement.update(units="m", display_units=units,
                               display_distance=measurement["distance"] / {"m": 1, "cm": .01, "mm": .001}[units])
        content = {"request_id": request_id, "thread_id": record["request"]["thread_id"],
                   "project": str(path), "revision": revision, "stage": record["request"]["stage"],
                   "focus": deepcopy(record["request"]["focus"]), "decision": decision,
                   "note": note, "annotation": annotation, "values": candidate["values"], "changes": candidate["changes"]}
        if previous:
            comparable = {key: value for key, value in previous.items() if key not in ("digest", "submitted_at")}
            _require(content == comparable, "Feedback was already submitted and cannot be replaced; request a new review", 409)
            return _public(data)
        _require(sha256(path) == revision, "Project changed while preparing feedback", 409)
        content["submitted_at"] = _now()
        content["digest"] = digest(content)
        write_json(location / "response.json", content)
        state.update(status="submitted", message="Feedback saved; waiting for the agent to process it")
        write_json(location / "state.json", state)
        return _public((record, state, content, location))


def _written_digest(value):
    import json
    return hashlib.sha256((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")).hexdigest()


def _archive_exact(path, original, revision):
    archive = path.parent / ".animation" / "revisions" / (revision + ".json")
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        _require(sha256(archive) == revision, "Existing revision archive is damaged; refusing to replace it", 409)
        return
    handle, temporary = tempfile.mkstemp(prefix=".review-", suffix=".tmp", dir=archive.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, archive)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _patch_declared(raw, base, parts, value):
    """Write one declared leaf while preserving all unrelated raw project data.

    Normalization can supply an omitted semantic default (e.g. object.scale).
    Materialize only that property's defaults if an explicit binding needs it.
    """
    cursor, defaults = raw, base
    for part in parts[:-1]:
        key = int(part) if isinstance(defaults, list) else part
        if isinstance(cursor, dict) and key not in cursor:
            cursor[key] = deepcopy(defaults[key])
        cursor, defaults = cursor[key], defaults[key]
    leaf = int(parts[-1]) if isinstance(cursor, list) else parts[-1]
    cursor[leaf] = deepcopy(value)


def apply_review(project_path, request_id, response_digest=None):
    path = _project_path(project_path)
    with _locked(path):
        data = _load(path, request_id)
        record, state, response, location = data
        _require(response is not None and response["decision"] == "confirm", "Only confirmed feedback can be applied", 409)
        _require(isinstance(response_digest, str) and response_digest == response["digest"],
                 "Apply requires the exact response digest read by the agent", 409)
        _check_reference_hashes(record["request"])
        current_revision = sha256(path)
        if state["status"] == "applied":
            return {"status": "already-applied", "request_id": request_id, "thread_id": record["request"]["thread_id"],
                    "revision": state["applied_revision"], "current_revision": current_revision,
                    "response_digest": response_digest}
        _require(state["status"] == "submitted", "Review is not awaiting application", 409)
        intent = state.get("apply_intent")
        if intent and current_revision == intent["revision"] and intent["response_digest"] == response_digest:
            # Recover a process exit after the atomic project replacement but
            # before lifecycle state was committed.
            state.update(status="applied", applied_at=_now(), applied_revision=current_revision,
                         message="Agent applied the confirmed adjustment")
            write_json(location / "state.json", state)
            return {"status": "already-applied", "request_id": request_id,
                    "thread_id": record["request"]["thread_id"], "revision": current_revision,
                    "response_digest": response_digest, "recovered": True}
        _require(current_revision == record["request"]["revision"], "Project changed since review creation; refusing to overwrite it", 409)
        candidate = _candidate(record, response["values"], path)
        _require(candidate["changes"] == response["changes"], "Feedback changes do not match the frozen scope", 409)
        output = read_json(path)
        for change in candidate["changes"]:
            parts, _ = _pointer(record["base"], change["path"])
            _patch_declared(output, record["base"], parts, change["after"])
        _require(_clean(_normalize(output, path)) == candidate["project"], "Scoped apply would alter unrelated project fields", 409)
        # A no-change confirmation must not rewrite/normalize the user's file.
        next_revision = _written_digest(output) if candidate["changes"] else current_revision
        state["apply_intent"] = {"revision": next_revision, "response_digest": response_digest}
        write_json(location / "state.json", state)
        _require(sha256(path) == current_revision, "Project changed while preparing the apply", 409)
        if candidate["changes"]:
            # Keep the exact original bytes, not a normalized approximation.
            raw = path.read_bytes()
            _require(hashlib.sha256(raw).hexdigest() == current_revision, "Project changed before archiving", 409)
            _archive_exact(path, raw, current_revision)
            _require(sha256(path) == current_revision, "Project changed before applying the response", 409)
            write_json(path, output)
        applied_revision = sha256(path)
        _require(applied_revision == next_revision, "Unexpected project revision after apply", 409)
        state.update(status="applied", applied_at=_now(), applied_revision=applied_revision,
                     message="Agent applied the confirmed adjustment")
        write_json(location / "state.json", state)
        return {"status": "applied", "request_id": request_id, "thread_id": record["request"]["thread_id"],
                "revision": applied_revision, "response_digest": response_digest, "changes": candidate["changes"]}


def close_review(project_path, request_id, message=""):
    path = _project_path(project_path)
    _text(message, "message", 4000, True)
    with _locked(path):
        data = _load(path, request_id)
        _, state, _, location = data
        if state["status"] != "closed":
            _require(state["status"] in ("pending", "submitted", "applied"), "Cannot close a superseded review", 409)
            state.update(status="closed", closed_at=_now(), message=message or "Agent closed this review")
            write_json(location / "state.json", state)
        return _public(data)


def wait_review(project_path, request_id=None, timeout=60):
    path = _project_path(project_path)
    _number(timeout, "timeout")
    _require(0 <= timeout <= 60, "timeout must be between 0 and 60 seconds")
    deadline, listener = time.monotonic() + timeout, uuid.uuid4().hex
    while True:
        with _locked(path):
            data = _load(path, request_id, current_required=False)
            if data is None:
                return {"status": "no-review", "agent_listening": False}
            record, state, response, location = data
            request_id = record["request"]["id"]
            if state["status"] != "pending":
                if state["status"] == "submitted" and response and not state.get("received_at"):
                    state.update(received_at=_now(), received_by_thread=record["request"]["thread_id"],
                                 message="Agent received the feedback; no project change has been applied yet")
                    state.pop("listener", None)
                    write_json(location / "state.json", state)
                result = _public(data)
                result.pop("baseline_project", None)
                result["timed_out"] = False
                return result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if state.get("listener", {}).get("id") == listener:
                    state.pop("listener", None)
                    write_json(location / "state.json", state)
                result = _public(data)
                result.pop("baseline_project", None)
                result["timed_out"] = True
                return result
            state["listener"] = {"id": listener, "thread_id": record["request"]["thread_id"],
                                 "expires_at": time.time() + min(3, remaining)}
            write_json(location / "state.json", state)
        time.sleep(min(.5, max(0, deadline - time.monotonic())))
