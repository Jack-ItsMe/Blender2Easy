from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / "skills" / "blender2easy"
sys.path.insert(0, str(ROOT / "scripts"))
from animkit import review
from animkit.common import read_json, write_json


class SurfaceOriginTests(unittest.TestCase):
    def test_origin_keeps_sampled_parameters_distinct_from_proposed_values(self):
        for variant, expected in (("original", 108), ("candidate", 95), (None, 95)):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/"project.json"
                write_json(path, read_json(ROOT/"assets/templates/box.json"))
                spec={"title":"Surface origin", "question":"Inspect selected surface", "stage":"motion",
                      "segments":[{"id":"open", "title":"Open", "source_range":[1,48]}],
                      "focus":{"shot_id":"opening","segment_id":"open","object_ids":["lid"],
                               "source_frame":38,"source_range":[1,48],"camera_id":"hero"},
                      "controls":[{"id":"angle","label":"Angle","kind":"number","min":60,"max":120,
                                   "step":1,"value":108,"bindings":[{"path":"/scene/animation/0/keys/2/value/0","scale":-1}]}],
                      "inspection":{"tools":["point"],"object_ids":["lid"]}}
                request=review.create_request(path,spec,"origin-test")["request"]
                annotation={"source_frame":38,"points":[{"object_id":"lid","world":[0,0,0],"local":[0,0,0]}]}
                if variant is not None: annotation["preview_variant"]=variant
                args=(path,request["id"],request["revision"],{"angle":95},"confirm","",annotation)
                response=review.submit_review(*args)["response"]
                self.assertEqual(response["annotation"]["sampled_values"],{"angle":expected})
                self.assertEqual(response["values"],{"angle":95})
                self.assertEqual(review.submit_review(*args)["response"]["digest"],response["digest"])
                self.assertNotIn("sampled_values",annotation)

    def test_invalid_origin_and_injected_sampled_parameters_rejected(self):
        request={"focus":{"source_range":[1,48],"object_ids":["lid"]},
                 "inspection":{"tools":["point"],"object_ids":["lid"]}}
        for annotation in ({"preview_variant":"other","source_frame":1},
                           {"preview_variant":"original","source_frame":1},
                           {"sampled_values":{"angle":777},"source_frame":1}):
            with self.subTest(annotation=annotation),self.assertRaises(review.ReviewError):
                review._annotation(annotation,request,{"lid":{}})


if __name__=="__main__": unittest.main()
