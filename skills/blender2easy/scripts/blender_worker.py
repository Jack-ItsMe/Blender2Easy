"""Standalone Blender build/render worker; invoke Blender with -- --job job.json."""
import argparse
import glob
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import traceback
import uuid

import bpy
from mathutils import Matrix, Vector


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".t-" + uuid.uuid4().hex[:12] + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def absolute(path):
    result = Path(path)
    if not result.is_absolute():
        raise ValueError("Worker output paths must be absolute: " + str(path))
    return result.resolve()


def inside(path, root):
    result = absolute(path)
    try:
        result.relative_to(root)
    except ValueError:
        raise ValueError("Output is outside project .animation: " + str(result))
    return result


def json_output(path, root):
    result = inside(path, root)
    if result.suffix.lower() != ".json":
        raise ValueError("Worker reports/progress must use .json paths")
    return result


def finite(value, name, minimum=None, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + " must be a finite number")
    if (minimum is not None and value < minimum) or (positive and value <= 0):
        raise ValueError(name + " is outside its allowed range")
    return float(value)


def vector(value, name, factor=1.0, positive=False):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(name + " must contain three numbers")
    return [finite(item, name, positive=positive) * factor for item in value]


def integer(value, name, minimum=1):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(name + " must be an integer >= " + str(minimum))
    return value


def linear(value):
    value = finite(value, "sRGB channel", minimum=0)
    if value > 1:
        raise ValueError("sRGB channels must be <= 1")
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def point_at(obj, target):
    direction = Vector(target) - obj.location
    if direction.length < 1e-9:
        raise ValueError(obj.name + " location and target coincide")
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def action_curves(obj):
    action = obj.animation_data.action
    if hasattr(action, "fcurves"):
        yield from action.fcurves
    else:
        # Blender 4.4+ layered actions, including Blender 5.x.
        for layer in action.layers:
            for strip in layer.strips:
                for bag in getattr(strip, "channelbags", []):
                    if bag.slot_handle == obj.animation_data.action_slot_handle:
                        yield from bag.fcurves


