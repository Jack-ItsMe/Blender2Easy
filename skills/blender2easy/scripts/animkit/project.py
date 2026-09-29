"""Project validation and deterministic output-to-source frame planning."""
from copy import deepcopy
from math import floor, isfinite
from pathlib import Path
import re
from .common import read_json, sha256


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(value, allowed, label):
    require(isinstance(value, dict), f"{label}: expected object")
    require(not set(value) - set(allowed), f"{label}: unsupported fields {sorted(set(value)-set(allowed))}")


def number(value, label, low=None, high=None, integer=False):
    require(type(value) in (int, float) and isfinite(value), f"{label}: expected finite number")
    require(not integer or type(value) is int, f"{label}: expected integer")
    require(low is None or value >= low, f"{label}: must be >= {low}")
    require(high is None or value <= high, f"{label}: must be <= {high}")
    return value


def vector(value, label, size=3, low=None, high=None, integer=False):
    require(isinstance(value, list) and len(value) == size, f"{label}: expected {size} values")
    for x in value:
        number(x, label, low, high, integer)
    return value


def text(value, label):
    require(isinstance(value, str) and bool(value.strip()), f"{label}: expected nonempty string")
    return value


def identifier(value, label):
    text(value, label)
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value), f"{label}: use letters, digits, '-' or '_'")
    return value


def frame_range(value, label):
    vector(value, label, 2, 1, 1000000, True)
    require(value[0] <= value[1], f"{label}: range is reversed")
    return value


def native_overrides(value):
    """Validate only declarative, named native edits; no arbitrary Blender paths."""
    fields(value, {"objects", "materials", "cameras"}, "source.overrides")
    claimed_objects = set()
    definitions = {
        "objects": {"id", "location", "rotation_deg", "scale"},
        "materials": {"id", "color", "roughness", "metallic"},
        "cameras": {"id", "location", "target", "lens", "ortho_scale"},
    }
    for group, allowed in definitions.items():
        entries = value.setdefault(group, [])
        require(isinstance(entries, list), f"source.overrides.{group}: expected list")
        seen = set()
        for entry in entries:
            label = f"source.overrides.{group}"
            fields(entry, allowed, label)
            ident = text(entry.get("id"), label + ".id")
            require(len(ident) <= 1024 and "\0" not in ident, label + ".id: invalid Blender name")
            require(ident not in seen, label + ": duplicate id " + ident)
            seen.add(ident)
            require(len(entry) > 1, label + ": at least one edited property is required")
            if group in ("objects", "cameras"):
                require(ident not in claimed_objects, "Native object/camera override duplicated: " + ident)
                claimed_objects.add(ident)
            for key in ("location", "rotation_deg", "target", "scale"):
                if key in entry:
                    vector(entry[key], label + "." + key)
                    if key == "scale":
                        require(all(abs(v) >= 0.000001 for v in entry[key]), label + ".scale: zero scale is unsupported")
            if "color" in entry:
                vector(entry["color"], label + ".color", 4, 0, 1)
            for key in ("roughness", "metallic"):
                if key in entry:
                    number(entry[key], label + "." + key, 0, 1)
            if "lens" in entry:
                number(entry["lens"], label + ".lens", 1, 1000)
            if "ortho_scale" in entry:
                number(entry["ortho_scale"], label + ".ortho_scale", 0.000001)
            require(not {"location", "target"}.issubset(entry) or entry["location"] != entry["target"],
                    label + ": camera location equals target")
    return value


