"""Installer/release behavior on tiny fixtures; never touches installed skills."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location("test_" + name + "_script", ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load_script("install")
release = load_script("build_release")


class PackagingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.destination = self.root / "codex/skills"
        self.files = {"SKILL.md": "---\nname: blender2easy\ndescription: Test fixture.\n---\n",
                      "LICENSE": "Test fixture license\n",
                      "scripts/animkit/__init__.py": '__version__ = "0.0.1"\n',
                      "editor/web/index.html": "<p>Fixture</p>\n"}
        runtime = {"editor/projects/editor-state.json": '{"current":"private-project"}',
                   "scripts/__pycache__/cached.pyc": "bytecode",
                   ".animation/review/response.json": "private feedback",
                   "node_modules/package/data": "dependency cache"}
        for relative, contents in (self.files | runtime).items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents.encode("utf-8"))
        for module in (installer, release):
            patcher = patch.object(module, "SOURCE", self.source)
            patcher.start()
            self.addCleanup(patcher.stop)

    def existing(self, name, text):
        path = self.destination / name
        path.mkdir(parents=True)
        (path / "old.txt").write_text(text, encoding="utf-8")
        return path

    def test_fresh_install_excludes_runtime_state(self):
        target, backups = installer.install(self.destination)
        self.assertEqual(target, self.destination / "blender2easy")
        self.assertEqual(backups, [])
        self.assertEqual({p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()}, set(self.files))

    def test_existing_skill_is_preserved_without_replace(self):
        for name in ("blender2easy", "object-animation"):
            with self.subTest(name=name):
                self.destination = self.root / ("without-replace-" + name) / "skills"
                old = self.existing(name, name)
                with self.assertRaisesRegex(ValueError, "--replace"):
                    installer.install(self.destination)
                self.assertEqual((old / "old.txt").read_text(), name)

    def test_replace_backs_up_current_and_legacy_outside_discovery(self):
        self.existing("blender2easy", "current skill")
        self.existing("object-animation", "legacy skill")
        target, backups = installer.install(self.destination, replace=True)
        self.assertEqual(len(backups), 2)
        self.assertTrue((target / "SKILL.md").is_file())
        self.assertFalse((self.destination / "object-animation").exists())
        self.assertEqual({path.name for path in backups}, {"blender2easy", "object-animation"})
        for path in backups:
            self.assertFalse(path.is_relative_to(self.destination))
            self.assertTrue(path.is_relative_to(self.destination.parent / "skill-backups"))
            self.assertEqual((path / "old.txt").read_text(),
                             "legacy skill" if path.name == "object-animation" else "current skill")

    def test_failed_publish_restores_previous_install(self):
        old = self.existing("blender2easy", "preserve me")
        original_rename = Path.rename

        def fail_staged_publish(path, target):
            if path.name == "blender2easy" and path.parent.name.startswith(".blender2easy-install-"):
                raise OSError("simulated publish failure")
            return original_rename(path, target)

        with patch.object(Path, "rename", fail_staged_publish), self.assertRaisesRegex(OSError, "simulated"):
            installer.install(self.destination, replace=True)
        self.assertEqual((old / "old.txt").read_text(), "preserve me")
        self.assertFalse(list(self.destination.parent.glob(".blender2easy-install-*")))

    def test_zip_has_single_skill_root_and_verified_manifest(self):
        archive, count = release.package(self.root / "dist")
        self.assertEqual(count, len(self.files))
        with zipfile.ZipFile(archive) as bundle:
            self.assertIsNone(bundle.testzip())
            self.assertEqual(set(bundle.namelist()), {"blender2easy/" + p for p in self.files})
            for relative, text in self.files.items():
                self.assertEqual(bundle.read("blender2easy/" + relative), text.encode("utf-8"))
        manifest = json.loads(archive.with_name("blender2easy-v0.0.1-manifest.json").read_text())
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual(manifest["sha256"], digest)
        self.assertEqual(manifest["version"], "0.0.1")
        self.assertEqual(archive.with_suffix(".sha256").read_text(), f"{digest}  {archive.name}\n")
        self.assertEqual({entry["path"] for entry in manifest["files"]}, set(self.files))
        for entry in manifest["files"]:
            self.assertEqual(entry["sha256"], hashlib.sha256(self.files[entry["path"]].encode()).hexdigest())
        second, _ = release.package(self.root / "second-dist")
        self.assertEqual(archive.read_bytes(), second.read_bytes(), "Archive must be reproducible")

    def test_packaging_preserves_existing_archive_and_rejects_source_output(self):
        archive, _ = release.package(self.root / "dist")
        original = archive.read_bytes()
        with self.assertRaises(FileExistsError):
            release.package(self.root / "dist")
        self.assertEqual(archive.read_bytes(), original)
        with self.assertRaises(ValueError):
            release.package(self.source / "dist")


if __name__ == "__main__":
    unittest.main()