def procedural(project):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "Animation"
    factor = {"m": 1.0, "cm": 0.01, "mm": 0.001}[project["units"]]
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene["animation_declared_units"] = project["units"]
    config = project["scene"]
    scene.world = bpy.data.worlds.new("Studio World")
    scene.world.use_nodes = True
    background = config.get("background", [0.92, 0.94, 0.97])
    if len(background) != 3:
        raise ValueError("scene.background must have three sRGB channels")
    world_node = scene.world.node_tree.nodes.get("Background")
    world_node.inputs["Color"].default_value = [linear(c) for c in background] + [1]
    world_node.inputs["Strength"].default_value = finite(config.get("world_strength", 0.7), "world_strength", minimum=0)
    materials = {}
    for spec in config.get("materials", []):
        ident = spec["id"]
        if ident in materials:
            raise ValueError("Duplicate material id: " + ident)
        color = spec["color"]
        if len(color) != 4:
            raise ValueError("Material color must be RGBA: " + ident)
        rgba = [linear(c) for c in color[:3]] + [finite(color[3], "alpha", minimum=0)]
        if rgba[3] > 1:
            raise ValueError("Material alpha must be <= 1")
        material = bpy.data.materials.new(ident)
        material.use_nodes = True
        shader = material.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = rgba
        shader.inputs["Alpha"].default_value = rgba[3]
        material.diffuse_color = rgba
        for key, socket, default in [("roughness", "Roughness", 0.4), ("metallic", "Metallic", 0.0)]:
            value = finite(spec.get(key, default), key, minimum=0)
            if value > 1:
                raise ValueError(key + " must be <= 1")
            shader.inputs[socket].default_value = value
        if rgba[3] < 1:
            if hasattr(material, "surface_render_method"):
                material.surface_render_method = "DITHERED"
            elif hasattr(material, "blend_method"):
                material.blend_method = "HASHED"
        materials[ident] = material
    objects = {}

    def register(obj, ident):
        if ident in objects:
            raise ValueError("Duplicate scene id: " + ident)
        obj.name = ident
        objects[ident] = obj

    for spec in config.get("objects", []):
        kind = spec["type"]
        if kind == "empty":
            obj = bpy.data.objects.new(spec["id"], None)
            scene.collection.objects.link(obj)
            obj.empty_display_size = 0.12 * factor
        else:
            if kind == "cube":
                bpy.ops.mesh.primitive_cube_add(size=1)
            elif kind == "cylinder":
                bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.5, depth=1)
            elif kind == "sphere":
                bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=0.5)
            else:
                raise ValueError("Unsupported object type: " + str(kind))
            obj = bpy.context.object
            obj.dimensions = vector(spec.get("dimensions", [1, 1, 1]), "dimensions", factor, positive=True)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            if kind in {"sphere", "cylinder"}:
                for face in obj.data.polygons:
                    face.use_smooth = kind == "sphere" or len(face.vertices) == 4
            if spec.get("material") is not None:
                if spec["material"] not in materials:
                    raise ValueError("Missing material: " + spec["material"])
                obj.data.materials.append(materials[spec["material"]])
            bevel = finite(spec.get("bevel", 0), "bevel", minimum=0) * factor
            if bevel:
                modifier = obj.modifiers.new("Edge highlights", "BEVEL")
                modifier.width = bevel
                modifier.segments = 3
        register(obj, spec["id"])
        obj.location = vector(spec.get("location", [0, 0, 0]), "location", factor)
        obj.rotation_euler = vector(spec.get("rotation_deg", [0, 0, 0]), "rotation_deg", math.pi / 180)
        obj.scale = vector(spec.get("scale", [1, 1, 1]), "scale", positive=True)
    for spec in config.get("cameras", []):
        data = bpy.data.cameras.new(spec["id"])
        data.type = spec.get("type", "PERSP")
        if data.type not in {"ORTHO", "PERSP"}:
            raise ValueError("Only ORTHO/PERSP cameras are supported")
        data.ortho_scale = finite(spec.get("ortho_scale", 4.5), "ortho_scale", positive=True) * factor
        data.lens = finite(spec.get("lens", 50), "lens", positive=True)
        data.clip_start = 0.001
        data.clip_end = 10000
        obj = bpy.data.objects.new(spec["id"], data)
        scene.collection.objects.link(obj)
        register(obj, spec["id"])
        obj.location = vector(spec["location"], "camera.location", factor)
        point_at(obj, vector(spec["target"], "camera.target", factor))
    for spec in config.get("lights", []):
        kind = spec.get("type", "AREA")
        if kind not in {"AREA", "POINT", "SUN", "SPOT"}:
            raise ValueError("Unsupported light type: " + kind)
        data = bpy.data.lights.new(spec["id"], kind)
        data.energy = finite(spec.get("energy", 600), "light.energy", minimum=0)
        if kind == "AREA":
            data.shape = "DISK"
            data.size = finite(spec.get("size", 5), "light.size", positive=True) * factor
        obj = bpy.data.objects.new(spec["id"], data)
        scene.collection.objects.link(obj)
        register(obj, spec["id"])
        obj.location = vector(spec["location"], "light.location", factor)
        # Point lights emit in every direction and need no target orientation.
        if kind != "POINT":
            point_at(obj, vector(spec.get("target", [0, 0, 0]), "light.target", factor))
    # Assign local parenting after every id has been created. No world-preserve conversion.
    for spec in config.get("objects", []):
        parent = spec.get("parent")
        if parent is not None:
            if parent not in objects:
                raise ValueError("Missing parent: " + parent)
            current = objects[parent]
            while current:
                if current == objects[spec["id"]]:
                    raise ValueError("Parent cycle at " + spec["id"])
                current = current.parent
            objects[spec["id"]].parent = objects[parent]
            objects[spec["id"]].matrix_parent_inverse = Matrix.Identity(4)
    all_frames = []
    for track in config.get("animation", []):
        if track["target"] not in objects:
            raise ValueError("Missing animation target: " + track["target"])
        obj = objects[track["target"]]
        property_name = track["property"]
        if property_name not in {"location", "rotation_deg", "scale"}:
            raise ValueError("Unsupported animated property: " + property_name)
        data_path = "rotation_euler" if property_name == "rotation_deg" else property_name
        value_factor = math.pi / 180 if property_name == "rotation_deg" else factor if property_name == "location" else 1
        for key in track["keys"]:
            frame = integer(key["frame"], "key frame")
            mode = key.get("interpolation", "BEZIER")
            if mode not in {"BEZIER", "LINEAR", "CONSTANT"}:
                raise ValueError("Invalid key interpolation: " + mode)
            setattr(obj, data_path, vector(key["value"], "key value", value_factor, positive=property_name == "scale"))
            obj.keyframe_insert(data_path=data_path, frame=frame)
            for curve in action_curves(obj):
                if curve.data_path == data_path:
                    for point in curve.keyframe_points:
                        if abs(point.co.x - frame) < 1e-5:
                            point.interpolation = mode
                            if mode == "BEZIER":
                                point.handle_left_type = "AUTO_CLAMPED"
                                point.handle_right_type = "AUTO_CLAMPED"
            all_frames.append(frame)
    for shot in project.get("shots", []):
        all_frames.extend(shot["source_range"])
    scene.frame_start = min(all_frames, default=1)
    scene.frame_end = max(all_frames, default=1)
    scene.render.fps = integer(project["render"]["fps"], "fps")
    scene.render.fps_base = 1.0
    scene.frame_set(scene.frame_start)
    # Standard transforms make color swatches predictable for neutral studio demos.
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    return scene, []


