"""Conversation locale is frozen in requests and carried by every review link."""
from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
import runpy
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
from urllib.parse import parse_qs, urlsplit
import urllib.request

ROOT = Path(__file__).resolve().parents[1] / "skills" / "blender2easy"
sys.path.insert(0, str(ROOT / "scripts"))
from animkit import review
from animkit import __version__
from animkit.common import read_json, write_json
import review_cli
import review_open

loader = importlib.util.spec_from_file_location("review_language_server", ROOT / "editor/server.py")
server = importlib.util.module_from_spec(loader)
loader.loader.exec_module(server)


class ReviewLanguageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.path = self.folder / "project.json"
        write_json(self.path, read_json(ROOT / "assets/templates/box.json"))
        self.original = self.path.read_bytes()
        self.spec = {
            "title": "检查盖子", "question": "保留我的项目文字", "stage": "motion",
            "segments": [{"id": "open", "title": "打开", "source_range": [1, 48]}],
            "focus": {"shot_id": "opening", "segment_id": "open", "object_ids": ["lid"],
                      "source_frame": 38, "source_range": [1, 48], "camera_id": "hero"},
            "controls": [],
        }

    def tearDown(self):
        self.temp.cleanup()

    def create(self, language="zh-CN"):
        spec = deepcopy(self.spec)
        spec["ui_language"] = language
        return review.create_request(self.path, spec, "language-test")

    def assert_link(self, result, expected, port=8766):
        parsed = urlsplit(result["url"])
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.port, port)
        self.assertEqual(parsed.path, "/preview/motion")
        self.assertEqual(query["request"], [result["request"]["id"]])
        self.assertEqual(query.get("context_lang"), [expected] if expected else None)
        self.assertNotIn("lang", query)

    def test_first_request_freezes_locale_without_rewriting_authored_content(self):
        raw = deepcopy(self.spec)
        raw["ui_language"] = " zh_CN "
        result = review.create_request(self.path, raw, "language-test")
        self.assertEqual(result["request"]["ui_language"], "zh-Hans")
        self.assert_link(result, "zh-Hans")
        self.assertEqual(raw["ui_language"], " zh_CN ")
        self.assertEqual(result["request"]["title"], self.spec["title"])
        self.assertEqual(result["request"]["question"], self.spec["question"])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(review.get_review(self.path)["request"]["ui_language"], "zh-Hans")
        record = read_json(self.folder / ".animation/review/requests" / result["request"]["id"] / "request.json")
        self.assertEqual(record["request"]["ui_language"], "zh-Hans")

    def test_canonical_values_and_reasonable_aliases(self):
        for language, expected in [
            ("en", "en"), ("EN_us", "en"), ("en-GB", "en"),
            ("zh", "zh-Hans"), ("zh-Hans", "zh-Hans"), ("zh-SG", "zh-Hans"),
            ("zh-Hans-CN", "zh-Hans"), ("zh-TW", "zh-Hant"),
            ("zh_HK", "zh-Hant"), ("zh-Hant", "zh-Hant"), ("繁體中文", "zh-Hant"),
        ]:
            with self.subTest(language=language):
                result = self.create(language)
                self.assertEqual(result["request"]["ui_language"], expected)
                self.assert_link(result, expected)

    def test_invalid_locale_cannot_supersede_current_request(self):
        current = self.create()
        for value in (None, "", "auto", "fr", "de-DE", 1, True, [], {},
                      "zh-CN&lang=en", "en/../../x", "zh-" + "x" * 100):
            with self.subTest(value=value), self.assertRaisesRegex(review.ReviewError, "ui_language"):
                self.create(value)
            self.assertEqual(review.get_review(self.path)["request"]["id"], current["request"]["id"])

    def test_legacy_and_explicit_url_override_parameters(self):
        legacy = review.create_request(self.path, self.spec, "language-test")
        self.assertNotIn("ui_language", legacy["request"])
        self.assert_link(legacy, None)
        self.assertEqual(legacy["url"], "http://127.0.0.1:8766/preview/motion?request=" + legacy["request"]["id"])
        result = self.create("zh-TW")
        url = review.review_url(result["request"],
                                "http://127.0.0.1:8775/?lang=en&theme=light&request=stale&context_lang=en")
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query, {"lang": ["en"], "theme": ["light"],
                                "request": [result["request"]["id"]], "context_lang": ["zh-Hant"]})
        self.assertEqual(urlsplit(url).port, 8775)

    def test_cli_spec_and_selected_port(self):
        spec = dict(self.spec, ui_language="zh_TW")
        spec_path = self.folder / "request-spec.json"
        write_json(spec_path, spec)
        output = io.StringIO()
        with redirect_stdout(output):
            status = review_cli.main(["create", str(self.path), "--spec", str(spec_path),
                                      "--thread", "language-test", "--port", "8775"])
        self.assertEqual(status, 0)
        self.assert_link(json.loads(output.getvalue()), "zh-Hant", 8775)

    def test_http_response_and_reopen_use_real_port_and_context(self):
        current = self.create("zh_CN")
        editor = server.Editor(self.folder / "workspace", self.path)
        http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        http.editor = editor
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{http.server_port}"
        try:
            opened = review_open.open_review(self.path, port=http.server_port, browser=False)
            self.assertEqual(opened["url"], review.review_url(current["request"], base))
            with urllib.request.urlopen(base + "/api/review", timeout=5) as response:
                value = json.load(response)
            self.assert_link(value["review"], "zh-Hans", http.server_port)
            payload = {"path": str(self.path), "request_id": current["request"]["id"],
                       "revision": current["request"]["revision"], "values": {},
                       "decision": "confirm"}
            request = urllib.request.Request(base + "/api/review/submit",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "X-Editor-Token": editor.token})
            with urllib.request.urlopen(request, timeout=5) as response:
                value = json.load(response)
            self.assert_link(value["review"], "zh-Hans", http.server_port)
        finally:
            http.shutdown()
            thread.join(timeout=5)
            http.server_close()

    def test_server_open_and_info_publish_context_link(self):
        current = self.create()
        http = Mock(server_port=8776)
        http.serve_forever.side_effect = KeyboardInterrupt
        output = io.StringIO()
        argv = ["server.py", "--project", str(self.path), "--workspace",
                str(self.folder / "workspace"), "--port", "8776", "--open"]
        with patch.object(sys, "argv", argv), patch.object(server, "ThreadingHTTPServer", return_value=http), \
             patch("webbrowser.open") as browser, redirect_stdout(output):
            server.main()
        info = json.loads(output.getvalue())
        expected = review.review_url(current["request"], "http://127.0.0.1:8776")
        self.assertEqual(info["url"], "http://127.0.0.1:8776")
        self.assertEqual(info["review_url"], expected)
        browser.assert_called_once_with(expected)

    def test_desktop_launcher_reuse_keeps_context_and_legacy_fallback(self):
        current = self.create("zh-TW")
        base = "http://127.0.0.1:8766"
        for active in (current, None):
            with self.subTest(active=bool(active)):
                responses = [io.BytesIO(json.dumps({"status": "READY", "version": __version__}).encode()),
                             io.BytesIO(json.dumps({"review": active}).encode())]
                with patch("urllib.request.urlopen", side_effect=responses) as fetch, \
                     patch("webbrowser.open") as browser, patch("subprocess.call") as launch, \
                     self.assertRaises(SystemExit) as exit_status:
                    runpy.run_path(str(ROOT / "editor/launch.py"), run_name="__main__")
                self.assertEqual(exit_status.exception.code, 0)
                browser.assert_called_once_with(review.review_url(current["request"], base) if active else base)
                launch.assert_not_called()
                self.assertEqual(fetch.call_args_list[-1].args[0], base + "/api/review")


if __name__ == "__main__":
    unittest.main()
