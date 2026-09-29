"""Read-only native discovery and glTF preview export, executed inside Blender."""
import argparse
import glob
import json
import math
import os
from pathlib import Path
import struct
import sys
import traceback
import uuid

import bpy
from mathutils import Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_worker import (absolute, file_hash, inside, native_animation_issue,
                            native_principled, native_transform_issue, write_json)

ORIGINAL_ID = "object_animation_id"


def srgb(value):
    return max(0.0, min(1.0, 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055))


def dependencies():
    result = set()
    for raw in bpy.utils.blend_paths(absolute=True, packed=False, local=False):
        if not raw or raw == "<builtin>":
            continue
        if "<UDIM>" in raw or "<UVTILE>" in raw:
            paths = glob.glob(raw.replace("<UDIM>", "[0-9][0-9][0-9][0-9]").replace("<UVTILE>", "u*_v*"))
            if not paths:
                raise ValueError("Missing external image tiles: " + raw)
        else:
            paths = [raw]
        for value in paths:
            path = Path(value).resolve()
            if not path.is_file():
                raise ValueError("Missing native dependency: " + str(path))
            result.add(str(path))
    sequences = [image.name for image in bpy.data.images if image.source == "SEQUENCE" and not image.packed_file]
    if sequences:
        raise ValueError("External image sequences must be packed/baked before import: " + ", ".join(sequences))
    return sorted(result)


def material_manifest(material):
    result = {"id": material.name, "color": [srgb(v) for v in material.diffuse_color[:3]] + [material.diffuse_color[3]],
              "roughness": material.roughness, "metallic": material.metallic,
              "editable_properties": [], "warnings": []}
    try:
        node = native_principled(material)
        rgba = node.inputs["Base Color"].default_value
        result["color"] = [srgb(v) for v in rgba[:3]] + [float(node.inputs["Alpha"].default_value)]
        for key, socket_name in (("color", "Base Color"), ("roughness", "Roughness"), ("metallic", "Metallic")):
            socket = node.inputs[socket_name]
            if key != "color":
                result[key] = float(socket.default_value)
            issue = native_animation_issue(material.node_tree, {socket.path_from_id("default_value")})
            if socket.is_linked or issue or material.library:
                result["warnings"].append(key + ": " + (issue or "linked texture/node/library property is read-only"))
            elif key == "color" and (node.inputs["Alpha"].is_linked or native_animation_issue(material.node_tree, {node.inputs["Alpha"].path_from_id("default_value")})):
                result["warnings"].append("color: linked/driven alpha is read-only")
            else:
                result["editable_properties"].append(key)
    except ValueError as error:
        result["warnings"].append(str(error))
    return result


def manifest(scene, dependency_paths):
    scene.frame_set(scene.frame_start)
    bpy.context.view_layer.update()
    result = {"scene": scene.name, "objects": [], "materials": [], "cameras": [], "lights": [],
              "frame_start": scene.frame_start, "frame_end": scene.frame_end,
              "fps": scene.render.fps / scene.render.fps_base,
              "units_scale": 1, "dependencies": dependency_paths,
              "warnings": ["Three.js previews approximate Blender shaders, lighting and physics; Blender render is authoritative."]}
    materials = {}
    for obj in scene.objects:
        issue = native_transform_issue(obj)
        if obj.rotation_mode == "QUATERNION":
            rotation = obj.rotation_quaternion.to_euler("XYZ")
        elif obj.rotation_mode == "AXIS_ANGLE":
            angle, x, y, z = obj.rotation_axis_angle
            rotation = Quaternion(Vector((x, y, z)), angle).to_euler("XYZ")
        else:
            rotation = obj.rotation_euler.to_quaternion().to_euler("XYZ")
        record = {"id": obj.name, "type": obj.type, "parent": obj.parent.name if obj.parent else None,
                  "location": list(obj.location), "rotation_deg": [math.degrees(v) for v in rotation],
                  "scale": list(obj.scale), "dimensions": list(obj.dimensions),
                  "editable_transform": issue is None, "transform_warning": issue,
                  "hidden": bool(obj.hide_render), "gltf_node": obj.name}
        slots = [slot.material.name for slot in obj.material_slots if slot.material]
        if slots:
            record["material"] = slots[0]
            record["materials"] = slots
        for slot in obj.material_slots:
            if slot.material:
                materials[slot.material.name] = slot.material
        result["objects"].append(record)
        if obj.type == "CAMERA":
            position = obj.matrix_world.translation
            target = position + obj.matrix_world.to_quaternion() @ Vector((0, 0, -max(1.0, obj.data.dof.focus_distance)))
            result["cameras"].append({"id": obj.name, "gltf_node": obj.name,
                                      "location": list(position), "target": list(target),
                                      "type": obj.data.type, "lens": obj.data.lens,
                                      "ortho_scale": obj.data.ortho_scale,
                                      "sensor_width": obj.data.sensor_width,
                                      "sensor_height": obj.data.sensor_height,
                                      "sensor_fit": obj.data.sensor_fit,
                                      "editable_transform": not issue and not obj.parent,
                                      "transform_warning": issue or ("Parented camera pose edits require unparenting/baking" if obj.parent else None)})
        elif obj.type == "LIGHT":
            result["lights"].append({"id": obj.name, "gltf_node": obj.name, "type": obj.data.type,
                                     "location": list(obj.matrix_world.translation),
                                     "energy": obj.data.energy, "color": list(obj.data.color)})
        if obj.modifiers and any(m.type in {"CLOTH", "FLUID", "SOFT_BODY", "PARTICLE_SYSTEM"} for m in obj.modifiers):
            result["warnings"].append(obj.name + ": physics/deforming simulation requires baked geometry for exact preview")
    result["materials"] = [material_manifest(mat) for mat in materials.values()]
    return result


