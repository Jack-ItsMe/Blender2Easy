# Evaluated structure, motion and revision diagnostics

`diagnose` inspects actual evaluated Blender geometry in a separate background
process, then applies explicit numerical contracts. It does not infer which parts
should connect, classify open boundaries as defects, or prove collision freedom.
No source asset is saved by the diagnostic worker.

```powershell
python scripts/animation.py diagnose snapshot assembly.blend --frames 1,24,48 --output inspection.json
python scripts/animation.py diagnose describe inspection.json --object Base --descendants --offset 0 --limit 30
python scripts/animation.py diagnose analyze inspection.json --contract constraints.json --output findings.json
python scripts/animation.py diagnose compare before.json after.json --contract constraints.json --output changes.json
```

Snapshot accepts `.blend`, `.glb`, `.gltf`, `.fbx` and `.obj`; it has `--blender`
and `--timeout` options. The default timeout is 120 seconds (maximum 3600). Each
output must be a new file. Exit codes are 0 for a completed snapshot or report
without hard violations, 2 for a completed report containing hard violations,
and 1 for invalid input, a stale current snapshot or an execution failure.
`REVIEW_REQUIRED` reports return 0 because they are completed evidence, not a
failed command. Always inspect the report status and findings.

## Contract schema

All object identifiers are exact `id` values in the snapshot, currently Blender
`name_full`. They are stable only while names remain unchanged. A rename is
reported as removal plus addition. Anchor points and axes are object-local;
tolerances and reported distances use Blender world units. Multiply distances by
`meters_per_unit` to obtain meters. Axes are directions, not Euler rotations.

```json
{
  "schema_version": "object-animation.diagnostic-contract/1",
  "required_objects": ["Base", "Lid"],
  "triangle_budget": 250000,
  "require_closed_mesh": ["Base"],
  "ground_objects": ["Base"],
  "ground_z": 0,
  "ground_tolerance": 0.001,
  "connections": [{
    "id": "pivot",
    "a": {"object_id": "Base", "point": [0, 0, 0]},
    "b": {"object_id": "Lid", "point": [0, 0, 0]},
    "tolerance": 0.001
  }],
  "contacts": [{"id": "seat", "a": "Base", "b": "Lid", "tolerance": 0.002}],
  "hinge_axes": [{
    "id": "hinge",
    "a": {"object_id": "Base", "point": [0, 0, 0], "axis": [0, 0, 1]},
    "b": {"object_id": "Lid", "point": [0, 0, 0], "axis": [0, 0, 1]},
    "distance_tolerance": 0.001,
    "angle_tolerance_degrees": 0.5
  }],
  "invariants": [{
    "object_id": "Base",
    "properties": ["geometry", "topology", "hierarchy", "transform", "materials"],
    "tolerance": 0.000001
  }]
}
```

Only `schema_version` is required. `camera_id` is optional and must identify an
actual camera; it labels findings for a preview camera and does not change the
world-space checks. Unknown contract fields, duplicate check IDs, non-finite
numbers, malformed matrices and invalid axes are rejected. Unknown object IDs
produce hard error findings; unknown invariant IDs in the comparison baseline
reject the comparison. Each contract group supports at most 256 entries.

`connections` measures the Euclidean distance between declared world-space
anchors on every sample. `hinge_axes` checks the acute angle between the two
transformed, normalized axes and the maximum distance of each declared point
from the other axis line. Reversing an axis is equivalent. Passing these checks
does not establish allowed rotation, hinge limits, pivot physics, or behavior
between frames.

`triangle_budget` checks all summarized mesh triangles in each frame, including
hidden objects. `require_closed_mesh` explicitly names the meshes which must be
nonempty with zero non-manifold edges. Passing this edge test does not prove
absence of self-intersection or correct surface orientation. Ground checks run
only when both `ground_objects` and a finite `ground_z` are provided; the lowest
mesh bound must lie within `ground_tolerance` (default 0.001) of that horizontal
plane. No implicit ground plane, closed-mesh requirement or triangle budget is
applied to arbitrary imported scenes.

`contacts` uses a world AABB separation lower bound. A gap beyond the declared
tolerance fails the contact constraint. Overlapping or nearby boxes always
produce `review_required`; their actual surfaces may still be separated,
penetrating, or correctly touching. This is not a mesh collision engine.

