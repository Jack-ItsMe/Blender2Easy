"""Read-only Blender worker for evaluated, bounded multi-frame scene snapshots.

SceneIR concepts and mesh inspection adapted from Blender Agent Studio, MIT,
Copyright (c) 2026 Bars. See ../vendor/bas/LICENSE for the retained license.
"""
import argparse
import hashlib
import math
from pathlib import Path
import struct
import sys

import bpy
import bmesh

sys.path.insert(0, str(Path(__file__).resolve().parent))
from animkit.diagnostics import SNAPSHOT_SCHEMA, file_hash, validate_snapshot, write_fresh


def operator_exists(operator):
    # bpy.ops dynamically creates wrappers, so hasattr() can report nonexistent operators.
    try:
        operator.get_rna_type()
        return True
    except (AttributeError, RuntimeError):
        return False


def load_asset(path):
    suffix = path.suffix.lower()
    if suffix == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False, use_scripts=False)
        return
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if suffix in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif suffix == ".fbx":
        if operator_exists(bpy.ops.wm.fbx_import):
            bpy.ops.wm.fbx_import(filepath=str(path))
        else:
            bpy.ops.import_scene.fbx(filepath=str(path))
    elif suffix == ".obj":
        if operator_exists(bpy.ops.wm.obj_import):
            bpy.ops.wm.obj_import(filepath=str(path))
        else:
            bpy.ops.import_scene.obj(filepath=str(path))
    else:
        raise ValueError(f"Unsupported asset type: {suffix}")


def components(mesh):
    parents = list(range(len(mesh.vertices)))
    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index
    for edge in mesh.edges:
        a, b = (root(index) for index in edge.vertices)
        if a != b:
            parents[b] = a
    return len({root(index) for index in range(len(parents))})


def material_summary(mesh):
    result = []
    for material in mesh.materials:
        if material is None:
            result.append(None)
        else:
            result.append({"id": material.name_full, "use_nodes": material.use_nodes,
                           "diffuse_rgba": list(material.diffuse_color),
                           "metallic": float(material.metallic), "roughness": float(material.roughness),
                           "node_types": sorted(node.bl_idname for node in material.node_tree.nodes)
                           if material.use_nodes and material.node_tree else []})
    return result


