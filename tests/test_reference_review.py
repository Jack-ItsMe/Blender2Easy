"""Reference evidence freezes image identity without expanding project edits."""
import base64
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1] / "skills" / "blender2easy"
sys.path.insert(0, str(ROOT / "scripts"))
from animkit import review
from animkit import __version__
from animkit.common import digest, read_json, sha256, write_json

loader = importlib.util.spec_from_file_location("reference_review_server", ROOT / "editor/server.py")
server = importlib.util.module_from_spec(loader)
loader.loader.exec_module(server)

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jFmkAAAAASUVORK5CYII=")


class ReferenceReviewFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "project.json"
        self.raw = read_json(ROOT / "assets/templates/box.json")
        write_json(self.path, self.raw)
        self.image = self.path.parent / "reference.png"
        self.image.write_bytes(PNG)
        self.spec = {
            "title": "Reference check", "question": "Does the lid match?", "stage": "motion",
            "thread_id": "reference-test-task",
            "segments": [{"id": "open", "title": "Open", "source_range": [6, 38]}],
            "focus": {"shot_id": "opening", "segment_id": "open", "object_ids": ["hinge", "lid"],
                      "source_frame": 38, "source_range": [6, 48], "camera_id": "hero"},
            "controls": [{"id": "angle", "label": "Angle", "kind": "number", "min": 60, "max": 120,
                          "step": 1, "value": 108,
                          "bindings": [{"path": "/scene/animation/0/keys/2/value/0", "scale": -1},
                                       {"path": "/scene/animation/0/keys/3/value/0", "scale": -1}]}],
            "evidence": {"references": [{"id": "ref-open", "title": "Open reference", "path": "reference.png"}],
                         "checkpoints": [{"id": "open-check", "title": "Lid open", "source_frame": 38,
                                          "camera_id": "detail", "reference_id": "ref-open", "object_ids": ["lid"]}]}}

    def tearDown(self):
        self.temp.cleanup()

    def create(self, spec=None):
        self.result = review.create_request(self.path, self.spec if spec is None else spec, "reference-test-task")
        self.request = self.result["request"]
        return self.result

    def preview(self, value=90):
        return review.preview_review(self.path, self.request["id"], self.request["revision"], {"angle": value})

    def submit(self, value=90, decision="confirm", annotation=None):
        return review.submit_review(self.path, self.request["id"], self.request["revision"], {"angle": value},
                                    decision, "Compare the lid edge", annotation)

    def annotation(self):
        return {"object_id": "lid", "source_frame": 38, "reference_id": "ref-open",
                "reference_uv": [0.25, 0.75], "checkpoint_id": "open-check"}

    def assert_rejected(self, spec):
        before = self.path.read_bytes()
        with self.assertRaises(review.ReviewError):
            self.create(spec)
        self.assertEqual(self.path.read_bytes(), before)