def normalize_project(raw, path):
    p = deepcopy(raw)
    path = Path(path).resolve()
    fields(p, {"schema_version", "id", "units", "assets", "scene", "source", "render", "shots"}, "project")
    require(type(p.get("schema_version")) is int and p["schema_version"] == 1, "schema_version must be 1")
    identifier(p.get("id"), "project.id")
    require(("scene" in p) != ("source" in p), "Provide exactly one of scene or source")
    p.setdefault("units", "m")
    require(p["units"] in ("m", "cm", "mm"), "units must be m, cm or mm")
    hashes = {}

    def asset_path(value, label):
        text(value, label)
        candidate = Path(value).expanduser()
        candidate = (candidate if candidate.is_absolute() else path.parent / candidate).resolve()
        require(candidate.is_file(), f"{label}: file missing: {candidate}")
        hashes[str(candidate)] = sha256(candidate)
        return str(candidate)

    p.setdefault("assets", [])
    require(isinstance(p["assets"], list), "assets must be a list")
    asset_ids = set()
    for a in p["assets"]:
        fields(a, {"id", "path", "sha256"}, "asset")
        identifier(a.get("id"), "asset.id")
        require(a["id"] not in asset_ids, "Duplicate asset id")
        asset_ids.add(a["id"])
        a["path"] = asset_path(a.get("path"), "asset.path")
        require(not a.get("sha256") or a["sha256"] == hashes[a["path"]], f"Asset hash mismatch: {a['id']}")
        a["sha256"] = hashes[a["path"]]
    cameras = set()
    if "source" in p:
        source = p["source"]
        fields(source, {"blend", "scene", "dependencies", "overrides"}, "source")
        source["blend"] = asset_path(source.get("blend"), "source.blend")
        require(Path(source["blend"]).suffix.lower() == ".blend", "source.blend must be a .blend file")
        text(source.setdefault("scene", "Scene"), "source.scene")
        require(isinstance(source.setdefault("dependencies", []), list), "source.dependencies must be a list")
        source["dependencies"] = [asset_path(x, "source.dependencies") for x in source["dependencies"]]
        if "overrides" in source:
            native_overrides(source["overrides"])
    else:
        scene = p["scene"]
        fields(scene, {"background", "world_strength", "materials", "objects", "cameras", "lights", "animation"}, "scene")
        vector(scene.setdefault("background", [0.95, 0.95, 0.95]), "scene.background", 3, 0, 1)
        number(scene.setdefault("world_strength", 0.7), "world_strength", 0, 100)
        for name in ("materials", "objects", "cameras", "lights", "animation"):
            require(isinstance(scene.setdefault(name, []), list), f"scene.{name} must be a list")
        material_ids = set()
        for mat in scene["materials"]:
            fields(mat, {"id", "color", "roughness", "metallic"}, "material")
            identifier(mat.get("id"), "material.id")
            require(mat["id"] not in material_ids, "Duplicate material id")
            material_ids.add(mat["id"])
            vector(mat.setdefault("color", [0.5, 0.5, 0.5, 1]), "material.color", 4, 0, 1)
            number(mat.setdefault("roughness", 0.4), "roughness", 0, 1)
            number(mat.setdefault("metallic", 0), "metallic", 0, 1)
        ids, parents = set(), {}

        def claim(obj, label):
            identifier(obj.get("id"), label + ".id")
            require(obj["id"] not in ids, f"Duplicate object/camera/light id: {obj['id']}")
            ids.add(obj["id"])

        for obj in scene["objects"]:
            fields(obj, {"id", "type", "dimensions", "location", "rotation_deg", "scale", "material", "parent", "bevel"}, "object")
            claim(obj, "object")
            require(obj.get("type") in ("cube", "cylinder", "sphere", "empty"), "Unsupported primitive type")
            vector(obj.setdefault("location", [0, 0, 0]), "location")
            vector(obj.setdefault("rotation_deg", [0, 0, 0]), "rotation_deg")
            vector(obj.setdefault("scale", [1, 1, 1]), "scale", low=0.000001)
            if obj["type"] != "empty":
                vector(obj.setdefault("dimensions", [1, 1, 1]), "dimensions", low=0.000001)
                number(obj.setdefault("bevel", 0), "bevel", 0)
                if obj.get("material"):
                    require(obj["material"] in material_ids, f"Unknown material: {obj['material']}")
            if obj.get("parent"):
                text(obj["parent"], "parent")
                parents[obj["id"]] = obj["parent"]
        object_ids = set(ids)
        for child, parent in parents.items():
            require(parent in object_ids, f"Unknown parent: {parent}")
            seen, current = {child}, parent
            while current:
                require(current not in seen, f"Parent cycle at {child}")
                seen.add(current)
                current = parents.get(current)
        for camera in scene["cameras"]:
            fields(camera, {"id", "location", "target", "type", "ortho_scale", "lens"}, "camera")
            claim(camera, "camera")
            cameras.add(camera["id"])
            vector(camera.get("location"), "camera.location")
            vector(camera.get("target"), "camera.target")
            require(camera["location"] != camera["target"], "Camera location equals target")
            require(camera.setdefault("type", "ORTHO") in ("ORTHO", "PERSP"), "Invalid camera type")
            number(camera.setdefault("ortho_scale", 5), "ortho_scale", 0.000001)
            number(camera.setdefault("lens", 50), "lens", 1, 1000)
        require(cameras, "At least one camera is required")
        for light in scene["lights"]:
            fields(light, {"id", "type", "location", "target", "energy", "size"}, "light")
            claim(light, "light")
            require(light.setdefault("type", "AREA") in ("AREA", "POINT", "SUN"), "Invalid light type")
            vector(light.get("location"), "light.location")
            vector(light.setdefault("target", [0, 0, 0]), "light.target")
            number(light.setdefault("energy", 500), "light.energy", 0)
            number(light.setdefault("size", 5), "light.size", 0.000001)
        channels = set()
        for track in scene["animation"]:
            fields(track, {"target", "property", "keys"}, "animation")
            require(track.get("target") in ids, f"Unknown animation target: {track.get('target')}")
            require(track.get("property") in ("location", "rotation_deg", "scale"), "Unsupported animation property")
            channel = (track["target"], track["property"])
            require(channel not in channels, f"Duplicate animation channel: {channel}")
            channels.add(channel)
            require(isinstance(track.get("keys"), list) and track["keys"], "Animation keys required")
            last = 0
            for key in track["keys"]:
                fields(key, {"frame", "value", "interpolation"}, "keyframe")
                number(key.get("frame"), "keyframe.frame", 1, 1000000, True)
                require(key["frame"] > last, "Keyframes must be unique and ascending")
                last = key["frame"]
                vector(key.get("value"), "keyframe.value", low=0.000001 if track["property"] == "scale" else None)
                require(key.setdefault("interpolation", "LINEAR") in ("LINEAR", "BEZIER", "CONSTANT"), "Invalid interpolation")
    render = p.setdefault("render", {})
    fields(render, {"fps", "resolution", "samples", "engine", "transparent"}, "render")
    number(render.setdefault("fps", 24), "fps", 1, 120, True)
    vector(render.setdefault("resolution", [640, 360]), "resolution", 2, 16, 8192, True)
    require(all(x % 2 == 0 for x in render["resolution"]), "H264 output width and height must be even")
    number(render.setdefault("samples", 16), "samples", 1, 4096, True)
    require(render.setdefault("engine", "BLENDER_EEVEE") in ("BLENDER_EEVEE", "CYCLES"), "Unsupported engine")
    require(type(render.setdefault("transparent", False)) is bool, "transparent must be boolean")
    require(isinstance(p.get("shots"), list) and p["shots"], "At least one shot required")
    shot_ids = set()
    for shot in p["shots"]:
        fields(shot, {"id", "title", "source_range", "camera", "timing", "overlays"}, "shot")
        identifier(shot.get("id"), "shot.id")
        require(shot["id"] not in shot_ids, "Duplicate shot id")
        shot_ids.add(shot["id"])
        text(shot.setdefault("title", shot["id"]), "shot.title")
        frame_range(shot.get("source_range"), "shot.source_range")
        text(shot.get("camera"), "shot.camera")
        require("source" in p or shot["camera"] in cameras, f"Unknown camera: {shot['camera']}")
        first, last = shot["source_range"]
        timing = shot.setdefault("timing", [{"source_range": [first, last], "frames": last-first+1, "anchors": []}])
        require(isinstance(timing, list) and timing, "timing must be a nonempty list")
        previous = first-1
        for phase in timing:
            fields(phase, {"source_range", "frames", "anchors"}, "timing phase")
            start, end = frame_range(phase.get("source_range"), "phase.source_range")
            require(start == previous+1 and end <= last, "Timing phases must cover the shot consecutively, without gaps")
            previous = end
            number(phase.get("frames"), "phase.frames", 1, 1000000, True)
            anchors = phase.setdefault("anchors", [])
            require(isinstance(anchors, list), "anchors must be a list")
            for anchor in anchors:
                number(anchor, "anchor", start, end, True)
            require(phase["frames"] >= len(set([start, end] + anchors)), "Output duration cannot retain all event anchors")
        require(previous == last, "Timing phases must cover the complete shot range")
        require(sum(phase["frames"] for phase in timing) <= 1000000, "Shot output exceeds 1,000,000 frames")
        overlays = shot.setdefault("overlays", [])
        require(isinstance(overlays, list), "overlays must be a list")
        plate_ids = {"main"}
        width, height = render["resolution"]
        for overlay in overlays:
            fields(overlay, {"id", "camera", "size", "rect", "source_range", "alpha", "fade_frames", "border", "radius", "border_rgb"}, "overlay")
            identifier(overlay.get("id"), "overlay.id")
            require(overlay["id"] not in plate_ids, "Duplicate/reserved overlay id")
            plate_ids.add(overlay["id"])
            text(overlay.get("camera"), "overlay.camera")
            require("source" in p or overlay["camera"] in cameras, f"Unknown overlay camera: {overlay['camera']}")
            x, y, w, h = vector(overlay.get("rect"), "overlay.rect", 4, 0, 8192, True)
            require(w >= 1 and h >= 1 and x+w <= width and y+h <= height, "Overlay must fit output canvas")
            vector(overlay.setdefault("size", [w, h]), "overlay.size", 2, 1, 8192, True)
            begin, finish = frame_range(overlay.setdefault("source_range", [first, last]), "overlay.source_range")
            require(first <= begin <= finish <= last, "Overlay source range must be within shot")
            number(overlay.setdefault("alpha", 1), "overlay.alpha", 0, 1)
            number(overlay.setdefault("fade_frames", 0), "overlay.fade_frames", 0, 1000000, True)
            number(overlay.setdefault("border", 0), "overlay.border", 0, min(w, h)//2, True)
            number(overlay.setdefault("radius", 0), "overlay.radius", 0, min(w, h)//2, True)
            vector(overlay.setdefault("border_rgb", [215, 220, 225]), "border_rgb", 3, 0, 255, True)
    p.update(_path=str(path), _root=str(path.parent), _state=str(path.parent / ".animation"), _asset_hashes=hashes)
    return p


def load_project(path):
    return normalize_project(read_json(path), path)


def sample_phase(first, last, count, anchors):
    """Monotonic integer lookup, retaining event anchors and both endpoints."""
    required = sorted(set([first, last] + list(anchors)))
    if count >= last-first+1:
        if count == 1:
            return [first]
        return [first + floor((last-first)*i/(count-1) + 0.5) for i in range(count)]
    require(count >= len(required), "Too few output frames for required anchors")
    capacities = [b-a-1 for a, b in zip(required, required[1:])]
    remaining, total = count-len(required), sum(capacities)
    allocated = [0] * len(capacities)
    if remaining:
        exact = [remaining*c/total for c in capacities]
        allocated = [floor(x) for x in exact]
        order = sorted(range(len(capacities)), key=lambda i: (exact[i]-allocated[i], capacities[i]), reverse=True)
        for i in order[:remaining-sum(allocated)]:
            allocated[i] += 1
    result = set(required)
    for (a, b), count_here in zip(zip(required, required[1:]), allocated):
        result.update(a + floor((b-a)*j/(count_here+1) + .5) for j in range(1, count_here+1))
    require(len(result) == count, "Internal frame sampling error")
    return sorted(result)


def compile_plans(project, build):
    plans = []
    render = project["render"]
    for shot in project["shots"]:
        mapping = []
        for phase in shot["timing"]:
            mapping.extend(sample_phase(*phase["source_range"], phase["frames"], phase["anchors"]))
        plates = {"main": {"camera": shot["camera"], "size": render["resolution"]}}
        rows = [{"frame": i, "original_output_frame": source,
                 "main": [{"plate": "main", "source": source, "weight": 1}], "overlays": []}
                for i, source in enumerate(mapping, 1)]
        for overlay in shot["overlays"]:
            plates[overlay["id"]] = {"camera": overlay["camera"], "size": overlay["size"]}
            visible = [row for row in rows if overlay["source_range"][0] <= row["original_output_frame"] <= overlay["source_range"][1]]
            fade = min(overlay["fade_frames"], (len(visible)+1)//2)
            for j, row in enumerate(visible):
                alpha = overlay["alpha"]
                if fade:
                    t = min(1, (j+1)/fade, (len(visible)-j)/fade)
                    alpha *= t*t*(3-2*t)
                row["overlays"].append({"plate": overlay["id"], "source": row["original_output_frame"],
                    "rect": overlay["rect"], "alpha": alpha, "border": overlay["border"],
                    "radius": overlay["radius"], "border_rgb": overlay["border_rgb"]})
        plans.append({"schema_version": 1, "id": shot["id"], "title": shot["title"], **render,
            "scene": project.get("source", {}).get("scene", "Animation"),
            "background": project.get("scene", {}).get("background", [1, 1, 1]),
            "blend": build["blend"], "build_key": build["key"], "blender_version": build["blender_version"],
            "plates": plates, "frames": rows, "source_range": shot["source_range"]})
    return plans
