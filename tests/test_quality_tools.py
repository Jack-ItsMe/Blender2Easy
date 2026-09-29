"""Bounded adapter behavior checks; no GPU or external integrations required."""
from pathlib import Path
import argparse
import ast
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "blender2easy" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from animkit import quality_tools as q


class QualityAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.asset = self.base / "fixture.blend"
        self.asset.write_bytes(b"bounded test fixture")
        self.spec = {"input": "fixture.blend", "outputDir": "new-output"}

    def write_spec(self, updates=None):
        value = self.spec | (updates or {})
        path = self.base / "spec.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def runner(self, argv, **kwargs):
        self.assertFalse(kwargs["shell"])
        self.assertIn("--disable-autoexec", argv)
        self.assertIn("--python-exit-code", argv)
        self.assertEqual(kwargs["timeout"], 25)
        self.assertEqual(Path(argv[argv.index("--python") + 1]), q.PLUGIN / q.TOOLS["inspect"][0])
        report = Path(argv[argv.index("--output") + 1])
        report.write_text('{"fixture":true}', encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)

    def run_mocked(self, callback=None):
        with patch.object(q, "resolve_tool", return_value=sys.executable), patch.object(q.subprocess, "run", side_effect=callback or self.runner):
            return q.run_tool("inspect", self.write_spec(), timeout=25)

    def test_unknown_fields_cannot_select_arbitrary_code(self):
        for field in ("script", "python", "args", "command", "output"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "Unknown"):
                q.prepare("inspect", self.spec | {field: "danger"}, self.base)
        self.assertFalse((self.base / "new-output").exists())

    def test_relative_paths_are_relative_to_spec(self):
        plan = q.prepare("inspect", self.spec, self.base)
        self.assertEqual(plan["inputs"][0][1], self.asset)
        self.assertEqual(plan["output"], self.base / "new-output")

    def test_existing_output_is_rejected_even_if_empty(self):
        (self.base / "new-output").mkdir()
        with self.assertRaisesRegex(ValueError, "must be new"):
            q.prepare("inspect", self.spec, self.base)

    def test_motion_budget_and_exact_names(self):
        for fields in ({"frames": [1], "targets": ["Cube"]},
                       {"frames": [2, 1], "targets": ["Cube"]},
                       {"frames": [1, 2], "targets": ["--python"]},
                       {"frames": list(range(13)), "targets": ["Cube"]},
                       {"frames": [True, 2], "targets": ["Cube"]}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                q.prepare("motion", self.spec | fields, self.base)

    def test_negative_frame_lists_reach_blender_argument_parser(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--frames")
        for tool, extra in (("motion", {"targets": ["Cube"]}), ("evidence", {})):
            with self.subTest(tool=tool):
                plan = q.prepare(tool, self.spec | {"frames": [-1, 1]} | extra, self.base)
                parsed, _ = parser.parse_known_args(plan["args"])
                self.assertEqual(parsed.frames, "-1,1")

    def test_landmark_validation_and_finite_values(self):
        valid = {"name": "corner", "objectName": "Cube", "localPoint": [0, 0, 0], "referenceUv": [0.5, 0.5]}
        for item in (valid | {"localPoint": [float("nan"), 0, 0]}, valid | {"referenceUv": [1.1, 0]}, valid | {"localPoint": [True, 0, 0]}, valid | {"unknown": 1}):
            with self.subTest(item=item), self.assertRaises(ValueError):
                q._landmarks([item])
        self.assertEqual(json.loads(q._landmarks([valid])), [valid])

    def test_authored_render_budget(self):
        with self.assertRaisesRegex(ValueError, "at most 12"):
            q.prepare("authored-render", self.spec | {"frames": list(range(7)), "cameras": ["A", "B"]}, self.base)

    def test_mixamo_import_is_local_fbx_with_bounded_options(self):
        fbx = self.base / "motion.fbx"
        fbx.write_bytes(b"local motion fixture")
        spec = self.spec | {"input": "motion.fbx", "clipName": "Walk", "fps": 30}
        plan = q.prepare("mixamo-import", spec, self.base)
        self.assertEqual(plan["report"].name, "mixamo-import.json")
        self.assertIn("--clip-name", plan["args"])
        for change in ({"input": "fixture.blend"}, {"fps": 25}, {"clipName": " "}, {"clipName": "x" * 121}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                q.prepare("mixamo-import", spec | change, self.base)

    def test_mixamo_import_reserves_its_own_payload_directory(self):
        (self.base / "motion.fbx").write_bytes(b"local motion fixture")
        spec = self.write_spec({"input": "motion.fbx", "clipName": "Walk"})
        def run(argv, **kwargs):
            payload = Path(argv[argv.index("--output-dir") + 1])
            self.assertFalse(payload.exists())
            payload.mkdir()
            (payload / "animation.blend").write_bytes(b"candidate")
            (payload / "mixamo-import.json").write_text('{"candidate":"animation.blend"}')
            return subprocess.CompletedProcess(argv, 0)
        with patch.object(q, "resolve_tool", return_value=sys.executable), patch.object(q.subprocess, "run", side_effect=run):
            result = q.run_tool("mixamo-import", spec)
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["inputUnchanged"])

    def test_success_retains_content_provenance(self):
        result = self.run_mocked()
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["inputUnchanged"])
        provenance = json.loads(Path(result["provenance"]).read_text())
        self.assertEqual(provenance["inputs"], provenance["inputsAfter"])
        self.assertEqual(len(provenance["outputs"]), 1)
        self.assertEqual(provenance["runtime"]["executable"], sys.executable)
        self.assertTrue(provenance["upstream"]["scripts"])

    def test_changed_input_invalidates_success(self):
        def run(argv, **kwargs):
            result = self.runner(argv, **kwargs)
            self.asset.write_bytes(b"unexpected mutation")
            return result
        result = self.run_mocked(run)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["inputUnchanged"])

    def test_timeout_writes_failure_provenance(self):
        def run(argv, **kwargs): raise subprocess.TimeoutExpired(argv, 25)
        result = self.run_mocked(run)
        self.assertEqual(result["status"], "timeout")
        self.assertTrue(Path(result["provenance"]).is_file())
        self.assertTrue(result["inputUnchanged"])

    def test_missing_report_is_failure(self):
        result = self.run_mocked(lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0))
        self.assertEqual(result["status"], "failed")
        self.assertIn("required report", result["error"])

    def test_failed_process_is_failure(self):
        result = self.run_mocked(lambda argv, **kwargs: subprocess.CompletedProcess(argv, 17))
        self.assertEqual(result["status"], "failed")
        self.assertIn("17", result["error"])

    def test_frame_passes_to_reference_and_camera_fit(self):
        (self.base / "reference.png").write_bytes(b"test")
        landmark = {"name": "a", "objectName": "Cube", "referenceUv": [0.2, 0.3]}
        for tool, extra in (("reference", {"reference": "reference.png"}), ("camera-fit", {"width": 128, "height": 128, "landmarks": [landmark] * 3})):
            plan = q.prepare(tool, self.spec | extra | {"frame": 12}, self.base)
            self.assertIn("--frame", plan["args"])
            self.assertEqual(plan["args"][plan["args"].index("--frame") + 1], "12")

    def test_production_loaders_disable_embedded_scripts(self):
        for name in ("inspect_asset.py", "render_evidence.py", "compare_reference.py", "fit_reference_camera.py"):
            path = q.PLUGIN / q.VALIDATION / name
            tree = ast.parse(path.read_text(encoding="utf-8"))
            calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "open_mainfile"]
            self.assertTrue(calls)
            for call in calls:
                self.assertTrue(any(k.arg == "use_scripts" and isinstance(k.value, ast.Constant) and k.value.value is False for k in call.keywords))

    def test_catalog_paths_are_bundled(self):
        catalog = q.catalog()
        self.assertTrue(Path(catalog["specGuide"]).is_file())
        self.assertEqual(len(catalog["specialists"]), 11)
        for item in catalog["commands"]: self.assertTrue(Path(item["script"]).is_file())
        for item in catalog["specialists"]: self.assertTrue(Path(item["skill"]).is_file())
        for item in catalog["optionalHelpers"]: self.assertTrue((q.PLUGIN / item["source"]).is_file())


if __name__ == "__main__":
    unittest.main()
