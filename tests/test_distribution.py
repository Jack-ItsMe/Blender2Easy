"""Verify local assets and preserved third-party provenance in the shipped skill."""
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1] / "skills" / "blender2easy"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DistributionTests(unittest.TestCase):
    def test_font_manifest_and_local_stylesheet_are_complete(self):
        fonts = ROOT / "editor/web/fonts"
        manifest = json.loads((fonts / "manifest.json").read_text(encoding="utf-8"))
        paths = [item["file"] for item in manifest]
        self.assertEqual(len(paths), len(set(paths)), "Duplicate font manifest paths")
        self.assertEqual(set(paths), {p.relative_to(fonts).as_posix() for p in fonts.rglob("*.woff2")})
        for item in manifest:
            with self.subTest(file=item["file"]):
                path = (fonts / item["file"]).resolve()
                self.assertTrue(path.is_relative_to(fonts.resolve()))
                self.assertEqual(path.stat().st_size, item["bytes"])
                self.assertEqual(sha(path), item["sha256"])
                self.assertEqual(path.read_bytes()[:4], b"wOF2")
                self.assertTrue(item["url"].startswith("https://fonts.gstatic.com/"))
        urls = re.findall(r"url\(([^)]+)\)", (fonts / "fonts.css").read_text(encoding="utf-8"))
        self.assertFalse(any("://" in url for url in urls))
        self.assertEqual({url.removeprefix("./") for url in urls}, set(paths))
        for family in ("Inter", "NotoSansSC", "NotoSansTC"):
            license_text = (fonts / f"{family}-OFL.txt").read_text(encoding="utf-8")
            self.assertIn("Copyright", license_text)
            self.assertIn("SIL OPEN FONT LICENSE Version 1.1", license_text)
            self.assertIn("DISCLAIMER", license_text)

    def test_font_ranges_cover_current_chinese_messages(self):
        css = (ROOT / "editor/web/fonts/fonts.css").read_text(encoding="utf-8")
        coverage = {}
        for block in re.findall(r"@font-face\s*\{([^}]+)\}", css):
            family = re.search(r"font-family:\s*'([^']+)'", block).group(1)
            points = coverage.setdefault(family, set())
            for entry in re.search(r"unicode-range:\s*([^;]+)", block).group(1).split(","):
                bounds = entry.strip().removeprefix("U+").split("-")
                points.update(range(int(bounds[0], 16), int(bounds[-1], 16) + 1))
        messages = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "editor/web/locales").glob("*.js"))
        cjk = {ord(c) for c in messages if "\u3400" <= c <= "\u9fff"}
        for family in ("Noto Sans SC", "Noto Sans TC"):
            self.assertFalse(cjk - coverage[family], f"Uncovered CJK codepoints in {family}")

    def test_vendored_sources_match_recorded_provenance(self):
        vendor = ROOT / "vendor/bas"
        provenance = json.loads((vendor / "PROVENANCE.json").read_text(encoding="utf-8"))
        changes = {item["path"]: item["vendoredSha256"] for item in provenance["localChanges"]}
        records = [(item["path"], changes.get(item["path"], item["upstreamSha256"]))
                   for item in provenance["sourceFiles"]]
        records += [(item["path"], item["vendoredSha256"]) for item in provenance["localChanges"]]
        records += [(item["path"], item["sha256"]) for item in provenance.get("localFiles", [])]
        for relative, digest in records:
            with self.subTest(file=relative):
                path = (vendor / relative).resolve()
                self.assertTrue(path.is_relative_to(vendor.resolve()))
                self.assertEqual(sha(path), digest)

    def test_maintained_document_links_resolve(self):
        vendor = ROOT / "vendor/bas"
        plugin = vendor / "plugins/blender-agent-studio"
        docs = [ROOT / "SKILL.md", ROOT / "THIRD_PARTY_NOTICES.md", *ROOT.glob("references/*.md"),
                vendor / "SKILL.md", *plugin.glob("skills/*/SKILL.md"),
                *plugin.rglob("astra-workflow.md"), plugin / "references/execution.md",
                plugin / "skills/blender-modeling-workflow/references/staged-quality-workflow.md"]
        for doc in docs:
            for target in re.findall(r"\]\(([^)]+)\)", doc.read_text(encoding="utf-8")):
                if "://" in target or target.startswith("#"):
                    continue
                with self.subTest(document=str(doc.relative_to(ROOT)), target=target):
                    self.assertTrue((doc.parent / target.split("#")[0]).exists())


if __name__ == "__main__":
    unittest.main()