class ReferenceReviewTests(ReferenceReviewFixture):
    def test_create_serializes_frozen_metadata_without_mutating_spec(self):
        original = deepcopy(self.spec)
        result = self.create()
        reference = result["request"]["evidence"]["references"][0]
        self.assertEqual(reference, {"id": "ref-open", "title": "Open reference",
                                    "path": str(self.image.resolve()), "sha256": sha256(self.image)})
        self.assertEqual(self.spec, original)
        self.assertEqual(review.get_review(self.path)["request"], result["request"])
        record = read_json(self.path.parent / ".animation/review/requests" / self.request["id"] / "request.json")
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["request"]["evidence"], result["request"]["evidence"])

    def test_references_can_exist_without_checkpoints_and_limits_are_inclusive(self):
        spec = deepcopy(self.spec)
        del spec["evidence"]["checkpoints"]
        self.assertEqual(self.create(spec)["request"]["evidence"]["checkpoints"], [])
        spec["evidence"]["references"] = [dict(self.spec["evidence"]["references"][0], id=f"ref-{i}") for i in range(6)]
        spec["evidence"]["checkpoints"] = [dict(self.spec["evidence"]["checkpoints"][0], id=f"check-{i}",
                                               reference_id=f"ref-{i % 6}") for i in range(12)]
        self.assertEqual(len(self.create(spec)["request"]["evidence"]["checkpoints"]), 12)
        for key in ("references", "checkpoints"):
            invalid = deepcopy(spec)
            invalid["evidence"][key].append(dict(invalid["evidence"][key][0], id="overflow"))
            self.assert_rejected(invalid)

    def test_invalid_reference_paths_and_content_are_rejected(self):
        for suffix, content in (("html", b"<html>unsafe</html>"), ("svg", b"<svg/>"),
                                ("mp4", b"movie"), ("png", b"<html>disguised</html>")):
            image = self.path.parent / ("bad." + suffix)
            image.write_bytes(content)
            spec = deepcopy(self.spec)
            spec["evidence"]["references"][0]["path"] = str(image)
            with self.subTest(path=image):
                self.assert_rejected(spec)
        for path in ("https://example.test/image.png", "data:image/png;base64,abc", "file:///reference.png", "missing.jpg"):
            spec = deepcopy(self.spec)
            spec["evidence"]["references"][0]["path"] = path
            with self.subTest(path=path):
                self.assert_rejected(spec)

    def test_reference_and_checkpoint_fields_are_strict(self):
        for section in ("references", "checkpoints"):
            for field, value in (("id", "../bad"), ("id", None), ("title", ""), ("path_to_write", "evil.json")):
                spec = deepcopy(self.spec)
                spec["evidence"][section][0][field] = value
                with self.subTest(section=section, field=field):
                    self.assert_rejected(spec)
            spec = deepcopy(self.spec)
            spec["evidence"][section].append(deepcopy(spec["evidence"][section][0]))
            self.assert_rejected(spec)
        for evidence in (None, [], {}, {"references": "reference.png"}, {"references": [], "checkpoints": {}},
                         {"references": [], "script": "run"}):
            spec = deepcopy(self.spec)
            spec["evidence"] = evidence
            self.assert_rejected(spec)
        spec = deepcopy(self.spec)
        spec["evidence"]["references"][0]["sha256"] = "browser-supplied-hash"
        self.assert_rejected(spec)

    def test_checkpoint_locations_must_be_in_frozen_scope(self):
        for field, value in (("source_frame", 5), ("source_frame", 49), ("source_frame", 38.0),
                             ("source_frame", True), ("camera_id", "unknown"), ("camera_id", []),
                             ("reference_id", "unknown"), ("reference_id", []),
                             ("object_ids", ["floor"]), ("object_ids", ["lid", "lid"]),
                             ("object_ids", "lid"), ("object_ids", [None])):
            spec = deepcopy(self.spec)
            spec["evidence"]["checkpoints"][0][field] = value
            with self.subTest(field=field, value=value):
                self.assert_rejected(spec)
        for frame in (6, 48):
            spec = deepcopy(self.spec)
            spec["evidence"]["checkpoints"][0]["source_frame"] = frame
            del spec["evidence"]["checkpoints"][0]["object_ids"]
            self.create(spec)

    def test_changed_reference_blocks_preview_submit_and_apply(self):
        self.create()
        original = self.path.read_bytes()
        self.image.write_bytes(PNG + b"replacement")
        for operation in (self.preview, self.submit):
            with self.assertRaisesRegex(review.ReviewError, "reference changed"):
                operation()
        self.image.write_bytes(PNG)
        submitted = self.submit(annotation=self.annotation())
        self.image.write_bytes(PNG + b"replacement")
        with self.assertRaisesRegex(review.ReviewError, "reference changed"):
            review.apply_review(self.path, self.request["id"], submitted["response"]["digest"])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(review.get_review(self.path)["status"], "submitted")

    def test_missing_reference_blocks_preview(self):
        self.create()
        self.image.unlink()
        with self.assertRaisesRegex(review.ReviewError, "reference changed"):
            self.preview()

    def test_annotation_rejects_unknown_ids_mismatch_and_invalid_uv(self):
        self.create()
        cases = [{"reference_id": "unknown"}, {"reference_id": []}, {"checkpoint_id": "unknown", "source_frame": 38},
                 {"checkpoint_id": []}, {"checkpoint_id": "open-check"},
                 {"checkpoint_id": "open-check", "source_frame": 37},
                 {"reference_uv": [0.2, 0.3]}, {"object_id": "unknown"},
                 {"source_frame": 99}, {"reference_path": str(self.image)}]
        for uv in ([0.1], [0, 1, 0], [-0.1, 0], [0, 1.1], [float("nan"), 0], [0, float("inf")],
                   [True, 0], ["0.1", 0], {"u": 0.1, "v": 0.2}):
            cases.append({"reference_id": "ref-open", "reference_uv": uv})
        for annotation in cases:
            with self.subTest(annotation=annotation), self.assertRaises(review.ReviewError):
                self.submit(annotation=annotation)
        self.assertEqual(review.get_review(self.path)["status"], "pending")
        spec = deepcopy(self.spec)
        spec["evidence"]["references"].append(dict(spec["evidence"]["references"][0], id="another-ref"))
        self.create(spec)
        with self.assertRaisesRegex(review.ReviewError, "does not match"):
            self.submit(annotation={"checkpoint_id": "open-check", "source_frame": 38, "reference_id": "another-ref"})

    def test_revise_preserves_exact_annotation_and_cannot_apply(self):
        self.create()
        before = self.path.read_bytes()
        annotation = self.annotation()
        submitted = self.submit(decision="revise", annotation=annotation)
        self.assertEqual(submitted["response"]["annotation"], annotation)
        self.assertEqual(review.get_review(self.path)["response"], submitted["response"])
        self.assertEqual(self.submit(decision="revise", annotation=annotation)["response"]["digest"], submitted["response"]["digest"])
        with self.assertRaises(review.ReviewError):
            review.apply_review(self.path, self.request["id"], submitted["response"]["digest"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_confirm_applies_only_bound_fields_and_defaults_preserve_bytes(self):
        before = self.path.read_bytes()
        self.create()
        self.preview()
        submitted = self.submit(annotation=self.annotation())
        self.assertEqual(self.path.read_bytes(), before)
        result = review.apply_review(self.path, self.request["id"], submitted["response"]["digest"])
        expected = deepcopy(self.raw)
        for key in (2, 3):
            expected["scene"]["animation"][0]["keys"][key]["value"][0] = -90
        self.assertEqual(read_json(self.path), expected)
        self.assertEqual(len(result["changes"]), 2)
        write_json(self.path, self.raw)
        self.create()
        submitted = self.submit(value=108, annotation={"reference_id": "ref-open", "reference_uv": [0, 1]})
        review.apply_review(self.path, self.request["id"], submitted["response"]["digest"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_legacy_specs_and_neighbor_object_annotation_remain_compatible(self):
        del self.spec["evidence"]
        result = self.create()
        self.assertNotIn("evidence", result["request"])
        # A feedback location does not authorize any new field bindings.
        annotation = {"object_id": "floor", "source_frame": 38, "segment_id": "open", "shot_id": "opening"}
        self.assertEqual(self.submit(annotation=annotation)["response"]["annotation"], annotation)

    def test_visual_only_reviews_allow_feedback_at_all_stages_without_project_writes(self):
        before = self.path.read_bytes()
        for stage in ("model", "motion", "camera", "delivery"):
            with self.subTest(stage=stage):
                spec = deepcopy(self.spec)
                spec.update(stage=stage, controls=[])
                self.create(spec)
                candidate = review.preview_review(self.path, self.request["id"], self.request["revision"], {})
                self.assertEqual(candidate["values"], {})
                self.assertEqual(candidate["changes"], [])
                with self.assertRaises(review.ReviewError):
                    review.preview_review(self.path, self.request["id"], self.request["revision"], {"angle": 90})
                result = review.submit_review(self.path, self.request["id"], self.request["revision"], {},
                                              "confirm", "", self.annotation())
                applied = review.apply_review(self.path, self.request["id"], result["response"]["digest"])
                self.assertEqual(applied["changes"], [])
                self.assertEqual(self.path.read_bytes(), before)
                self.create(spec)
                result = review.submit_review(self.path, self.request["id"], self.request["revision"], {},
                                              "revise", "The hinge needs remodeling", self.annotation())
                self.assertEqual(result["response"]["annotation"], self.annotation())
                with self.assertRaises(review.ReviewError):
                    review.apply_review(self.path, self.request["id"], result["response"]["digest"])
                self.assertEqual(self.path.read_bytes(), before)

    def test_identity_revision_digest_and_task_checks_are_unchanged(self):
        self.create()
        with self.assertRaises(review.ReviewError):
            review.preview_review(self.path, "review-other", self.request["revision"], {"angle": 90})
        with self.assertRaises(review.ReviewError):
            review.preview_review(self.path, self.request["id"], "wrong", {"angle": 90})
        with self.assertRaises(review.ReviewError):
            review.create_request(self.path, self.spec, "different-task")
        submitted = self.submit(annotation=self.annotation())
        with self.assertRaises(review.ReviewError):
            review.apply_review(self.path, self.request["id"], "wrong-digest")
        response_path = self.path.parent / ".animation/review/requests" / self.request["id"] / "response.json"
        response = read_json(response_path)
        response["annotation"]["reference_uv"] = [0.9, 0.9]
        write_json(response_path, response)
        with self.assertRaisesRegex(review.ReviewError, "digest mismatch"):
            review.apply_review(self.path, self.request["id"], submitted["response"]["digest"])
        response["thread_id"] = "different-task"
        response["digest"] = digest({key: value for key, value in response.items() if key != "digest"})
        write_json(response_path, response)
        with self.assertRaisesRegex(review.ReviewError, "different review, project, or agent task"):
            review.get_review(self.path)


class ReferenceHTTPTests(ReferenceReviewFixture):
    """Exercise public asset registration and route protections on an ephemeral port."""

    def setUp(self):
        super().setUp()
        self.create()
        self.editor = server.Editor(self.path.parent / "editor-state", self.path)
        self.http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.http.editor = self.editor
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.http.server_port}"

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        super().tearDown()

    def call(self, route, data=None, headers=None):
        request = urllib.request.Request(self.base + route, data=None if data is None else json.dumps(data).encode(),
                  headers={"Content-Type": "application/json", "X-Editor-Token": self.editor.token, **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def payload(self):
        return {"path": str(self.path), "request_id": self.request["id"], "revision": self.request["revision"],
                "values": {"angle": 90}, "decision": "revise", "note": "Lid edge", "annotation": self.annotation()}

    def test_reference_urls_serve_frozen_images_with_same_local_asset_mechanism(self):
        status, result = self.call("/api/review")
        self.assertEqual(status, 200)
        url = result["review"]["reference_urls"]["ref-open"]
        self.assertTrue(url.startswith("/artifact/"))
        self.assertNotIn(str(self.image), url)
        self.assertEqual(self.call("/api/review")[1]["review"]["reference_urls"]["ref-open"], url)
        self.image.write_bytes(PNG + b"replacement")
        self.assertEqual(self.call("/api/review")[0], 409)
        self.assertEqual(self.call("/api/review/submit", self.payload())[0], 409)
        with urllib.request.urlopen(self.base + url, timeout=5) as response:
            self.assertEqual(response.read(), PNG)
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.call("/artifact/not-registered")[0], 404)

    def test_reference_annotation_posts_without_project_write_and_routes_remain_scoped(self):
        original = self.path.read_bytes()
        status, result = self.call("/api/review/submit", self.payload())
        self.assertEqual(status, 200)
        self.assertEqual(result["review"]["response"]["annotation"], self.annotation())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.call("/api/review/submit", self.payload() | {"project": {}})[0], 400)
        self.assertEqual(self.call("/api/save", {"path": str(self.path), "project": {}})[0], 403)
        self.assertEqual(self.call("/api/review/submit", self.payload(), {"Origin": "https://other.test"})[0], 403)
        self.assertEqual(self.call("/api/review/submit", self.payload(), {"X-Editor-Token": "wrong"})[0], 403)

    def test_legacy_review_public_mapping_is_empty(self):
        del self.spec["evidence"]
        self.create()
        self.assertEqual(self.call("/api/review")[1]["review"]["reference_urls"], {})
        self.assertEqual(self.call("/api/session")[1]["version"], __version__)
        self.assertEqual(self.call("/api/health")[1]["version"], __version__)


if __name__ == "__main__":
    unittest.main()