`invariants` is meaningful with `compare`; `analyze` marks it as requiring a
baseline. Geometry fingerprints contain evaluated object-local vertex positions;
topology fingerprints contain vertex counts and edge/face connectivity. These
fingerprints compare exactly, so a vertex reorder is a change. Hierarchy compares
parent IDs. Transform compares all 16 world-matrix elements using `tolerance`
(default `1e-6`). Material checks compare recorded slot summaries and face-slot
assignments; they do not prove complete shader or texture equality. Geometry and
topology invariants on non-mesh objects remain unverified.
The optional `semantic_role` invariant compares only explicitly authored roles.

Unconstrained additions, removals and changes are factual review findings.
Declared invariant changes are hard errors. The comparison requires identical
sample frame numbers and unit scales; it does not align different animation
timelines or renamed objects.

`describe` reports compact hierarchy, roles, bounds, dimensions, centers and mesh
facts. `--object ID` scopes to one object; `--descendants` includes its descendants.
`--offset` and `--limit` paginate the selected objects (limit 1..200, default 50).
Aggregate counts always cover the entire selected scope before pagination.
`--frame N` chooses one captured sample; omitted, each captured frame is described.
The output is JSON on stdout; `--output` optionally also saves a fresh JSON file.
Authored `animation_role` is preferred over `bas_role`, and the property supplying
the role is recorded as `role_evidence`. Missing roles remain null.

## Snapshot and report provenance

Snapshots use `object-animation.scene-snapshot/1`, with a `source` containing the
absolute primary asset path and SHA-256, Blender/worker provenance, and up to 32
`frames`. Each sample records frame, fps, `meters_per_unit`, active camera,
evaluated world transforms, world bounds, parent IDs, mesh counts, connected
components, non-manifold/boundary/degenerate/zero-length element counts, material
summaries, and exact geometry/topology fingerprints. Evaluated modifiers are
included. The active scene has a limit of 2048 objects and two million vertices
and faces per frame, with additional edge/loop limits. Hidden objects are
included; generated instances are not expanded. Per-sample limitations are
recorded explicitly.

The source hash is verified before and after Blender execution. Scripts inside
`.blend` files are disabled. Current source hashes are also verified before and
after analysis. Reports are never written over an existing path. Primary asset
hashes do not include external image files, geometry caches or linked files.

For a revision, capture `before.json`, make the intended edit, then capture
`after.json`. The historical baseline need not still exist on disk: compare
uses its recorded evaluated data and original source hash. The after asset must
still match its snapshot hash. Report provenance explicitly marks a historical
baseline, records exact input snapshot-file hashes and contract-file hash, and
verifies the current after source. Treat snapshots as trusted local evidence;
they are not signed and cannot authenticate a manually edited baseline.

Reports use `object-animation.diagnostic-report/1`. They contain `sources`
([before, after] for comparisons), normalized snapshot and contract fingerprints,
implementation provenance, `status` (`PASS`, `REVIEW_REQUIRED`, `FAIL`) and
`findings`. `PASS` means no tested constraint failed and no generated finding
requires review, not a claim of visual quality or complete scene correctness.

Each finding has `id`, `title`, `severity` (`info`, `warning`, `error`),
`object_ids`, optional `source_frame`/`camera_id`, `constraint` (`hard` or
`review_required`) and factual `details`. A preview can attach the normalized
finding fields and retain details in the original report. Before displaying a
report as current evidence, verify the last `sources` item against the current
asset; the first source of a comparison is intentionally historical.

To turn a finding into a focused user judgment, attach the report through
`review create PROJECT --spec SPEC --diagnostics findings.json`. Read
[the review evidence contract](review.md#diagnostic-findings) for source/build
matching, selection and frozen hashes. Only eligible findings within the
request's object/frame scope are displayed; the complete numerical details stay
in the report. A displayed finding describes the frozen source and is not
recomputed when the user adjusts a preview control.

The extractor/declared-anchor approach is informed by Blender Agent Studio's
MIT-licensed SceneIR and analysis tooling. The vendored source and license are
under `vendor/bas`. These diagnostics add bounded multi-frame anchor/axis checks
and revision fingerprints; the separate `quality` command exposes the vendored
tools such as reference comparison and camera fitting.