def project_path(project, path):
    path = Path(path)
    return (Path(project["_root"]) / path).resolve() if not path.is_absolute() else path.resolve()


def source_dependencies(project):
    declared = {project_path(project, item["path"]) for item in project.get("assets", [])}
    for item in project["source"].get("dependencies", []):
        declared.add(project_path(project, item["path"] if isinstance(item, dict) else item))
    hashes = {str(Path(path).resolve()).casefold(): value for path, value in project.get("_asset_hashes", {}).items()}
    referenced = set()
    for raw in bpy.utils.blend_paths(absolute=True, packed=False, local=False):
        if not raw or raw == "<builtin>":
            continue
        # UDIM resources must name every tile in the declared dependency set.
        if "<UDIM>" in raw or "<UVTILE>" in raw:
            matches = glob.glob(raw.replace("<UDIM>", "[0-9][0-9][0-9][0-9]").replace("<UVTILE>", "u*_v*"))
            if not matches:
                raise ValueError("Missing external image tiles: " + raw)
            referenced.update(Path(item).resolve() for item in matches)
        else:
            referenced.add(Path(raw).resolve())
    sequences = [image.name for image in bpy.data.images if image.source == "SEQUENCE" and not image.packed_file]
    if sequences:
        raise ValueError("External image sequences are not supported in phase 1; bake/pack them first: " + ", ".join(sequences))
    missing = sorted(str(path) for path in referenced if path not in declared)
    if missing:
        raise ValueError("Undeclared native dependencies; add source.dependencies or assets: " + "; ".join(missing))
    for path in sorted(referenced):
        if not path.is_file():
            raise ValueError("Missing native dependency: " + str(path))
        expected = hashes.get(str(path).casefold())
        if not isinstance(expected, str) or expected != file_hash(path):
            raise ValueError("Native dependency hash missing or changed: " + str(path))
    return sorted(str(path) for path in referenced)


def check_shot_cameras(project, scene):
    camera_names = []
    for shot in project.get("shots", []):
        camera_names.append(shot["camera"])
        camera_names.extend(item["camera"] for item in shot.get("overlays", []))
    for name in camera_names:
        obj = scene.objects.get(name)
        if obj is None or obj.type != "CAMERA":
            raise ValueError("Camera missing from scene " + scene.name + ": " + name)
    if camera_names:
        scene.camera = scene.objects[camera_names[0]]


def native_animation_issue(owner, paths):
    animation = getattr(owner, "animation_data", None)
    if not animation:
        return None
    if any(curve.data_path in paths for curve in animation.drivers):
        return "drivers control the edited property"
    if any(not track.mute and any(not strip.mute for strip in track.strips)
           for track in animation.nla_tracks):
        return "active NLA strips require baking before editing"
    return None


