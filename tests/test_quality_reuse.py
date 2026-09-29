"""Content-verified reuse: stale evidence must never start Blender or be replaced."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "blender2easy" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from animkit import quality_tools as q
import quality_cli


class QualityReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.asset = self.base / "source.blend"
        self.asset.write_bytes(b"packed test scene")
        self.dependency = self.base / "texture.png"
        self.dependency.write_bytes(b"declared texture")
        self.executable = self.base / "blender.exe"
        self.executable.write_bytes(b"test executable")
        self.spec = self.base / "spec.json"
        self.data = {"input": "source.blend", "outputDir": "result", "dependencies": ["texture.png"], "dependenciesComplete": True}
        self.spec.write_text(json.dumps(self.data), encoding="utf-8")
        self.output = self.base / "result"
        self.report = self.output / "payload" / "metrics.json"
        self.manifest = self.output / "provenance.json"
        self.addCleanup(patch.stopall)
        patch.object(q, "resolve_tool", return_value=str(self.executable)).start()
        self.process = patch.object(q.subprocess, "run", side_effect=self.runner).start()

    def runner(self, argv, **kwargs):
        report = Path(argv[argv.index("--output") + 1])
        report.write_text('{"hard_gate_pass":true}', encoding="utf-8")
        (report.parent / "evidence.png").write_bytes(b"complete output image")
        kwargs["stdout"].write(b"Blender test version\n")
        return subprocess.CompletedProcess(argv, 0)

    def fresh(self):
        result = q.run_tool("inspect", self.spec)
        self.assertEqual(result["status"], "complete")
        self.assertFalse(result["reused"])
        return result

    def rejected(self, pattern=None):
        saved = self.manifest.read_bytes() if self.manifest.exists() else None
        self.process.reset_mock()
        with self.assertRaisesRegex(ValueError, pattern or "Cannot reuse outputDir"):
            q.run_tool("inspect", self.spec, reuse=True)
        self.process.assert_not_called()
        if saved is not None: self.assertEqual(self.manifest.read_bytes(), saved)

    def test_hit_skips_process_and_preserves_every_file(self):
        first = self.fresh()
        contents = {p: p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
        self.process.reset_mock()
        second = q.run_tool("inspect", self.spec, timeout=120, reuse=True)
        self.process.assert_not_called()
        self.assertTrue(second["reused"])
        self.assertEqual(second["durationSeconds"], first["durationSeconds"])
        self.assertGreaterEqual(second["reuseVerificationSeconds"], 0)
        self.assertEqual(contents, {p: p.read_bytes() for p in self.output.rglob("*") if p.is_file()})

    def test_opt_in_on_missing_directory_runs_once(self):
        result = q.run_tool("inspect", self.spec, reuse=True)
        self.assertFalse(result["reused"])
        self.process.assert_called_once()

    def test_default_still_rejects_complete_existing_directory(self):
        self.fresh()
        self.process.reset_mock()
        with self.assertRaisesRegex(ValueError, "must be new"):
            q.run_tool("inspect", self.spec)
        self.process.assert_not_called()

    def test_unknown_dependency_coverage_cannot_reuse_or_create(self):
        self.data.pop("dependenciesComplete")
        self.spec.write_text(json.dumps(self.data), encoding="utf-8")
        self.rejected("dependenciesComplete:true")
        self.assertFalse(self.output.exists())

    def test_source_change_rejects(self):
        self.fresh()
        self.asset.write_bytes(b"edited source")
        self.rejected("inputs changed")

    def test_declared_dependency_change_rejects(self):
        self.fresh()
        self.dependency.write_bytes(b"different texture")
        self.rejected("inputs changed")

    def test_spec_only_change_rejects(self):
        self.fresh()
        self.spec.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        self.rejected("inputs changed")

    def test_blender_binary_change_rejects(self):
        self.fresh()
        self.executable.write_bytes(b"upgraded executable")
        self.rejected("Blender executable changed")

    def test_adapter_or_vendor_code_change_rejects(self):
        self.fresh()
        original = q.sha256
        paths = [SCRIPTS / "quality_cli.py", SCRIPTS / "animkit" / "common.py", q.PLUGIN / q.TOOLS["inspect"][0]]
        for target in paths:
            with self.subTest(path=target), patch.object(q, "sha256", side_effect=lambda p: "changed" if Path(p) == target else original(p)):
                self.rejected("(adapter|upstream) changed")

    def test_payload_corruption_or_missing_file_rejects(self):
        self.fresh()
        image = self.report.parent / "evidence.png"
        image.write_bytes(b"corrupt")
        self.rejected("payload inventory or content changed")
        image.unlink()
        self.rejected("payload inventory or content changed")

    def test_extra_payload_file_rejects(self):
        self.fresh()
        (self.report.parent / "unexpected.txt").write_text("injected")
        self.rejected("payload inventory or content changed")

    def test_log_corruption_rejects(self):
        self.fresh()
        (self.output / "blender.log").write_text("corrupt")
        self.rejected("Blender log changed")

    def test_incomplete_and_legacy_manifests_are_not_hits(self):
        self.fresh()
        saved = json.loads(self.manifest.read_text())
        for mutation in ({"status": "running"}, {"status": "timeout", "error": "timed out"}, {"reuseSchemaVersion": 0}, {"executionUnchanged": False}, {"inputsAfter": []}):
            with self.subTest(mutation=mutation):
                self.manifest.write_text(json.dumps(saved | mutation))
                self.rejected()

    def test_empty_or_malformed_manifest_is_not_a_hit(self):
        self.output.mkdir()
        self.rejected()
        self.manifest.write_text("not JSON")
        self.rejected()

    def test_failed_first_run_error_is_retained(self):
        self.process.side_effect = lambda argv, **kwargs: subprocess.CompletedProcess(argv, 17)
        result = q.run_tool("inspect", self.spec)
        self.assertEqual(result["status"], "failed")
        self.assertIn("Blender exited 17", result["error"])
        self.rejected("prior run")

    def test_cli_flag_calls_verified_reuse(self):
        self.fresh()
        self.process.reset_mock()
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = quality_cli.main(["run", "inspect", "--spec", str(self.spec), "--reuse"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stream.getvalue())["reused"])
        self.process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
