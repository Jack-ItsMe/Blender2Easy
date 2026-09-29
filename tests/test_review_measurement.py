"""Saved measurements use the same units as the procedural viewport."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / "skills" / "blender2easy"
sys.path.insert(0, str(ROOT / "scripts"))
from animkit import review
from animkit.common import read_json, write_json


class MeasurementUnitsTests(unittest.TestCase):
    def test_saved_receipt_converts_declared_units_and_is_idempotent(self):
        for units, expected in (("m", .025), ("cm", 2.5), ("mm", 25)):
            with self.subTest(units=units), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "project.json"
                project = read_json(ROOT / "assets/templates/box.json")
                project["units"] = units
                write_json(path, project)
                spec = {
                    "title": "Measure", "question": "Check edge", "stage": "motion",
                    "segments": [{"id": "open", "title": "Open", "source_range": [1, 48]}],
                    "focus": {"shot_id": "opening", "segment_id": "open", "object_ids": ["lid"],
                              "source_frame": 38, "source_range": [1, 48], "camera_id": "hero"},
                    "controls": [], "inspection": {"tools": ["measure"], "object_ids": ["lid"]},
                }
                request = review.create_request(path, spec, "units-test")["request"]
                annotation = {"source_frame": 38, "points": [
                    {"object_id": "lid", "local": [0, 0, 0], "world": [0, 0, 0]},
                    {"object_id": "lid", "local": [.025, 0, 0], "world": [.025, 0, 0]},
                ]}
                args = (path, request["id"], request["revision"], {}, "confirm", "", annotation)
                response = review.submit_review(*args)["response"]
                measure = response["annotation"]["measurement"]
                self.assertEqual(measure["units"], "m")
                self.assertEqual(measure["display_units"], units)
                self.assertAlmostEqual(measure["display_distance"], expected)
                self.assertFalse(measure["verified_geometry"])
                self.assertEqual(review.submit_review(*args)["response"]["digest"], response["digest"])
                self.assertNotIn("measurement", annotation)

    def test_unknown_preview_mapping_stays_uncalibrated(self):
        request = {"focus": {"source_range": [1, 48], "object_ids": ["lid"]},
                   "inspection": {"tools": ["measure"], "object_ids": ["lid"]}}
        result = review._annotation({"source_frame": 38, "points": [
            {"object_id": "lid", "local": [0, 0, 0], "world": [0, 0, 0]},
            {"object_id": "lid", "local": [0, 0, 1], "world": [0, 0, 1]},
        ]}, request, {"lid": {}})
        self.assertEqual(result["measurement"]["units"], "preview_world_units")
        self.assertFalse(result["measurement"]["verified_geometry"])


if __name__ == "__main__":
    unittest.main()