def inspect_glb(path, result):
    """Record actual exported node names and validate animation's time origin."""
    with Path(path).open("rb") as stream:
        magic, version, length = struct.unpack("<4sII", stream.read(12))
        if magic != b"glTF" or version != 2 or length != Path(path).stat().st_size:
            raise RuntimeError("Blender output is not a complete glTF 2 binary")
        size, kind = struct.unpack("<II", stream.read(8))
        if kind != 0x4E4F534A:
            raise RuntimeError("glTF JSON chunk is missing")
        gltf = json.loads(stream.read(size).decode("utf-8"))
    by_id = {node.get("extras", {}).get(ORIGINAL_ID): (i, node.get("name", ""))
             for i, node in enumerate(gltf.get("nodes", [])) if node.get("extras", {}).get(ORIGINAL_ID)}
    # Linked-library objects may not permit custom properties, but their original
    # unique name still gives an exact exported-node mapping.
    by_name = {}
    for index, node in enumerate(gltf.get("nodes", [])):
        by_name.setdefault(node.get("name", ""), []).append(index)
    for group in ("objects", "cameras", "lights"):
        for item in result[group]:
            named = by_name.get(item["id"], [])
            fallback = (named[0], item["id"]) if len(named) == 1 else (None, item["id"])
            index, name = by_id.get(item["id"], fallback)
            item.update(gltf_node=name, gltf_node_index=index, preview_visible=index is not None)
    for animation in gltf.get("animations", []):
        for sampler in animation.get("samplers", []):
            minimum = gltf["accessors"][sampler["input"]].get("min", [0])[0]
            if abs(minimum) > 1e-5:
                raise RuntimeError("glTF animation does not begin at zero: " + str(minimum))
    result["animation_clips"] = [item.get("name", "") for item in gltf.get("animations", [])]
    result["gltf_extras_id"] = ORIGINAL_ID


def run(job):
    source = absolute(job["blend"])
    state = absolute(job["state"])
    report = inside(job["report"], state)
    if report.suffix.lower() != ".json" or source == report:
        raise ValueError("Invalid preview report path")
    original_hash = file_hash(source)
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
    scene = bpy.data.scenes.get(job["scene"]) if job.get("scene") else bpy.context.scene
    if scene is None:
        raise ValueError("Native scene not found: " + str(job.get("scene")))
    bpy.context.window.scene = scene
    dependency_paths = dependencies()
    result = manifest(scene, dependency_paths)
    result["scenes"] = [item.name for item in bpy.data.scenes]
    if job["operation"] == "export":
        output = inside(job["output"], state)
        if output.suffix.lower() != ".glb" or output == source:
            raise ValueError("Preview output must be a new .glb inside project state")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(".t-" + uuid.uuid4().hex[:12] + ".glb")
        for obj in scene.objects:
            # This is in-memory metadata only; source and built .blend are never saved here.
            try:
                obj[ORIGINAL_ID] = obj.name
            except (TypeError, RuntimeError):
                result["warnings"].append(obj.name + ": linked object uses name mapping and is read-only")
        try:
            bpy.ops.export_scene.gltf(filepath=str(temporary), check_existing=False,
                export_format="GLB", export_yup=False, export_extras=True,
                use_active_scene=True, use_renderable=True, export_apply=True,
                export_cameras=True, export_lights=True, export_animations=True,
                export_animation_mode="SCENE", export_anim_scene_split_object=False,
                export_frame_range=True, export_frame_step=1, export_force_sampling=True,
                export_anim_slide_to_zero=True, export_current_frame=False,
                export_bake_animation=True, export_optimize_animation_size=True)
            inspect_glb(temporary, result)
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    elif job["operation"] != "discover":
        raise ValueError("Unknown preview operation")
    if file_hash(source) != original_hash:
        raise RuntimeError("Source .blend changed during read-only preview operation")
    response = {"status": "PASS", "manifest": result, "source_sha256": original_hash,
                "blender_version": bpy.app.version_string}
    write_json(report, response)
    return response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    job = json.loads(Path(args.job).read_text(encoding="utf-8-sig"))
    try:
        result = run(job)
        print(json.dumps({"status": result["status"], "scene": result["manifest"]["scene"]}, ensure_ascii=False))
    except Exception as error:
        try:
            write_json(inside(job["report"], absolute(job["state"])), {"status": "ERROR", "error": str(error)})
        except Exception:
            pass
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
