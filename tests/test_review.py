"""Security and lifecycle regressions for agent-scoped animation review."""
from copy import deepcopy
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[1] / "skills" / "blender2easy"
sys.path.insert(0, str(ROOT / "scripts"))
from animkit import review
from animkit.common import read_json, sha256, write_json


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # The injected write hook compares the canonical path used by review.
        self.path = Path(self.temp.name).resolve() / "project.json"
        self.raw = read_json(ROOT / "assets/templates/box.json")
        write_json(self.path, self.raw)
        self.spec = {
            "title": "确认开盖", "question": "角度是否合适？", "context": "只调整开盖动作。",
            "stage": "motion", "thread_id": "test-thread",
            "segments": [{"id": "intro", "title": "外观", "source_range": [1, 6]},
                         {"id": "open", "title": "开盖", "source_range": [6, 38]},
                         {"id": "inside", "title": "内部", "source_range": [38, 48]}],
            "focus": {"shot_id": "opening", "segment_id": "open", "object_ids": ["hinge", "lid"],
                      "source_frame": 38, "source_range": [6, 48], "camera_id": "hero"},
            "controls": [{"id": "opening", "label": "打开角度", "kind": "number", "unit": "°",
                          "min": 60, "max": 120, "step": 1, "value": 108,
                          "bindings": [{"path": "/scene/animation/0/keys/2/value/0", "scale": -1},
                                       {"path": "/scene/animation/0/keys/3/value/0", "scale": -1}]}]}

    def tearDown(self):
        self.temp.cleanup()

    def create(self, spec=None):
        self.request = review.create_request(self.path, spec or self.spec, "test-thread")
        self.ident = self.request["request"]["id"]
        self.revision = self.request["request"]["revision"]
        return self.request

    def preview(self, values=None, **kwargs):
        return review.preview_review(self.path, kwargs.get("request_id", self.ident),
                                     kwargs.get("revision", self.revision), values or {"opening": 90})

    def submit(self, values=None, decision="confirm", note="", **kwargs):
        return review.submit_review(self.path, self.ident, self.revision, values or {"opening": 90},
                                    decision, note, kwargs.get("annotation"))

    def test_scoped_preview_does_not_write_and_apply_only_changes_declared_leaves(self):
        original_bytes = self.path.read_bytes()
        self.create()
        candidate = self.preview()
        self.assertEqual(self.path.read_bytes(), original_bytes)
        self.assertEqual(len(candidate["changes"]), 2)
        submitted = self.submit(annotation={"object_id": "lid", "source_frame": 38})
        self.assertEqual(self.path.read_bytes(), original_bytes)
        result = review.apply_review(self.path, self.ident, submitted["response"]["digest"])
        expected = deepcopy(self.raw)
        expected["scene"]["animation"][0]["keys"][2]["value"][0] = -90
        expected["scene"]["animation"][0]["keys"][3]["value"][0] = -90
        self.assertEqual(read_json(self.path), expected)
        self.assertEqual(result["status"], "applied")
        archive = self.path.parent / ".animation/revisions" / (self.revision + ".json")
        self.assertEqual(archive.read_bytes(), original_bytes)
        self.assertEqual(submitted["response"]["thread_id"], "test-thread")
        self.assertEqual(submitted["response"]["focus"]["segment_id"], "open")

    def test_rejects_out_of_range_nonfinite_step_and_extra_controls(self):
        self.create()
        for value in (59, 121, 90.5, True, float("nan"), float("inf"), "90"):
            with self.subTest(value=value), self.assertRaises(review.ReviewError):
                self.preview({"opening": value})
        for values in ({"opening": 90, "path": "/source/blend"}, {}, {"other": 90}):
            with self.subTest(values=values), self.assertRaises(review.ReviewError):
                review.preview_review(self.path, self.ident, self.revision, values)

    def test_rejects_extra_spec_control_and_binding_fields(self):
        for target, field in (("spec", "project"), ("control", "onChange"), ("binding", "script")):
            spec = deepcopy(self.spec)
            item = spec if target == "spec" else spec["controls"][0] if target == "control" else spec["controls"][0]["bindings"][0]
            item[field] = "arbitrary"
            with self.subTest(target=target), self.assertRaises(review.ReviewError):
                self.create(spec)

    def test_structural_and_asset_paths_are_never_bindable(self):
        for pointer in ("/scene/objects/0", "/scene/objects", "/scene/objects/8/parent",
                        "/scene/objects/8/id", "/scene/objects/8/type", "/scene/animation/0/target",
                        "/scene/animation/0/keys", "/assets", "/units", "/schema_version"):
            spec = deepcopy(self.spec)
            spec["stage"] = "model"
            spec["controls"][0]["bindings"] = [{"path": pointer}]
            with self.subTest(pointer=pointer), self.assertRaises(review.ReviewError):
                self.create(spec)

    def test_scope_is_stage_specific(self):
        spec = deepcopy(self.spec)
        spec["controls"][0]["bindings"] = [{"path": "/scene/objects/1/dimensions/0"}]
        with self.assertRaises(review.ReviewError):
            self.create(spec)
        spec["stage"] = "model"
        spec["controls"][0].update(value=2.4, min=1, max=4, step=.1)
        self.create(spec)
        self.assertEqual(self.preview({"opening": 3})["project"]["scene"]["objects"][1]["dimensions"][0], 3)

    def test_wrong_default_duplicate_controls_and_overlapping_paths(self):
        spec = deepcopy(self.spec)
        spec["controls"][0]["value"] = 90
        with self.assertRaises(review.ReviewError):
            self.create(spec)
        spec = deepcopy(self.spec)
        spec["controls"].append(deepcopy(spec["controls"][0]))
        with self.assertRaises(review.ReviewError):
            self.create(spec)
        spec["controls"][1]["id"] = "second"
        with self.assertRaises(review.ReviewError):
            self.create(spec)
        spec = deepcopy(self.spec)
        spec["controls"][0]["bindings"].append(deepcopy(spec["controls"][0]["bindings"][0]))
        with self.assertRaises(review.ReviewError):
            self.create(spec)

    def test_color_default_preserves_full_precision_and_alpha(self):
        spec = deepcopy(self.spec)
        spec["stage"] = "model"
        spec["controls"] = [{"id": "paint", "label": "颜色", "kind": "color", "value": "#1f6687",
                             "bindings": [{"path": "/scene/materials/0/color"}]}]
        self.create(spec)
        default = self.preview({"paint": "#1f6687"})
        self.assertEqual(default["changes"], [])
        self.assertEqual(default["project"]["scene"]["materials"][0]["color"], [0.12, 0.4, 0.53, 1])
        changed = self.preview({"paint": "#FF0000"})
        self.assertEqual(changed["project"]["scene"]["materials"][0]["color"], [1, 0, 0, 1])
        self.assertEqual(changed["values"]["paint"], "#ff0000")

    def test_choice_cannot_replace_objects_and_vector_output_validates_schema(self):
        spec = deepcopy(self.spec)
        spec["stage"] = "delivery"
        spec["controls"] = [{"id": "format", "label": "画幅", "kind": "choice", "value": "wide",
                             "options": [{"value": "wide", "label": "横屏"}, {"value": "tall", "label": "竖屏"}],
                             "bindings": [{"path": "/render/resolution", "choices": {"wide": [640, 360], "tall": [360, 640]}}]}]
        self.create(spec)
        self.assertEqual(self.preview({"format": "tall"})["project"]["render"]["resolution"], [360, 640])
        spec["controls"][0]["bindings"][0]["choices"]["tall"] = [361, 640]
        self.create(spec)
        with self.assertRaises(review.ReviewError):
            self.preview({"format": "tall"})

    def test_integer_frame_binding_casts_integral_calculation(self):
        spec = deepcopy(self.spec)
        spec["controls"] = [{"id": "seconds", "label": "时长", "kind": "number", "unit": "s",
                             "value": 2, "min": 1, "max": 4, "step": .25,
                             "bindings": [{"path": "/shots/0/timing/0/frames", "scale": 24}]}]
        self.create(spec)
        candidate = self.preview({"seconds": 2.5})
        self.assertEqual(candidate["project"]["shots"][0]["timing"][0]["frames"], 60)
        self.assertIs(type(candidate["project"]["shots"][0]["timing"][0]["frames"]), int)
        spec["controls"][0]["step"] = .01
        self.create(spec)
        with self.assertRaises(review.ReviewError):
            self.preview({"seconds": 2.01})

    def test_integer_written_coordinate_can_accept_fraction(self):
        spec = deepcopy(self.spec)
        spec["stage"] = "model"
        spec["controls"] = [{"id": "height", "label": "位置", "kind": "number", "value": 0,
                             "min": -1, "max": 1, "step": .1,
                             "bindings": [{"path": "/scene/objects/1/location/0"}]}]
        self.create(spec)
        self.assertEqual(self.preview({"height": .5})["project"]["scene"]["objects"][1]["location"][0], .5)

    def test_full_candidate_schema_rejects_unsorted_keyframe(self):
        spec = deepcopy(self.spec)
        spec["controls"] = [{"id": "frame", "label": "帧", "kind": "number", "value": 38,
                             "min": 1, "max": 48, "step": 1,
                             "bindings": [{"path": "/scene/animation/0/keys/2/frame"}]}]
        self.create(spec)
        with self.assertRaises(review.ReviewError):
            self.preview({"frame": 3})
        self.assertEqual(sha256(self.path), self.revision)

    def test_invalid_focus_references_and_source_range(self):
        for key, value in (("object_ids", ["unknown"]), ("camera_id", "unknown"), ("shot_id", "unknown"),
                           ("segment_id", "unknown"), ("source_frame", 999), ("source_range", [1, 100])):
            spec = deepcopy(self.spec)
            spec["focus"][key] = value
            with self.subTest(key=key), self.assertRaises(review.ReviewError):
                self.create(spec)

    def test_object_labels_are_agent_authored_and_reference_real_objects(self):
        spec = deepcopy(self.spec)
        spec["focus"]["object_labels"] = {"lid": "盒盖", "hinge": "开合关节"}
        self.create(spec)
        self.assertEqual(self.request["request"]["focus"]["object_labels"], spec["focus"]["object_labels"])
        for labels in ({"missing": "名字"}, {"lid": "x" * 81}, {"lid": 12}, ["盒盖"]):
            bad = deepcopy(spec)
            bad["focus"]["object_labels"] = labels
            with self.subTest(labels=labels), self.assertRaises(review.ReviewError):
                self.create(bad)

    def test_old_request_and_wrong_revision_are_rejected(self):
        self.create()
        old_id, old_revision = self.ident, self.revision
        self.create()
        with self.assertRaises(review.ReviewError) as error:
            self.preview(request_id=old_id)
        self.assertEqual(error.exception.status, 409)
        with self.assertRaises(review.ReviewError):
            self.preview(revision="bad-revision")
        prior = review.wait_review(self.path, old_id, timeout=0)
        self.assertEqual(prior["status"], "superseded")
        self.assertEqual(old_revision, self.revision)

    def test_project_disk_edits_reject_preview_submit_and_apply(self):
        self.create()
        submitted = self.submit()
        changed = deepcopy(self.raw)
        changed["render"]["samples"] = 20
        write_json(self.path, changed)
        changed_revision = sha256(self.path)
        with self.assertRaises(review.ReviewError):
            self.preview()
        # A duplicate submit is acknowledged without mutating the project;
        # changed feedback cannot replace the immutable response.
        self.assertEqual(self.submit()["response"]["digest"], submitted["response"]["digest"])
        with self.assertRaises(review.ReviewError):
            self.submit({"opening": 91})
        with self.assertRaises(review.ReviewError):
            review.apply_review(self.path, self.ident, submitted["response"]["digest"])
        self.assertEqual(sha256(self.path), changed_revision)

    def test_unsubmitted_stale_revision_rejected(self):
        self.create()
        self.path.write_text(self.path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaises(review.ReviewError):
            self.submit()

    def test_revision_change_during_validation_rejected(self):
        self.create()
        original = review._normalize
        def mutate(raw, path):
            result = original(raw, path)
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            return result
        with patch.object(review, "_normalize", side_effect=mutate), self.assertRaises(review.ReviewError):
            self.preview()

    def test_revise_requires_note_and_cannot_apply(self):
        self.create()
        with self.assertRaises(review.ReviewError):
            self.submit(decision="revise")
        result = self.submit(decision="revise", note="这里再慢一点", annotation={"source_frame": 20})
        with self.assertRaises(review.ReviewError):
            review.apply_review(self.path, self.ident, result["response"]["digest"])
        self.assertEqual(sha256(self.path), self.revision)

    def test_double_submit_and_apply_are_idempotent(self):
        self.create()
        first, second = self.submit(), self.submit()
        self.assertEqual(first["response"], second["response"])
        with self.assertRaises(review.ReviewError):
            self.submit(note="different")
        applied = review.apply_review(self.path, self.ident, first["response"]["digest"])
        repeated = review.apply_review(self.path, self.ident, first["response"]["digest"])
        self.assertEqual(repeated["status"], "already-applied")
        self.assertEqual(applied["revision"], repeated["revision"])
        self.assertEqual(self.submit()["response"], first["response"])

    def test_apply_requires_exact_digest_and_response_identity(self):
        self.create()
        submitted = self.submit()
        for wrong in (None, "fake"):
            with self.assertRaises(review.ReviewError):
                review.apply_review(self.path, self.ident, wrong)
        location = self.path.parent / ".animation/review/requests" / self.ident / "response.json"
        response = read_json(location)
        response["thread_id"] = "another-task"
        response["digest"] = review.digest({k: v for k, v in response.items() if k != "digest"})
        write_json(location, response)
        with self.assertRaises(review.ReviewError):
            review.get_review(self.path)

    def test_frozen_thread_binding_and_cli_refuses_other_task(self):
        with self.assertRaises(review.ReviewError):
            review.create_request(self.path, self.spec, "another-task")
        self.create()
        process = subprocess.run([sys.executable, str(ROOT / "scripts/review_cli.py"), "wait", str(self.path),
                                  "--request", self.ident, "--timeout", "0", "--thread", "another-task"],
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 2)
        self.assertEqual(json.loads(process.stdout)["code"], 409)

    def test_wait_without_request_pins_checked_thread_before_concurrent_replacement(self):
        import review_cli
        first = self.create()
        other_spec = deepcopy(self.spec)
        other_spec["thread_id"] = "other-thread"
        second = review.create_request(self.path, other_spec, "other-thread")
        next_id = second["request"]["id"]
        review.submit_review(self.path, next_id, self.revision, {"opening": 90}, "confirm")
        # get_review represents the earlier thread-check snapshot. The current
        # pointer changes before wait starts; it must not acknowledge task B.
        with patch.object(review_cli, "get_review", return_value=first), redirect_stdout(io.StringIO()) as output:
            code = review_cli.main(["wait", str(self.path), "--timeout", "0", "--thread", "test-thread"])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "superseded")
        self.assertEqual(result["request"]["id"], self.ident)
        self.assertNotIn("received_at", review.get_review(self.path))

    def test_persistence_survives_process_restart(self):
        self.create()
        submitted = self.submit()
        process = subprocess.run([sys.executable, str(ROOT / "scripts/review_cli.py"), "status", str(self.path)],
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stderr)
        reloaded = json.loads(process.stdout)
        self.assertEqual(reloaded["status"], "submitted")
        self.assertEqual(reloaded["response"]["digest"], submitted["response"]["digest"])
        self.assertNotIn("received_at", reloaded)

    def test_wait_heartbeat_expires_and_receipt_is_honest(self):
        self.create()
        response = {}
        listener = threading.Thread(target=lambda: response.update(review.wait_review(self.path, self.ident, timeout=2)))
        listener.start()
        active = False
        for _ in range(30):
            try:
                if review.get_review(self.path)["agent_listening"]:
                    active = True
                    break
            except review.ReviewError:
                pass
            time.sleep(.02)
        self.assertTrue(active)
        self.submit()
        listener.join(3)
        self.assertFalse(listener.is_alive())
        self.assertEqual(response["status"], "submitted")
        self.assertEqual(response["received_by_thread"], "test-thread")
        self.assertIn("received_at", response["response"])
        self.assertFalse(response["agent_listening"])
        self.assertEqual(sha256(self.path), self.revision)

    def test_timeout_does_not_pretend_agent_received_anything(self):
        self.create()
        result = review.wait_review(self.path, self.ident, timeout=.02)
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["agent_listening"])
        self.assertNotIn("received_at", result)
        with self.assertRaises(review.ReviewError):
            review.wait_review(self.path, self.ident, 61)

    def test_delivery_zero_controls_and_media_freeze(self):
        spec = deepcopy(self.spec)
        spec.update(stage="delivery", controls=[], media={"path": "rendered.mp4"})
        media = self.path.parent / "rendered.mp4"
        media.write_bytes(b"fixture MP4")
        self.create(spec)
        self.assertTrue(self.request["url"].startswith("http://127.0.0.1:8766/preview/delivery?request="))
        result = review.preview_review(self.path, self.ident, self.revision, {})
        self.assertEqual(result["changes"], [])
        media.write_bytes(b"changed output")
        with self.assertRaises(review.ReviewError):
            review.preview_review(self.path, self.ident, self.revision, {})

    def test_confirm_unchanged_does_not_normalize_or_rewrite_file(self):
        self.create()
        result = self.submit({"opening": 108})
        self.assertEqual(result["response"]["changes"], [])
        review.apply_review(self.path, self.ident, result["response"]["digest"])
        self.assertEqual(sha256(self.path), self.revision)

    def test_crash_after_project_write_recovers_without_reapplying(self):
        self.create()
        submitted = self.submit()
        original_write = review.write_json
        def interrupted_write(path, value):
            original_write(path, value)
            if Path(path) == self.path:
                raise RuntimeError("simulated process termination after project replacement")
        with patch.object(review, "write_json", side_effect=interrupted_write), self.assertRaises(review.ReviewError):
            review.apply_review(self.path, self.ident, submitted["response"]["digest"])
        result = review.apply_review(self.path, self.ident, submitted["response"]["digest"])
        self.assertTrue(result["recovered"])
        self.assertEqual(result["status"], "already-applied")

    def test_crash_after_feedback_write_recovers_immutable_submission(self):
        self.create()
        original_write = review.write_json
        def interrupted_write(path, value):
            original_write(path, value)
            if Path(path).name == "response.json":
                raise RuntimeError("simulated process termination after feedback commit")
        with patch.object(review, "write_json", side_effect=interrupted_write), self.assertRaises(review.ReviewError):
            self.submit()
        recovered = review.get_review(self.path)
        self.assertEqual(recovered["status"], "submitted")
        self.assertEqual(self.submit()["response"], recovered["response"])
        self.assertEqual(sha256(self.path), self.revision)

    def test_two_concurrent_submissions_commit_only_one_response(self):
        self.create()
        outcomes = []
        def send(value):
            try:
                outcomes.append(self.submit({"opening": value})["response"]["values"]["opening"])
            except review.ReviewError as exc:
                outcomes.append(exc.status)
        workers = [threading.Thread(target=send, args=(value,)) for value in (90, 91)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(2)
        self.assertEqual(outcomes.count(409), 1)
        self.assertEqual(len(outcomes), 2)
        self.assertIn(review.get_review(self.path)["values"]["opening"], (90, 91))

    def test_native_asset_change_rejected_and_source_path_cannot_bind(self):
        native = self.path.parent / "scene.blend"
        native.write_bytes(b"fixture Blender asset")
        raw = deepcopy(self.raw)
        raw.pop("scene")
        raw["source"] = {"blend": "scene.blend", "overrides": {"objects": [{"id": "lid", "location": [0, 0, 0]}]}}
        write_json(self.path, raw)
        spec = deepcopy(self.spec)
        spec["focus"]["object_ids"] = ["lid"]
        spec["stage"] = "model"
        spec["controls"] = [{"id": "height", "label": "位置", "kind": "number", "value": 0,
                             "min": -1, "max": 1, "step": .1,
                             "bindings": [{"path": "/source/overrides/objects/0/location/2"}]}]
        self.create(spec)
        self.assertEqual(self.preview({"height": .5})["project"]["source"]["overrides"]["objects"][0]["location"][2], .5)
        native.write_bytes(b"external asset changed")
        with self.assertRaises(review.ReviewError):
            self.preview({"height": .5})
        spec["controls"][0]["bindings"] = [{"path": "/source/blend"}]
        with self.assertRaises(review.ReviewError):
            self.create(spec)

    def test_native_import_discovery_supports_focus_without_override(self):
        native = self.path.parent / "scene.blend"
        native.write_bytes(b"fixture Blender asset")
        raw = deepcopy(self.raw)
        raw.pop("scene")
        raw["source"] = {"blend": "scene.blend", "scene": "Scene"}
        write_json(self.path, raw)
        spec = deepcopy(self.spec)
        spec.update(stage="delivery", controls=[])
        spec["focus"]["object_ids"] = ["lid"]
        report = self.path.parent / ".animation/editor/import/native-discovery/fixture/manifest.json"
        data = {"source_sha256": sha256(native), "manifest": {"scene": "Scene", "objects": [{"id": "lid"}], "cameras": [{"id": "hero"}]}}
        write_json(report, data)
        self.create(spec)
        self.assertEqual(self.request["request"]["focus"]["object_ids"], ["lid"])
        data["manifest"]["scene"] = "OtherScene"
        write_json(report, data)
        with self.assertRaises(review.ReviewError):
            self.create(spec)
        data["manifest"]["scene"] = "Scene"
        data["source_sha256"] = "stale"
        write_json(report, data)
        with self.assertRaises(review.ReviewError):
            self.create(spec)

    def test_annotation_does_not_allow_arbitrary_instructions_or_unknown_location(self):
        self.create()
        for annotation in ({"path": "/scene/objects"}, {"object_id": "unknown"}, {"source_frame": 999}, {}):
            with self.subTest(annotation=annotation), self.assertRaises(review.ReviewError):
                self.submit(annotation=annotation)

    def test_close_preserves_feedback_and_blocks_edits(self):
        self.create()
        submitted = self.submit(decision="revise", note="调整节奏")
        closed = review.close_review(self.path, self.ident, "已根据反馈准备下一版")
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["response"], submitted["response"])
        with self.assertRaises(review.ReviewError):
            self.preview()


if __name__ == "__main__":
    unittest.main(verbosity=2)
