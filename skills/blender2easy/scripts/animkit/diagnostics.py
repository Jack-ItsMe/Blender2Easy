"""Deterministic, bounded scene diagnostics. No Blender imports or inferred intent.

Scene summary and declared-anchor design informed by Blender Agent Studio (MIT,
Copyright (c) 2026 Bars); the retained license is in vendor/bas/LICENSE.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

SNAPSHOT_SCHEMA = "object-animation.scene-snapshot/1"
CONTRACT_SCHEMA = "object-animation.diagnostic-contract/1"
REPORT_SCHEMA = "object-animation.diagnostic-report/1"
PROPERTIES = {"geometry", "topology", "hierarchy", "transform", "materials", "semantic_role"}
LIMITATIONS = [
    "Only the declared sampled frames are checked; motion between samples is unverified.",
    "Bounds are world-space axis-aligned boxes, not exact surfaces or collision tests.",
    "Passing declared anchors or axes does not prove a mechanical joint or correct motion.",
    "Mesh summaries use the evaluated viewport dependency graph, not render-only settings.",
    "Primary asset hashes do not fingerprint external textures, caches or linked dependencies.",
]


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def finite_tree(value, path="value"):
    if isinstance(value, float):
        _require(math.isfinite(value), f"Non-finite number at {path}")
    elif isinstance(value, dict):
        for key, child in value.items():
            finite_tree(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            finite_tree(child, f"{path}[{index}]")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def read_json(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    finite_tree(value)
    return value


def write_fresh(path, value):
    data = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(data)
    return target


def _number(value, label, minimum=0):
    _require(isinstance(value, (float, int)) and not isinstance(value, bool)
             and math.isfinite(value) and value >= minimum, f"Invalid {label}")
    return value


def _vector(value, label, size=3):
    _require(isinstance(value, list) and len(value) == size, f"{label} requires {size} values")
    for child in value:
        _number(child, label, -math.inf)
    return value


def _identifier(value, label):
    _require(isinstance(value, str) and 0 < len(value) <= 1024, f"Invalid {label}")


def _sha256(value, label):
    _require(isinstance(value, str) and len(value) == 64
             and all(c in "0123456789abcdef" for c in value), f"Invalid {label}")


def _keys(value, allowed, required, label):
    _require(isinstance(value, dict), f"{label} must be an object")
    _require(set(value) <= set(allowed), f"Unknown {label} fields: {sorted(set(value) - set(allowed))}")
    _require(set(required) <= set(value), f"Missing {label} fields: {sorted(set(required) - set(value))}")


def validate_snapshot(snapshot):
    finite_tree(snapshot)
    _require(isinstance(snapshot, dict) and snapshot.get("schema_version") == SNAPSHOT_SCHEMA,
             f"Expected {SNAPSHOT_SCHEMA}")
    source = snapshot.get("source", {})
    _require(isinstance(source, dict) and isinstance(source.get("path"), str), "Snapshot source path is missing")
    _sha256(source.get("sha256"), "source sha256")
    frames = snapshot.get("frames")
    _require(isinstance(frames, list) and 1 <= len(frames) <= 32, "Snapshot requires 1..32 sampled frames")
    frame_ids = set()
    for sample in frames:
        _require(isinstance(sample, dict), "Frame sample must be an object")
        frame = sample.get("frame")
        _require(type(frame) is int and -1048574 <= frame <= 1048574 and frame not in frame_ids,
                 "Sample frame must be a unique Blender integer frame")
        frame_ids.add(frame)
        _require(_number(sample.get("meters_per_unit"), "meters_per_unit") > 0, "meters_per_unit must be positive")
        limitations = sample.get("limitations", [])
        _require(isinstance(limitations, list) and all(isinstance(item, str) for item in limitations),
                 "Frame limitations must be an array of strings")
        objects = sample.get("objects")
        _require(isinstance(objects, list) and len(objects) <= 2048, "Frame requires at most 2048 objects")
        ids = set()
        for obj in objects:
            _require(isinstance(obj, dict), "Object summary must be an object")
            _identifier(obj.get("id"), "object id")
            _require(obj["id"] not in ids, f"Duplicate object ID {obj['id']}")
            ids.add(obj["id"])
            _identifier(obj.get("kind"), "object kind")
            role = obj.get("semantic_role")
            _require(role is None or isinstance(role, str) and len(role) <= 256, "Invalid semantic_role")
            parent = obj.get("parent")
            _require(parent is None or isinstance(parent, str), "parent must be an exact ID or null")
            matrix = obj.get("world_matrix")
            _require(isinstance(matrix, list) and len(matrix) == 4, "world_matrix requires 4 rows")
            for row in matrix:
                _vector(row, "world_matrix row", 4)
            _require(all(abs(matrix[3][i] - ([0, 0, 0, 1][i])) <= 1e-9 for i in range(4)),
                     "world_matrix must be affine")
            bounds = obj.get("bounds")
            if bounds is not None:
                _keys(bounds, {"min", "max"}, {"min", "max"}, "bounds")
                _vector(bounds["min"], "bounds.min")
                _vector(bounds["max"], "bounds.max")
                _require(all(a <= b for a, b in zip(bounds["min"], bounds["max"])), "Inverted bounds")
            mesh = obj.get("mesh")
            if mesh is not None:
                _require(isinstance(mesh, dict), "mesh must be an object or null")
                for key in ("vertices", "edges", "faces", "triangles", "connected_components",
                            "non_manifold_edges", "boundary_edges", "degenerate_faces",
                            "zero_length_edges", "missing_material_faces"):
                    _require(type(mesh.get(key)) is int and mesh[key] >= 0, f"Invalid mesh.{key}")
                for key in ("geometry_sha256", "topology_sha256"):
                    _sha256(mesh.get(key), f"mesh.{key}")
            if "material_assignment_sha256" in obj:
                _sha256(obj["material_assignment_sha256"], "material_assignment_sha256")
            _require(isinstance(obj.get("materials", []), list), "materials must be an array")
            for material in obj.get("materials", []):
                _require(material is None or isinstance(material, dict), "Invalid material summary")
                if material is not None:
                    _identifier(material.get("id"), "material id")
        parents = {obj["id"]: obj.get("parent") for obj in objects}
        for obj_id, parent in parents.items():
            _require(parent is None or parent in ids, f"Unknown parent of {obj_id}: {parent}")
            seen = {obj_id}
            while parent is not None:
                _require(parent not in seen, f"Cyclic hierarchy at {obj_id}")
                seen.add(parent)
                parent = parents[parent]
    return snapshot


def validate_contract(contract):
    contract = {"schema_version": CONTRACT_SCHEMA} if contract is None else contract
    finite_tree(contract)
    allowed = {"schema_version", "required_objects", "connections", "contacts", "hinge_axes", "invariants", "camera_id",
               "triangle_budget", "require_closed_mesh", "ground_z", "ground_objects", "ground_tolerance"}
    _keys(contract, allowed, {"schema_version"}, "contract")
    _require(contract["schema_version"] == CONTRACT_SCHEMA, f"Expected {CONTRACT_SCHEMA}")
    if "camera_id" in contract:
        _identifier(contract["camera_id"], "camera_id")
    for group in ("required_objects", "connections", "contacts", "hinge_axes", "invariants", "require_closed_mesh", "ground_objects"):
        _require(isinstance(contract.get(group, []), list) and len(contract.get(group, [])) <= 256,
                 f"{group} requires at most 256 entries")
    for obj_id in contract.get("required_objects", []):
        _identifier(obj_id, "required object ID")
    _require(len(set(contract.get("required_objects", []))) == len(contract.get("required_objects", [])),
             "Duplicate required object ID")
    for group in ("require_closed_mesh", "ground_objects"):
        for obj_id in contract.get(group, []):
            _identifier(obj_id, group + " object ID")
        _require(len(set(contract.get(group, []))) == len(contract.get(group, [])), f"Duplicate {group} object ID")
    if "triangle_budget" in contract:
        _require(type(contract["triangle_budget"]) is int and contract["triangle_budget"] >= 0,
                 "triangle_budget must be a nonnegative integer")
    if "ground_z" in contract:
        _number(contract["ground_z"], "ground_z", -math.inf)
        _require(bool(contract.get("ground_objects")), "ground_z requires explicit ground_objects")
    if contract.get("ground_objects"):
        _require("ground_z" in contract, "ground_objects requires an explicit ground_z")
    if "ground_tolerance" in contract:
        _number(contract["ground_tolerance"], "ground_tolerance")
        _require(bool(contract.get("ground_objects")), "ground_tolerance requires explicit ground_objects")
    check_ids = set()
    for group in ("connections", "contacts", "hinge_axes"):
        for check in contract.get(group, []):
            fields = {"id", "a", "b", "tolerance"} if group != "hinge_axes" else {
                "id", "a", "b", "distance_tolerance", "angle_tolerance_degrees"}
            _keys(check, fields, fields, group)
            _identifier(check["id"], "check id")
            _require(check["id"] not in check_ids, f"Duplicate check ID {check['id']}")
            check_ids.add(check["id"])
            for side in ("a", "b"):
                if group == "contacts":
                    _identifier(check[side], "contact object ID")
                else:
                    endpoint = check[side]
                    keys = {"object_id", "point", "axis"} if group == "hinge_axes" else {"object_id", "point"}
                    _keys(endpoint, keys, keys, "endpoint")
                    _identifier(endpoint["object_id"], "endpoint object ID")
                    _vector(endpoint["point"], "endpoint point")
                    if group == "hinge_axes":
                        _vector(endpoint["axis"], "endpoint axis")
                        _require(_norm(endpoint["axis"]) > 1e-12, "Hinge axis must be nonzero")
            if group == "hinge_axes":
                _number(check["distance_tolerance"], "distance_tolerance")
                _require(_number(check["angle_tolerance_degrees"], "angle_tolerance_degrees") <= 90,
                         "angle_tolerance_degrees must be <= 90")
            else:
                _number(check["tolerance"], "tolerance")
    invariant_ids = set()
    for invariant in contract.get("invariants", []):
        _keys(invariant, {"object_id", "properties", "tolerance"}, {"object_id", "properties"}, "invariant")
        _identifier(invariant["object_id"], "invariant object ID")
        _require(invariant["object_id"] not in invariant_ids, "Duplicate invariant object ID")
        invariant_ids.add(invariant["object_id"])
        props = invariant["properties"]
        _require(isinstance(props, list) and bool(props) and all(isinstance(x, str) for x in props)
                 and set(props) <= PROPERTIES and len(set(props)) == len(props), "Invalid invariant properties")
        _number(invariant.get("tolerance", 1e-6), "invariant tolerance")
    return contract


def _norm(vector):
    return math.hypot(*vector)


def _sub(a, b):
    return [x - y for x, y in zip(a, b)]


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def _transform(matrix, vector, point=True):
    result = [sum(matrix[row][col] * vector[col] for col in range(3))
              + (matrix[row][3] if point else 0) for row in range(3)]
    finite_tree(result, "transformed endpoint")
    return result


def _world_endpoint(objects, endpoint):
    obj = objects[endpoint["object_id"]]
    point = _transform(obj["world_matrix"], endpoint["point"])
    if "axis" not in endpoint:
        return point
    axis = _transform(obj["world_matrix"], endpoint["axis"], point=False)
    length = _norm(axis)
    _require(math.isfinite(length) and length > 1e-12, f"Collapsed hinge axis on {obj['id']}")
    return point, [value / length for value in axis]


def _finding(findings, code, title, severity, object_ids, frame=None, constraint="review_required", **details):
    result = {"id": code, "title": title, "severity": severity, "object_ids": sorted(set(object_ids)),
              "constraint": constraint, "details": details}
    if frame is not None:
        result["source_frame"] = frame
    findings.append(result)


def _report(kind, snapshots, contract, findings):
    camera = contract.get("camera_id")
    if camera:
        for item in findings:
            item["camera_id"] = camera
    status = "FAIL" if any(f["severity"] == "error" for f in findings) else (
        "REVIEW_REQUIRED" if any(f["constraint"] == "review_required" for f in findings) else "PASS")
    result = {"schema_version": REPORT_SCHEMA, "kind": kind, "status": status,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "sources": [dict(item["source"]) for item in snapshots],
              "snapshot_sha256": [fingerprint(item) for item in snapshots],
              "contract_sha256": fingerprint(contract), "findings": findings,
              "limitations": list(dict.fromkeys(LIMITATIONS + [limitation for item in snapshots
                  for sample in item["frames"] for limitation in sample.get("limitations", [])])),
              "provenance": {"engine": "animkit.diagnostics", "schema_version": 1,
                             "implementation_sha256": file_hash(__file__)}}
    finite_tree(result)
    return result


def _analyze(snapshot, contract):
    findings = []
    for sample in snapshot["frames"]:
        frame = sample["frame"]
        objects = {obj["id"]: obj for obj in sample["objects"]}
        requested = set(contract.get("required_objects", []))
        requested.update(contract.get("require_closed_mesh", []))
        requested.update(contract.get("ground_objects", []))
        camera = contract.get("camera_id")
        if camera:
            requested.add(camera)
        for group in ("connections", "contacts", "hinge_axes"):
            for check in contract.get(group, []):
                requested.update(check[side] if group == "contacts" else check[side]["object_id"] for side in ("a", "b"))
        for invariant in contract.get("invariants", []):
            requested.add(invariant["object_id"])
        missing = requested - objects.keys()
        for obj_id in sorted(missing):
            _finding(findings, f"missing:{frame}:{obj_id}", "Declared object is missing", "error", [obj_id], frame,
                     "hard", expected_id=obj_id)
        if camera in objects and objects[camera]["kind"] != "CAMERA":
            _finding(findings, f"camera:{frame}", "Declared camera ID is not a camera", "error", [camera], frame, "hard")
        if "triangle_budget" in contract:
            mesh_objects = [obj for obj in sample["objects"] if obj.get("mesh") is not None]
            actual = sum(obj["mesh"]["triangles"] for obj in mesh_objects)
            passed = actual <= contract["triangle_budget"]
            _finding(findings, f"triangle-budget:{frame}", "Triangle count is within the declared budget" if passed else "Declared triangle budget exceeded",
                     "info" if passed else "error", [obj["id"] for obj in mesh_objects], frame, "hard",
                     triangles=actual, maximum=contract["triangle_budget"], scope="all summarized meshes in this frame")
        for obj_id in contract.get("require_closed_mesh", []):
            if obj_id not in objects:
                continue
            mesh = objects[obj_id].get("mesh")
            passed = mesh is not None and mesh["vertices"] > 0 and mesh["faces"] > 0 and mesh["non_manifold_edges"] == 0
            _finding(findings, f"closed-mesh:{frame}:{obj_id}", "Mesh meets declared closed-edge requirement" if passed else "Declared closed-mesh requirement failed",
                     "info" if passed else "error", [obj_id], frame, "hard",
                     non_manifold_edges=mesh["non_manifold_edges"] if mesh else None,
                     boundary_edges=mesh["boundary_edges"] if mesh else None,
                     note="Edge manifoldness does not prove absence of self-intersection or correct surface orientation.")
        for obj_id in contract.get("ground_objects", []):
            if obj_id not in objects:
                continue
            bounds = objects[obj_id].get("bounds")
            if bounds is None:
                _finding(findings, f"ground:{frame}:{obj_id}", "Declared ground target has no mesh bounds", "error", [obj_id], frame, "hard")
                continue
            gap = bounds["min"][2] - contract["ground_z"]
            tolerance = contract.get("ground_tolerance", 0.001)
            passed = abs(gap) <= tolerance
            title = "Object bound meets the declared ground plane" if passed else (
                "Object bound is above the declared ground plane" if gap > 0 else "Object bound is below the declared ground plane")
            _finding(findings, f"ground:{frame}:{obj_id}", title, "info" if passed else "error", [obj_id], frame, "hard",
                     signed_distance=gap, ground_z=contract["ground_z"], tolerance=tolerance,
                     note="This checks the lowest evaluated mesh point against an explicit horizontal plane.")
        for obj in sample["objects"]:
            mesh = obj.get("mesh")
            if not mesh:
                continue
            for key, title in (("degenerate_faces", "Degenerate faces require review"),
                               ("zero_length_edges", "Zero-length edges require review"),
                               ("missing_material_faces", "Faces lack an assigned material"),
                               ("non_manifold_edges", "Non-manifold edges require context")):
                if mesh[key]:
                    _finding(findings, f"mesh:{frame}:{obj['id']}:{key}", title, "warning", [obj["id"]], frame,
                             count=mesh[key], metric=key, boundary_edges=mesh["boundary_edges"],
                             note="Open boundaries may be intentional; no automatic defect classification.")
        for group in ("connections", "contacts", "hinge_axes"):
            for check in contract.get(group, []):
                ids = [check[side] if group == "contacts" else check[side]["object_id"] for side in ("a", "b")]
                if any(obj_id in missing for obj_id in ids):
                    continue
                code = f"{group}:{frame}:{check['id']}"
                if group == "connections":
                    a, b = (_world_endpoint(objects, check[side]) for side in ("a", "b"))
                    distance = _norm(_sub(a, b))
                    passed = distance <= check["tolerance"]
                    _finding(findings, code, "Declared anchors coincide within tolerance" if passed else "Declared anchors separated",
                             "info" if passed else "error", ids, frame, "hard", distance=distance,
                             tolerance=check["tolerance"], a_world=a, b_world=b)
                elif group == "contacts":
                    a, b = (objects[obj_id].get("bounds") for obj_id in ids)
                    if a is None or b is None:
                        _finding(findings, code, "Contact cannot be checked without mesh bounds", "warning", ids, frame,
                                 reason="missing_bounds")
                        continue
                    gaps = [max(0, a["min"][i] - b["max"][i], b["min"][i] - a["max"][i]) for i in range(3)]
                    distance = _norm(gaps)
                    if distance > check["tolerance"]:
                        _finding(findings, code, "Declared contact is separated by its bounds", "error", ids, frame, "hard",
                                 aabb_gap=distance, tolerance=check["tolerance"])
                    else:
                        _finding(findings, code, "Contact remains unverified by overlapping or nearby bounds", "warning", ids, frame,
                                 aabb_gap=distance, tolerance=check["tolerance"], contact_verified=False,
                                 note="AABB proximity cannot establish surface contact, penetration or collision freedom.")
                else:
                    try:
                        (a, u), (b, v) = (_world_endpoint(objects, check[side]) for side in ("a", "b"))
                    except ValueError as exc:
                        _finding(findings, code, "Hinge axis cannot be evaluated", "error", ids, frame, "hard", reason=str(exc))
                        continue
                    angle = math.degrees(math.acos(min(1, max(0, abs(_dot(u, v))))))
                    delta = _sub(b, a)
                    # Compare the declared points against both axis lines. A shortest
                    # distance between infinite lines would hide remotely intersecting axes.
                    distance = max(_norm(_cross(delta, u)), _norm(_cross(delta, v)))
                    passed = distance <= check["distance_tolerance"] and angle <= check["angle_tolerance_degrees"]
                    _finding(findings, code, "Declared hinge axes align within tolerance" if passed else "Declared hinge axes misalign",
                             "info" if passed else "error", ids, frame, "hard", axis_distance=distance,
                             angle_degrees=angle, distance_tolerance=check["distance_tolerance"],
                             angle_tolerance_degrees=check["angle_tolerance_degrees"], axes_are_undirected=True)
    return findings


def analyze(snapshot, contract=None):
    validate_snapshot(snapshot)
    contract = validate_contract(contract)
    findings = _analyze(snapshot, contract)
    if contract.get("invariants"):
        _finding(findings, "invariants:baseline-required", "Revision invariants require a before/after comparison", "warning",
                 [item["object_id"] for item in contract["invariants"]])
    return _report("analyze", [snapshot], contract, findings)


def _property(obj, name):
    if name == "semantic_role":
        return obj.get("semantic_role")
    if name == "hierarchy":
        return obj.get("parent")
    if name == "transform":
        return obj["world_matrix"]
    if name == "materials":
        return {"slots": obj.get("materials", []), "assignments_sha256": obj.get("material_assignment_sha256")}
    mesh = obj.get("mesh")
    if mesh is None:
        return None
    return mesh["geometry_sha256" if name == "geometry" else "topology_sha256"]


def compare(before, after, contract=None):
    validate_snapshot(before)
    validate_snapshot(after)
    contract = validate_contract(contract)
    left = {sample["frame"]: sample for sample in before["frames"]}
    right = {sample["frame"]: sample for sample in after["frames"]}
    _require(left.keys() == right.keys(), "Revision comparison requires identical sampled frame numbers")
    findings = _analyze(after, contract)
    invariants = {item["object_id"]: item for item in contract.get("invariants", [])}
    for obj_id in invariants:
        _require(any(obj_id == obj["id"] for sample in left.values() for obj in sample["objects"]),
                 f"Invariant ID does not exist in baseline: {obj_id}")
    for frame in sorted(left):
        _require(left[frame]["meters_per_unit"] == right[frame]["meters_per_unit"],
                 "Revision comparison requires identical meters_per_unit")
        a = {obj["id"]: obj for obj in left[frame]["objects"]}
        b = {obj["id"]: obj for obj in right[frame]["objects"]}
        for obj_id in sorted(a.keys() - b.keys()):
            hard = obj_id in invariants or obj_id in contract.get("required_objects", [])
            _finding(findings, f"removed:{frame}:{obj_id}", "Object was removed", "error" if hard else "warning", [obj_id], frame,
                     "hard" if hard else "review_required")
        for obj_id in sorted(b.keys() - a.keys()):
            _finding(findings, f"added:{frame}:{obj_id}", "Object was added", "info", [obj_id], frame)
        for obj_id in sorted(a.keys() & b.keys()):
            invariant = invariants.get(obj_id, {})
            if a[obj_id]["kind"] != b[obj_id]["kind"]:
                _finding(findings, f"kind:{frame}:{obj_id}", "Object type changed", "error" if invariant else "warning", [obj_id], frame,
                         "hard" if invariant else "review_required", before=a[obj_id]["kind"], after=b[obj_id]["kind"])
            for prop in sorted(PROPERTIES):
                old, new = _property(a[obj_id], prop), _property(b[obj_id], prop)
                if prop in {"geometry", "topology"} and prop in invariant.get("properties", []) and (old is None or new is None):
                    _finding(findings, f"unverified:{frame}:{obj_id}:{prop}", f"Object {prop} invariant cannot be checked",
                             "warning", [obj_id], frame, reason="Evaluated mesh summary is unavailable")
                    continue
                delta = max(abs(x - y) for ra, rb in zip(old, new) for x, y in zip(ra, rb)) if prop == "transform" else None
                changed = delta > invariant.get("tolerance", 1e-6) if prop == "transform" else old != new
                if changed:
                    hard = prop in invariant.get("properties", [])
                    _finding(findings, f"changed:{frame}:{obj_id}:{prop}", f"Object {prop} changed",
                             "error" if hard else "info", [obj_id], frame, "hard" if hard else "review_required",
                             property=prop, before=old, after=new, max_matrix_delta=delta)
    return _report("compare", [before, after], contract, findings)


def describe(snapshot, object_id=None, descendants=False, offset=0, limit=50, frame=None):
    """Scoped/paginated facts. Aggregate counts cover the entire scope before paging."""
    validate_snapshot(snapshot)
    _require(type(offset) is int and offset >= 0, "offset must be a nonnegative integer")
    _require(type(limit) is int and 1 <= limit <= 200, "limit must be between 1 and 200")
    _require(not descendants or object_id is not None, "descendants requires an object ID")
    if object_id is not None:
        _identifier(object_id, "scope object ID")
    samples = [sample for sample in snapshot["frames"] if frame is None or sample["frame"] == frame]
    _require(bool(samples), f"Snapshot has no sample at frame {frame}")
    described = []
    for sample in samples:
        objects = {obj["id"]: obj for obj in sample["objects"]}
        _require(object_id is None or object_id in objects, f"Unknown scope object ID: {object_id}")
        selected = set(objects) if object_id is None else {object_id}
        if descendants:
            children = {}
            for obj in objects.values():
                children.setdefault(obj.get("parent"), []).append(obj["id"])
            pending = [object_id]
            while pending:
                for child in children.get(pending.pop(), []):
                    if child not in selected:
                        selected.add(child)
                        pending.append(child)
        selected = sorted(selected)
        page = selected[offset:offset + limit]
        result_objects = []
        for obj_id in page:
            obj = objects[obj_id]
            bounds = obj.get("bounds")
            result_objects.append({"id": obj_id, "kind": obj["kind"], "parent": obj.get("parent"),
                                   "semantic_role": obj.get("semantic_role"), "role_evidence": obj.get("role_evidence"),
                                   "children": sorted(item["id"] for item in objects.values() if item.get("parent") == obj_id),
                                   "bounds": bounds,
                                   "dimensions": [b-a for a, b in zip(bounds["min"], bounds["max"])] if bounds else None,
                                   "center": [(a+b)/2 for a, b in zip(bounds["min"], bounds["max"])] if bounds else None,
                                   "mesh": obj.get("mesh"),
                                   "material_ids": [item["id"] if item else None for item in obj.get("materials", [])]})
        meshes = [objects[obj_id]["mesh"] for obj_id in selected if objects[obj_id].get("mesh") is not None]
        described.append({"frame": sample["frame"], "meters_per_unit": sample["meters_per_unit"],
                          "scope": {"object_id": object_id, "descendants": descendants, "total": len(selected),
                                    "offset": offset, "limit": limit, "returned": len(page)},
                          "totals": {"mesh_objects": len(meshes), "vertices": sum(mesh["vertices"] for mesh in meshes),
                                     "triangles": sum(mesh["triangles"] for mesh in meshes)},
                          "objects": result_objects, "limitations": sample.get("limitations", [])})
    result = {"schema_version": "object-animation.scene-description/1", "source": dict(snapshot["source"]),
              "snapshot_sha256": fingerprint(snapshot), "frames": described}
    finite_tree(result)
    return result