def native_transform_issue(obj):
    """Expose the same conservative transform limits in the UI and the builder."""
    if obj.library and not obj.override_library:
        return "linked-library objects must be made local before editing"
    if any(not constraint.mute and constraint.influence != 0 for constraint in obj.constraints):
        return "active constraints require baking before editing"
    if obj.parent_type != "OBJECT" and obj.parent:
        return "bone/vertex parenting requires baking before editing"
    if any(abs(obj.matrix_parent_inverse[r][c] - (1 if r == c else 0)) > 1e-6
           for r in range(4) for c in range(4)):
        return "nonidentity parent inverse requires applying before editing"
    if (obj.delta_location.length > 1e-6 or obj.delta_rotation_euler.to_matrix() != Matrix.Identity(3)
            or any(abs(v - 1) > 1e-6 for v in obj.delta_scale)
            or abs(obj.delta_rotation_quaternion.angle) > 1e-6):
        return "delta transforms require applying before editing"
    return native_animation_issue(obj, {"location", "rotation_euler", "rotation_quaternion",
                                       "rotation_axis_angle", "scale"})


def remove_native_channels(owner, paths):
    """Copy shared actions and remove only explicitly overridden property curves."""
    issue = native_animation_issue(owner, paths)
    if issue:
        raise ValueError(owner.name + ": " + issue)
    animation = getattr(owner, "animation_data", None)
    if not animation or not animation.action:
        return
    # Even a unique action can be referenced by the imported datablock elsewhere.
    animation.action = animation.action.copy()
    action = animation.action
    if hasattr(action, "fcurves"):
        collections = [action.fcurves]
    else:
        collections = [bag.fcurves for layer in action.layers for strip in layer.strips
                       for bag in getattr(strip, "channelbags", [])
                       if bag.slot_handle == animation.action_slot_handle]
    for curves in collections:
        for curve in list(curves):
            if curve.data_path in paths:
                curves.remove(curve)


def native_principled(material):
    if not material.use_nodes or not material.node_tree:
        raise ValueError(material.name + ": enable a direct Principled BSDF material before editing")
    outputs = [node for node in material.node_tree.nodes
               if node.type == "OUTPUT_MATERIAL" and node.is_active_output]
    if len(outputs) != 1 or not outputs[0].inputs["Surface"].is_linked:
        raise ValueError(material.name + ": material needs one active surface output")
    node = outputs[0].inputs["Surface"].links[0].from_node
    if node.type != "BSDF_PRINCIPLED":
        raise ValueError(material.name + ": mixed/custom shaders cannot be edited as Principled material")
    return node


def apply_native_overrides(project, scene):
    overrides = project["source"].get("overrides", {})
    scene.frame_set(scene.frame_start)
    rotation_paths = {"rotation_euler", "rotation_quaternion", "rotation_axis_angle"}
    count = 0
    for spec in overrides.get("objects", []):
        obj = scene.objects.get(spec["id"])
        if obj is None:
            raise ValueError("Native override object missing: " + spec["id"])
        issue = native_transform_issue(obj)
        if issue:
            raise ValueError(obj.name + ": " + issue)
        paths = set(spec) & {"location", "scale"}
        if "rotation_deg" in spec:
            paths |= rotation_paths
        remove_native_channels(obj, paths)
        if "location" in spec:
            obj.location = spec["location"]
        if "scale" in spec:
            obj.scale = spec["scale"]
        if "rotation_deg" in spec:
            obj.rotation_mode = "XYZ"
            obj.rotation_euler = [math.radians(v) for v in spec["rotation_deg"]]
        count += 1
    for spec in overrides.get("materials", []):
        material = bpy.data.materials.get(spec["id"])
        if material is None or not any(material == slot.material for obj in scene.objects for slot in obj.material_slots):
            raise ValueError("Native override material missing from scene: " + spec["id"])
        if material.library and not material.override_library:
            raise ValueError(material.name + ": linked-library material must be made local")
        node = native_principled(material)
        for key, socket_name in (("color", "Base Color"), ("roughness", "Roughness"), ("metallic", "Metallic")):
            if key not in spec:
                continue
            socket = node.inputs[socket_name]
            if socket.is_linked:
                raise ValueError(material.name + ": " + socket_name + " is driven by a linked texture/node")
            remove_native_channels(material.node_tree, {socket.path_from_id("default_value")})
            socket.default_value = ([linear(v) for v in spec[key][:3]] + [spec[key][3]]) if key == "color" else spec[key]
            if key == "color":
                alpha_socket = node.inputs["Alpha"]
                if alpha_socket.is_linked:
                    raise ValueError(material.name + ": Alpha is driven by a linked texture/node")
                remove_native_channels(material.node_tree, {alpha_socket.path_from_id("default_value")})
                alpha_socket.default_value = spec[key][3]
                material.diffuse_color = socket.default_value
                if spec[key][3] < 1 and hasattr(material, "surface_render_method"):
                    material.surface_render_method = "DITHERED"
            else:
                setattr(material, key, spec[key])
        count += 1
    for spec in overrides.get("cameras", []):
        obj = scene.objects.get(spec["id"])
        if obj is None or obj.type != "CAMERA":
            raise ValueError("Native override camera missing: " + spec["id"])
        if "location" in spec or "target" in spec:
            issue = native_transform_issue(obj)
            if issue or obj.parent:
                raise ValueError(obj.name + ": " + (issue or "parented camera pose edits require unparenting/baking"))
            paths = {"location"} if "location" in spec else set()
            if "target" in spec:
                paths |= rotation_paths
            remove_native_channels(obj, paths)
            if "location" in spec:
                obj.location = spec["location"]
            if "target" in spec:
                obj.rotation_mode = "XYZ"
                point_at(obj, spec["target"])
        data_paths = set(spec) & {"lens", "ortho_scale"}
        if data_paths:
            if obj.data.library and not obj.data.override_library:
                raise ValueError(obj.name + ": linked camera data must be made local")
            # Isolate shared camera data: changing one camera must not edit another.
            obj.data = obj.data.copy()
            remove_native_channels(obj.data, data_paths)
            for key in data_paths:
                setattr(obj.data, key, spec[key])
        count += 1
    scene.frame_set(scene.frame_start)
    bpy.context.view_layer.update()
    return count


