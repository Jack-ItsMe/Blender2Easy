"""Small numerical fixtures plus real Blender mesh/import smoke tests; no renders."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / "skills" / "blender2easy"
sys.path.insert(0, str(ROOT / "scripts"))
from animkit.common import resolve_tool
from animkit.diagnostics import (SNAPSHOT_SCHEMA, CONTRACT_SCHEMA, analyze, compare,
                                describe, file_hash, validate_snapshot, write_fresh)
from diagnostics_cli import capture, main


def object_fixture(name, x=0, axis_rotation=False):
    matrix = [[1, 0, 0, x], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    if axis_rotation:
        matrix = [[0, 0, 1, x], [0, 1, 0, 0], [-1, 0, 0, 0], [0, 0, 0, 1]]
    return {"id": name, "kind": "MESH", "parent": None, "world_matrix": matrix,
            "bounds": {"min": [x-1, -1, -1], "max": [x+1, 1, 1]}, "materials": [],
            "mesh": {"vertices": 8, "edges": 12, "faces": 6, "triangles": 12,
                     "connected_components": 1, "non_manifold_edges": 0, "boundary_edges": 0,
                     "degenerate_faces": 0, "zero_length_edges": 0, "missing_material_faces": 0,
                     "geometry_sha256": "1"*64, "topology_sha256": "2"*64}}


def snapshot_fixture(frames=(1, 3)):
    return {"schema_version": SNAPSHOT_SCHEMA, "source": {"path": "fixture.blend", "sha256": "0"*64},
            "frames": [{"frame": frame, "meters_per_unit": 1,
                        "objects": [object_fixture("Base"), object_fixture("Lid")]}
                       for frame in frames]}


def contract_fixture():
    return {"schema_version": CONTRACT_SCHEMA}


class DiagnosticsTests(unittest.TestCase):
    def test_anchor_checks_every_sample(self):
        snapshot = snapshot_fixture()
        snapshot["frames"][1]["objects"][1] = object_fixture("Lid", x=2)
        contract = contract_fixture()
        contract["connections"] = [{"id": "pivot", "a": {"object_id": "Base", "point": [0, 0, 0]},
                                    "b": {"object_id": "Lid", "point": [0, 0, 0]}, "tolerance": 0.01}]
        report = analyze(snapshot, contract)
        self.assertEqual(report["status"], "FAIL")
        errors = [item for item in report["findings"] if item["severity"] == "error"]
        self.assertEqual([item["source_frame"] for item in errors], [3])
        self.assertEqual(errors[0]["details"]["distance"], 2)

    def test_contact_overlap_is_not_verified(self):
        contract = contract_fixture()
        contract["contacts"] = [{"id": "seat", "a": "Base", "b": "Lid", "tolerance": 0.01}]
        report = analyze(snapshot_fixture(), contract)
        self.assertEqual(report["status"], "REVIEW_REQUIRED")
        self.assertTrue(all(item["details"]["contact_verified"] is False for item in report["findings"]))
        separated = snapshot_fixture((1,))
        separated["frames"][0]["objects"][1] = object_fixture("Lid", x=5)
        report = analyze(separated, contract)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["findings"][0]["details"]["aabb_gap"], 3)

    def test_hinge_axes_accept_reversed_direction_and_detect_tilt(self):
        snapshot = snapshot_fixture()
        snapshot["frames"][1]["objects"][1] = object_fixture("Lid", axis_rotation=True)
        contract = contract_fixture()
        contract["hinge_axes"] = [{"id": "hinge", "a": {"object_id": "Base", "point": [0, 0, 0], "axis": [0, 0, 1]},
                                   "b": {"object_id": "Lid", "point": [0, 0, 0], "axis": [0, 0, -1]},
                                   "distance_tolerance": 0.01, "angle_tolerance_degrees": 1}]
        report = analyze(snapshot, contract)
        self.assertEqual([item["severity"] for item in report["findings"]], ["info", "error"])
        self.assertAlmostEqual(report["findings"][1]["details"]["angle_degrees"], 90)
        snapshot["frames"][1]["objects"][1] = object_fixture("Lid", x=0.5)
        report = analyze(snapshot, contract)
        self.assertAlmostEqual(report["findings"][1]["details"]["axis_distance"], 0.5)

    def test_unknown_ids_fail_and_schema_is_strict(self):
        contract = contract_fixture()
        contract["connections"] = [{"id": "pivot", "a": {"object_id": "TYPO", "point": [0, 0, 0]},
                                    "b": {"object_id": "Lid", "point": [0, 0, 0]}, "tolerance": 0.01}]
        result = analyze(snapshot_fixture(), contract)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["findings"][0]["object_ids"], ["TYPO"])
        contract["connection"] = []
        with self.assertRaisesRegex(ValueError, "Unknown contract fields"):
            analyze(snapshot_fixture(), contract)
        with self.assertRaisesRegex(ValueError, "Missing contract fields"):
            analyze(snapshot_fixture(), {})

    def test_nonfinite_duplicate_and_cycles_rejected(self):
        snapshot = snapshot_fixture()
        snapshot["frames"][0]["objects"][0]["world_matrix"][0][0] = float("nan")
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            validate_snapshot(snapshot)
        snapshot = snapshot_fixture()
        snapshot["frames"][0]["objects"][1]["id"] = "Base"
        with self.assertRaisesRegex(ValueError, "Duplicate object"):
            validate_snapshot(snapshot)
        snapshot = snapshot_fixture()
        snapshot["frames"][0]["objects"][0]["parent"] = "Lid"
        snapshot["frames"][0]["objects"][1]["parent"] = "Base"
        with self.assertRaisesRegex(ValueError, "Cyclic hierarchy"):
            validate_snapshot(snapshot)

    def test_snapshot_rejects_malformed_fingerprints_and_limitations(self):
        for field in ('geometry_sha256', 'topology_sha256'):
            snapshot = snapshot_fixture((1,))
            snapshot['frames'][0]['objects'][0]['mesh'][field] = 'z' * 64
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Invalid mesh'):
                validate_snapshot(snapshot)
        snapshot = snapshot_fixture((1,))
        snapshot['frames'][0]['objects'][0]['material_assignment_sha256'] = 'invalid'
        with self.assertRaisesRegex(ValueError, 'material_assignment_sha256'):
            validate_snapshot(snapshot)
        for limitations in ('not an array', [{'unexpected': 'object'}]):
            snapshot = snapshot_fixture((1,))
            snapshot['frames'][0]['limitations'] = limitations
            with self.subTest(limitations=limitations), self.assertRaisesRegex(ValueError, 'limitations'):
                analyze(snapshot)

    def test_revision_invariants_and_unconstrained_changes(self):
        before = snapshot_fixture()
        after = copy.deepcopy(before)
        after["frames"][0]["objects"][1]["mesh"]["geometry_sha256"] = "3"*64
        after["frames"][1]["objects"][1]["parent"] = "Base"
        after["frames"][0]["objects"].append(object_fixture("New"))
        contract = contract_fixture()
        contract["invariants"] = [{"object_id": "Lid", "properties": ["geometry"]}]
        report = compare(before, after, contract)
        errors = [item for item in report["findings"] if item["severity"] == "error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["details"]["property"], "geometry")
        self.assertTrue(any(item["id"] == "changed:3:Lid:hierarchy" and item["constraint"] == "review_required"
                            for item in report["findings"]))
        self.assertTrue(any(item["id"] == "added:1:New" for item in report["findings"]))
        self.assertEqual(analyze(before, contract)["status"], "REVIEW_REQUIRED")

    def test_revision_rejects_mismatched_frames_and_unknown_invariant(self):
        with self.assertRaisesRegex(ValueError, "identical sampled"):
            compare(snapshot_fixture((1,)), snapshot_fixture((3,)))
        contract = contract_fixture()
        contract["invariants"] = [{"object_id": "TYPO", "properties": ["geometry"]}]
        with self.assertRaisesRegex(ValueError, "does not exist in baseline"):
            compare(snapshot_fixture(), snapshot_fixture(), contract)

    def test_nonmesh_invariant_requires_review(self):
        before = snapshot_fixture((1,))
        before["frames"][0]["objects"][0].update({"kind": "EMPTY", "mesh": None, "bounds": None})
        contract = contract_fixture()
        contract["invariants"] = [{"object_id": "Base", "properties": ["geometry"]}]
        report = compare(before, copy.deepcopy(before), contract)
        self.assertEqual(report["status"], "REVIEW_REQUIRED")
        self.assertIn("cannot be checked", report["findings"][0]["title"])

    def test_explicit_triangle_closed_and_ground_constraints(self):
        contract = contract_fixture()
        contract.update({"triangle_budget": 23, "require_closed_mesh": ["Lid"],
                         "ground_objects": ["Base"], "ground_z": 0, "ground_tolerance": 0.01})
        snapshot = snapshot_fixture((1,))
        snapshot["frames"][0]["objects"][1]["mesh"]["non_manifold_edges"] = 4
        snapshot["frames"][0]["objects"][1]["mesh"]["boundary_edges"] = 4
        report = analyze(snapshot, contract)
        errors = {item["id"] for item in report["findings"] if item["severity"] == "error"}
        self.assertEqual(errors, {"triangle-budget:1", "closed-mesh:1:Lid", "ground:1:Base"})
        contract["triangle_budget"] = 24
        contract["ground_z"] = -1
        snapshot["frames"][0]["objects"][1]["mesh"]["non_manifold_edges"] = 0
        snapshot["frames"][0]["objects"][1]["mesh"]["boundary_edges"] = 0
        self.assertEqual(analyze(snapshot, contract)["status"], "PASS")
        del contract["ground_objects"]
        with self.assertRaisesRegex(ValueError, "explicit ground_objects"):
            analyze(snapshot, contract)

    def test_describe_scope_roles_and_unpaginated_totals(self):
        snapshot = snapshot_fixture((1,))
        snapshot["frames"][0]["objects"][1]["parent"] = "Base"
        snapshot["frames"][0]["objects"][0].update({"semantic_role": "support", "role_evidence": "animation_role"})
        result = describe(snapshot, "Base", descendants=True, offset=1, limit=1)
        frame = result["frames"][0]
        self.assertEqual(frame["scope"]["total"], 2)
        self.assertEqual(frame["totals"]["triangles"], 24)
        self.assertEqual([obj["id"] for obj in frame["objects"]], ["Lid"])
        self.assertEqual(describe(snapshot, "Base")["frames"][0]["objects"][0]["semantic_role"], "support")
        with self.assertRaisesRegex(ValueError, "Unknown scope"):
            describe(snapshot, "TYPO")
        with self.assertRaisesRegex(ValueError, "requires an object"):
            describe(snapshot, descendants=True)

    def test_cli_fresh_output_stale_after_and_historical_before(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "asset.blend"
            source.write_bytes(b"tiny fixture old")
            before = snapshot_fixture((1,))
            before["source"] = {"path": str(source), "sha256": file_hash(source)}
            write_fresh(root / "before.json", before)
            source.write_bytes(b"tiny fixture revised")
            after = copy.deepcopy(before)
            after["source"]["sha256"] = file_hash(source)
            write_fresh(root / "after.json", after)
            output = root / "report.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["compare", str(root / "before.json"), str(root / "after.json"), "--output", str(output)]), 0)
                self.assertEqual(main(["analyze", str(root / "after.json"), "--output", str(output)]), 1)
                self.assertEqual(main(["analyze", str(root / "before.json"), "--output", str(root / "stale.json")]), 1)
            self.assertTrue(json.loads(output.read_text())["provenance"]["historical_baseline"])
            self.assertFalse((root / "stale.json").exists())


@unittest.skipUnless(os.environ.get("BLENDER2EASY_TEST_BLENDER") == "1",
                     "Use scripts/check.py --with-blender for Blender integration")
class BlenderSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.blender = resolve_tool("blender")
        except ValueError as exc:
            raise unittest.SkipTest(str(exc))

    def test_real_evaluated_animation_snapshot_and_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "fixture.py"
            script.write_text('''import bpy, sys\nfrom pathlib import Path\nroot = Path(sys.argv[sys.argv.index("--") + 1])
bpy.ops.wm.read_factory_settings(use_empty=True)
material = bpy.data.materials.new("FixtureMaterial")
bpy.ops.mesh.primitive_cube_add(size=1)
base = bpy.context.object
base.name = "Base"
base["animation_role"] = "fixture_support"
base.data.materials.append(material)
bevel = base.modifiers.new("EvaluatedBevel", "BEVEL")
bevel.width = 0.05
bevel.segments = 2
bpy.ops.mesh.primitive_cube_add(size=1)
lid = bpy.context.object
lid.name = "Lid"
lid.data.materials.append(material)
lid.location.x = 0
lid.keyframe_insert(data_path="location", frame=1)
lid.location.x = 2
lid.keyframe_insert(data_path="location", frame=3)
bpy.context.scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(root / "fixture.blend"))
bpy.ops.export_scene.gltf(filepath=str(root / "fixture.glb"), export_format="GLB")
bpy.ops.export_scene.gltf(filepath=str(root / "fixture.gltf"), export_format="GLTF_SEPARATE")
bpy.ops.wm.obj_export(filepath=str(root / "fixture.obj"))
bpy.ops.export_scene.fbx(filepath=str(root / "fixture.fbx"))
''', encoding="utf-8")
            completed = subprocess.run([self.blender, "--background", "--factory-startup", "--disable-autoexec",
                                        "--python-exit-code", "1", "--python", str(script), "--", str(root)],
                                       capture_output=True, text=True, timeout=120,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(completed.returncode, 0, completed.stdout[-4000:] + completed.stderr[-1000:])
            source = root / "fixture.blend"
            initial_hash = file_hash(source)
            result = capture(source, root / "snapshot.json", "1,3", self.blender)
            self.assertEqual(initial_hash, file_hash(source))
            first = {obj["id"]: obj for obj in result["frames"][0]["objects"]}
            third = {obj["id"]: obj for obj in result["frames"][1]["objects"]}
            self.assertGreater(first["Base"]["mesh"]["vertices"], 8)
            self.assertAlmostEqual(first["Lid"]["world_matrix"][0][3], 0)
            self.assertAlmostEqual(third["Lid"]["world_matrix"][0][3], 2)
            self.assertEqual(first["Base"]["mesh"]["geometry_sha256"], third["Base"]["mesh"]["geometry_sha256"])
            self.assertEqual(first["Base"]["materials"][0]["id"], "FixtureMaterial")
            self.assertEqual(first["Base"]["semantic_role"], "fixture_support")
            negative_output = root / "negative-frames.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["snapshot", str(source), "--frames=-2,3", "--output", str(negative_output),
                                       "--blender", self.blender]), 0)
            negative_snapshot = json.loads(negative_output.read_text(encoding="utf-8"))
            self.assertEqual([sample["frame"] for sample in negative_snapshot["frames"]], [-2, 3])
            contract = contract_fixture()
            contract["connections"] = [{"id": "pivot", "a": {"object_id": "Base", "point": [0, 0, 0]},
                                        "b": {"object_id": "Lid", "point": [0, 0, 0]}, "tolerance": 0.01}]
            self.assertEqual(analyze(result, contract)["status"], "FAIL")
            for extension in ("glb", "gltf", "fbx", "obj"):
                with self.subTest(extension=extension):
                    imported = capture(root / f"fixture.{extension}", root / f"{extension}.json", "1", self.blender)
                    self.assertGreaterEqual(len(imported["frames"][0]["objects"]), 2)
                    self.assertTrue(imported["provenance"]["source_unchanged"])


if __name__ == "__main__":
    unittest.main()
