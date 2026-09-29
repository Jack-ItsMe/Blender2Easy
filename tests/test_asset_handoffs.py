import json
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1] / "skills" / "blender2easy"
sys.path.insert(0, str(ROOT / "scripts"))
from animkit.asset_tools import prepare_search


class AssetHandoffTests(unittest.TestCase):
    def test_query_is_encoded_in_provider_url_and_remains_a_handoff(self):
        query = "机械 motion & jump/?#"
        mixamo = prepare_search("mixamo", query)
        parsed = urlparse(mixamo["url"])
        self.assertEqual(parsed.netloc, "www.mixamo.com")
        self.assertEqual(parse_qs(parsed.fragment.partition("?")[2])["query"], [query])
        pixabay = prepare_search("pixabay", query)
        self.assertEqual(urlparse(pixabay["url"]).netloc, "pixabay.com")
        self.assertEqual(unquote(urlparse(pixabay["url"]).path.removeprefix("/sound-effects/search/").removesuffix("/")), query)
        for result in (mixamo, pixabay):
            self.assertEqual(result["status"], "browser_required")
            self.assertNotIn("assets", result)

    def test_invalid_provider_and_queries_rejected(self):
        for provider, query in (("unknown", "walk"), ("mixamo", ""), ("pixabay", "x"*201), ("mixamo", "a\0b"), ("pixabay", [])):
            with self.subTest(provider=provider, query=query), self.assertRaises(ValueError):
                prepare_search(provider, query)

    def test_actual_cli_emits_structured_browser_handoff(self):
        result = subprocess.run([sys.executable,"-X","utf8",str(ROOT/"scripts/animation.py"),"assets","search","mixamo","--query","walk & stop"],capture_output=True,text=True,encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["query"], "walk & stop")


if __name__ == "__main__":
    unittest.main()