def build(job):
    project = job["project"]
    state = absolute(project["_state"])
    output = inside(job["output"], state)
    if output.suffix.lower() != ".blend":
        raise ValueError("Build output must use a .blend path")
    report_path = json_output(job["report"], state)
    warnings = []
    dependencies = []
    if project.get("source"):
        source = project_path(project, project["source"]["blend"])
        if source == output or source == report_path:
            raise ValueError("Source .blend must never be overwritten")
        if not source.is_file():
            raise ValueError("Missing source .blend: " + str(source))
        original_hash = file_hash(source)
        bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
        scene_name = project["source"].get("scene", "Scene")
        scene = bpy.data.scenes.get(scene_name)
        if scene is None:
            raise ValueError("Missing source scene: " + scene_name)
        dependencies = source_dependencies(project)
        try:
            bpy.ops.file.pack_all()
        except RuntimeError as error:
            warnings.append("Some native resources remain external: " + str(error))
        bpy.context.window.scene = scene
        apply_native_overrides(project, scene)
        if file_hash(source) != original_hash:
            raise RuntimeError("Source input changed during build")
    else:
        scene, warnings = procedural(project)
    check_shot_cameras(project, scene)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(".t-" + uuid.uuid4().hex[:12] + ".blend")
    try:
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(temporary), check_existing=False, relative_remap=True)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError("Blender did not write the built .blend")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    report = {"status": "PASS", "output": str(output), "blender_version": bpy.app.version_string,
              "scene": scene.name, "object_count": len(scene.objects), "warnings": warnings,
              "native_dependencies": dependencies}
    write_json(report_path, report)
    return report


def render_settings(scene, job):
    engine = job["engine"]
    if engine == "BLENDER_EEVEE_NEXT":
        engine = "BLENDER_EEVEE" if bpy.app.version >= (5, 0, 0) else engine
    elif engine == "BLENDER_EEVEE" and (4, 2, 0) <= bpy.app.version < (5, 0, 0):
        engine = "BLENDER_EEVEE_NEXT"
    if engine not in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "CYCLES"}:
        raise ValueError("Unsupported render engine: " + str(engine))
    scene.render.engine = engine
    samples = integer(job["samples"], "samples")
    if engine == "CYCLES":
        scene.cycles.samples = samples
    elif hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = samples
    else:
        raise RuntimeError("This Blender version does not expose EEVEE render samples")
    scene.render.fps = integer(job["fps"], "fps")
    scene.render.fps_base = 1.0
    scene.render.film_transparent = bool(job["transparent"])
    scene.render.use_compositing = False
    scene.render.use_sequencer = False
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.use_file_extension = True
    scene.render.use_border = False
    scene.render.use_crop_to_border = False
    scene.render.use_stamp = False
    # Never change view-layer enablement, exclusions, source lighting, or color management.