def snapshot_frame(frame):
    scene = bpy.context.scene
    scene.frame_set(frame)
    graph = bpy.context.evaluated_depsgraph_get()
    originals = sorted(scene.objects, key=lambda obj: obj.name_full)
    if len(originals) > 2048:
        raise ValueError("At most 2048 scene objects supported; isolate an assembly")
    ids = {obj.name_full for obj in originals}
    limitations = ["Hidden objects are included; viewport evaluation is used.",
                  "Only MESH geometry is summarized; other object types require visual review.",
                  "Material summaries do not fingerprint texture pixels or every shader parameter."]
    if any(instance.is_instance for instance in graph.object_instances):
        limitations.append("Dependency-graph instances are not expanded; realize instances for complete bounds and totals.")
    objects = []
    total_vertices = total_faces = 0
    for obj in originals:
        evaluated = obj.evaluated_get(graph)
        matrix = [[float(value) for value in row] for row in evaluated.matrix_world]
        parent = obj.parent.name_full if obj.parent else None
        if parent not in ids:
            if parent is not None:
                limitations.append(f"Parent outside active scene omitted for {obj.name_full}")
            parent = None
        entry = {"id": obj.name_full, "kind": obj.type, "parent": parent,
                 "world_matrix": matrix, "bounds": None, "mesh": None, "materials": [],
                 "hide_render": obj.hide_render, "hide_viewport": obj.hide_viewport}
        role_key = "animation_role" if "animation_role" in obj else "bas_role" if "bas_role" in obj else None
        entry["semantic_role"] = obj.get(role_key) if role_key else None
        entry["role_evidence"] = role_key
        if obj.type == "MESH":
            mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=graph)
            try:
                total_vertices += len(mesh.vertices)
                total_faces += len(mesh.polygons)
                if total_vertices > 2000000 or total_faces > 2000000 or len(mesh.edges) > 4000000 or len(mesh.loops) > 8000000:
                    raise ValueError("Evaluated frame exceeds 2 million vertices/faces; isolate an assembly")
                mins, maxs = [math.inf] * 3, [-math.inf] * 3
                geometry, topology, assignments = hashlib.sha256(), hashlib.sha256(), hashlib.sha256()
                topology.update(struct.pack("<QQQ", len(mesh.vertices), len(mesh.edges), len(mesh.polygons)))
                for vertex in mesh.vertices:
                    local = [float(value) for value in vertex.co]
                    world = evaluated.matrix_world @ vertex.co
                    if not all(math.isfinite(value) for value in local + list(world)):
                        raise ValueError(f"Non-finite geometry in {obj.name_full}")
                    geometry.update(struct.pack("<3d", *local))
                    for axis in range(3):
                        mins[axis] = min(mins[axis], float(world[axis]))
                        maxs[axis] = max(maxs[axis], float(world[axis]))
                for edge in mesh.edges:
                    topology.update(struct.pack("<2Q", *edge.vertices))
                for poly in mesh.polygons:
                    assignments.update(struct.pack("<Q", poly.material_index))
                    topology.update(struct.pack("<Q", len(poly.vertices)))
                    for index in poly.vertices:
                        topology.update(struct.pack("<Q", index))
                if mesh.vertices:
                    entry["bounds"] = {"min": mins, "max": maxs}
                mesh.calc_loop_triangles()
                bm = bmesh.new()
                try:
                    bm.from_mesh(mesh)
                    non_manifold = sum(not edge.is_manifold for edge in bm.edges)
                    boundary = sum(edge.is_boundary for edge in bm.edges)
                    zero_length = sum(edge.calc_length() <= 1e-12 for edge in bm.edges)
                finally:
                    bm.free()
                entry["mesh"] = {"vertices": len(mesh.vertices), "edges": len(mesh.edges),
                                 "faces": len(mesh.polygons), "triangles": len(mesh.loop_triangles),
                                 "connected_components": components(mesh), "non_manifold_edges": non_manifold,
                                 "boundary_edges": boundary, "degenerate_faces": sum(poly.area <= 1e-12 for poly in mesh.polygons),
                                 "zero_length_edges": zero_length,
                                 "missing_material_faces": sum(poly.material_index >= len(mesh.materials)
                                    or mesh.materials[poly.material_index] is None for poly in mesh.polygons),
                                 "geometry_sha256": geometry.hexdigest(), "topology_sha256": topology.hexdigest()}
                entry["materials"] = material_summary(mesh)
                entry["material_assignment_sha256"] = assignments.hexdigest()
            finally:
                evaluated.to_mesh_clear()
        objects.append(entry)
    return {"frame": frame, "meters_per_unit": scene.unit_settings.scale_length,
            "fps": scene.render.fps / scene.render.fps_base,
            "active_camera_id": scene.camera.name_full if scene.camera else None,
            "objects": objects, "limitations": limitations}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--frames")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    source, output = Path(args.input).resolve(), Path(args.output).resolve()
    if not source.is_file() or source == output or output.exists():
        raise ValueError("Require an existing source and a new distinct snapshot path")
    initial_hash = file_hash(source)
    load_asset(source)
    frames = [int(value) for value in args.frames.split(",")] if args.frames else [bpy.context.scene.frame_current]
    if not 1 <= len(frames) <= 32 or len(set(frames)) != len(frames) or any(abs(frame) > 1048574 for frame in frames):
        raise ValueError("Require 1..32 unique Blender integer frames")
    snapshot = {"schema_version": SNAPSHOT_SCHEMA, "source": {"path": str(source), "sha256": initial_hash},
                "provenance": {"blender_version": bpy.app.version_string,
                               "worker_sha256": file_hash(__file__), "source_unchanged": False},
                "frames": [snapshot_frame(frame) for frame in frames]}
    if file_hash(source) != initial_hash:
        raise ValueError("Source changed during diagnostics")
    snapshot["provenance"]["source_unchanged"] = True
    validate_snapshot(snapshot)
    write_fresh(output, snapshot)
    print(f"ANIMATION_DIAGNOSTIC_SNAPSHOT={output}")


if __name__ == "__main__":
    main()
