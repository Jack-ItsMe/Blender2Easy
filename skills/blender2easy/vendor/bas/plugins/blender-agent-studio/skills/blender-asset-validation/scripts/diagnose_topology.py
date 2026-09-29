"""Localize definite evaluated-mesh degeneracies without changing the asset.

Run through Blender:
blender --background --factory-startup --python diagnose_topology.py -- \
  --input asset.glb --output topology.json [--object ExactName] [--limit 20]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspect_asset import load_asset, script_args


DEGENERATE_FACE_AREA = 1e-12
ZERO_LENGTH_EDGE = 1e-9
MAX_SCENE_OBJECTS = 2_048
MAX_EVALUATED_GEOMETRY = 2_000_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--frame", type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--object", dest="object_name")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(script_args())
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be from 1 through 100")
    return args


def finite(values: Any) -> bool:
    return all(math.isfinite(float(value)) for value in values)


def rounded(values: Any, places: int = 9) -> list[float]:
    return [round(float(value), places) for value in values]


def finding(
    object_name: str,
    element_index: int,
    kind: str,
    world_center: Any,
    measurement: str,
    value: float,
) -> dict[str, Any]:
    return {
        "objectName": object_name,
        "evaluatedElementIndex": int(element_index),
        "kind": kind,
        "worldCenter": rounded(world_center),
        measurement: float(value),
    }


def inspect_mesh(
    obj: bpy.types.Object,
    depsgraph: bpy.types.Depsgraph,
    findings: list[dict[str, Any]],
    limit: int,
) -> dict[str, int]:
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    try:
        if len(mesh.vertices) > MAX_EVALUATED_GEOMETRY or len(mesh.edges) > MAX_EVALUATED_GEOMETRY or len(mesh.polygons) > MAX_EVALUATED_GEOMETRY:
            raise ValueError("Topology diagnostic geometry limit exceeded; isolate an assembly first")
        world_vertices = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
        if any(not finite(vertex) for vertex in world_vertices):
            raise ValueError(f"Non-finite world vertex: {obj.name_full}")

        mesh.calc_loop_triangles()
        polygon_areas = [0.0] * len(mesh.polygons)
        for triangle in mesh.loop_triangles:
            first, second, third = (world_vertices[index] for index in triangle.vertices)
            polygon_areas[triangle.polygon_index] += (second - first).cross(third - first).length / 2.0

        counts = {"vertices": len(mesh.vertices), "edges": len(mesh.edges), "polygons": len(mesh.polygons), "degenerate_faces": 0, "zero_length_edges": 0}
        for polygon in mesh.polygons:
            area = polygon_areas[polygon.index]
            if area <= DEGENERATE_FACE_AREA:
                counts["degenerate_faces"] += 1
                if len(findings) < limit:
                    center = sum((world_vertices[index] for index in polygon.vertices), start=world_vertices[polygon.vertices[0]].copy() * 0.0) / len(polygon.vertices) if polygon.vertices else evaluated.matrix_world.translation
                    findings.append(finding(obj.name_full, polygon.index, "degenerate_face", center, "area", area))
        for edge in mesh.edges:
            first, second = (world_vertices[index] for index in edge.vertices)
            length = (second - first).length
            if length <= ZERO_LENGTH_EDGE:
                counts["zero_length_edges"] += 1
                if len(findings) < limit:
                    findings.append(finding(obj.name_full, edge.index, "zero_length_edge", (first + second) / 2.0, "length", length))
        return counts
    finally:
        evaluated.to_mesh_clear()


def main() -> None:
    args = parse_args()
    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source == output or output.exists():
        raise ValueError("Topology diagnostic output must be a new file distinct from the asset")

    load_asset(source)
    if args.frame is not None:
        if not -1048574 <= args.frame <= 1048574:
            raise ValueError("frame must be within Blender limits")
        bpy.context.scene.frame_set(args.frame)
    scene_objects = sorted(bpy.context.scene.objects, key=lambda obj: obj.name_full)
    if len(scene_objects) > MAX_SCENE_OBJECTS:
        raise ValueError("Topology diagnostic supports at most 2048 scene objects; isolate an assembly first")
    if args.object_name is not None:
        selected = [obj for obj in scene_objects if obj.name_full == args.object_name]
        if not selected:
            raise ValueError(f"Exact object not found: {args.object_name}")
    else:
        selected = scene_objects

    depsgraph = bpy.context.evaluated_depsgraph_get()
    findings: list[dict[str, Any]] = []
    counts = {"mesh_objects": 0, "evaluated_vertices": 0, "evaluated_edges": 0, "evaluated_polygons": 0, "degenerate_faces": 0, "zero_length_edges": 0}
    for obj in selected:
        # Match inspect_asset.py: glTF importer editor helpers are not delivered geometry.
        if obj.type != "MESH" or any(collection.name == "glTF_not_exported" for collection in obj.users_collection):
            continue
        mesh_counts = inspect_mesh(obj, depsgraph, findings, args.limit)
        counts["mesh_objects"] += 1
        counts["evaluated_vertices"] += mesh_counts["vertices"]
        counts["evaluated_edges"] += mesh_counts["edges"]
        counts["evaluated_polygons"] += mesh_counts["polygons"]
        counts["degenerate_faces"] += mesh_counts["degenerate_faces"]
        counts["zero_length_edges"] += mesh_counts["zero_length_edges"]
        if any(counts[key] > MAX_EVALUATED_GEOMETRY for key in ("evaluated_vertices", "evaluated_edges", "evaluated_polygons")):
            raise ValueError("Topology diagnostic geometry limit exceeded; isolate an assembly first")

    total_findings = counts["degenerate_faces"] + counts["zero_length_edges"]
    report = {
        "schema_version": "bas-topology-diagnostics/0.1",
        "input": str(source),
        "scope": {"objectName": args.object_name, "frame": int(bpy.context.scene.frame_current)},
        "counts": counts,
        "findings": findings,
        "total_findings": total_findings,
        "truncated": total_findings > len(findings),
        "thresholds": {"degenerate_face_area": DEGENERATE_FACE_AREA, "zero_length_edge": ZERO_LENGTH_EDGE},
        "limitations": [
            "Findings use evaluated mesh element indexes; they are not editable source-mesh indexes.",
            "Only world-space faces and edges at or below the reported area/length thresholds are reported. This tool performs no repair or deletion.",
            "Open boundaries and non-manifold edges are excluded because they are not automatically defects.",
            "Active scene and current frame use the evaluated viewport dependency graph, not render-only modifier settings.",
        ],
        "blender": {"version": bpy.app.version_string, "background": bool(bpy.app.background)},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, allow_nan=False, indent=2, sort_keys=True)
    print(f"BAS_TOPOLOGY_DIAGNOSTICS={output}")


if __name__ == "__main__":
    main()