def render(job):
    blend = absolute(job["blend"])
    state = next((path for path in blend.parents if path.name == ".animation"), None)
    if state is None:
        raise ValueError("Render input must be a built .blend within project .animation")
    report_path = json_output(job["report"], state)
    progress_path = json_output(job["progress"], state)
    bpy.ops.wm.open_mainfile(filepath=str(blend), load_ui=False, use_scripts=False)
    name = job.get("scene")
    scene = bpy.data.scenes.get(name) if name else bpy.context.scene
    if scene is None:
        raise ValueError("Missing render scene: " + str(name))
    bpy.context.window.scene = scene
    render_settings(scene, job)
    prepared = []
    destinations = set()
    plate_ids = set()
    for plate in job["plates"]:
        if plate["id"] in plate_ids:
            raise ValueError("Duplicate render plate id: " + plate["id"])
        plate_ids.add(plate["id"])
        camera = scene.objects.get(plate["camera"])
        if camera is None or camera.type != "CAMERA":
            raise ValueError("Camera missing from scene " + scene.name + ": " + plate["camera"])
        if len(plate["size"]) != 2:
            raise ValueError("Render size needs width and height")
        size = [integer(value, "render size") for value in plate["size"]]
        for request in plate["requests"]:
            frame = integer(request["frame"], "render frame", minimum=0)
            path = inside(request["path"], state)
            if path.suffix.lower() != ".png":
                raise ValueError("Render requests must use .png paths")
            if path in destinations:
                raise ValueError("Duplicate render destination: " + str(path))
            destinations.add(path)
            prepared.append((plate["id"], camera, size, frame, path))
    rendered = 0
    total = len(prepared)
    progress = {"status": "RUNNING", "rendered": 0, "completed": 0, "total": total}
    write_json(progress_path, progress)
    for ident, camera, size, frame, path in prepared:
        scene.render.resolution_x, scene.render.resolution_y = size
        scene.frame_set(frame)
        # Native timeline camera markers can change scene.camera during frame_set.
        scene.camera = camera
        bpy.context.view_layer.update()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(".t-" + uuid.uuid4().hex[:12] + ".png")
        try:
            scene.render.filepath = str(temporary)
            bpy.ops.render.render(write_still=True, scene=scene.name)
            if not temporary.is_file() or temporary.stat().st_size < 32:
                raise RuntimeError("Blender did not produce PNG: " + str(temporary))
            with temporary.open("rb") as handle:
                if handle.read(8) != b"\x89PNG\r\n\x1a\n":
                    raise RuntimeError("Render is not PNG: " + str(temporary))
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        rendered += 1
        progress = {"status": "RUNNING", "rendered": rendered, "completed": rendered,
                    "total": total, "plate": ident, "source": frame}
        write_json(progress_path, progress)
    report = {"status": "PASS", "rendered": rendered, "completed": rendered, "total": total,
              "scene": scene.name, "blender_version": bpy.app.version_string}
    write_json(progress_path, report)
    write_json(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    job = json.loads(Path(args.job).read_text(encoding="utf-8-sig"))
    try:
        if job.get("operation") == "build":
            result = build(job)
        elif job.get("operation") == "render":
            result = render(job)
        else:
            raise ValueError("Unknown worker operation: " + str(job.get("operation")))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)
    except Exception as error:
        result = {"status": "ERROR", "error": str(error), "blender_version": bpy.app.version_string}
        # Only update paths after validating the job's output boundary.
        try:
            if job.get("operation") == "build":
                state = absolute(job["project"]["_state"])
            else:
                state = next(path for path in absolute(job["blend"]).parents if path.name == ".animation")
            for key in ("report", "progress"):
                if job.get(key):
                    write_json(json_output(job[key], state), result)
        except Exception:
            pass
        print(json.dumps(result, ensure_ascii=False), flush=True)
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
