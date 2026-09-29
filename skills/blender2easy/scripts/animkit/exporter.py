"""Copy a project and checked deliveries without exporting mutable render caches."""
from pathlib import Path
import os
import shutil
import tempfile

from .common import read_json, sha256, write_json
from .project import load_project, require


def export_project(project, destination, ffmpeg=None):
    target = Path(destination).expanduser().resolve()
    root = Path(project["_root"]).resolve()
    require(not target.exists(), "Export destination must be a new directory")
    require(not target.is_relative_to(root), "Export outside the original project directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".animation-export-", dir=target.parent)).resolve()
    files, mapping, deliveries = [], {}, []
    try:
        def copy_checked(source, relative, expected=None):
            source = Path(source).resolve()
            expected = expected or sha256(source)
            require(sha256(source) == expected, f"Input changed before export: {source}")
            output = stage / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, output)
            require(sha256(output) == expected, f"Export copy hash mismatch: {relative}")
            files.append({"path": Path(relative).as_posix(), "sha256": expected,
                          "bytes": output.stat().st_size})
            return Path(relative).as_posix()

        raw = read_json(project["_path"])
        for source, expected in project["_asset_hashes"].items():
            relative = Path("assets") / expected[:20] / Path(source).name
            mapping[source] = copy_checked(source, relative, expected)
        for asset, normalized in zip(raw.get("assets", []), project.get("assets", [])):
            asset["path"] = mapping[normalized["path"]]
            asset["sha256"] = normalized["sha256"]
        if "source" in raw:
            raw["source"]["blend"] = mapping[project["source"]["blend"]]
            raw["source"]["dependencies"] = [mapping[p] for p in project["source"]["dependencies"]]
        write_json(stage / "project.json", raw)
        load_project(stage / "project.json")
        files.append({"path": "project.json", "sha256": sha256(stage / "project.json"),
                      "bytes": (stage / "project.json").stat().st_size})

        index = Path(project["_state"]) / "deliveries.json"
        if index.exists():
            from .pipeline import verify_output
            for shot, entry in read_json(index).items():
                # IDs are untrusted when read from a saved artifact index.
                require(shot and shot not in (".", "..") and Path(shot).name == shot and not any(c in shot for c in '/\\<>:"|?*'),
                        "Invalid delivery ID")
                report = entry["report"]
                verification = verify_output(report, ffmpeg)
                check = read_json(report["check"])
                copied = []
                for artifact in check["artifacts"]:
                    relative = Path("deliveries") / shot / Path(artifact["path"]).name
                    copied.append(copy_checked(artifact["path"], relative, artifact["sha256"]))
                # Retain original provenance separately; it is not a relocated pipeline cache.
                copy_checked(report["check"], Path("deliveries") / shot / "source-check.json")
                deliveries.append({"shot": shot, "files": copied,
                                   "full_decode_at_export": verification.get("full_decode", False),
                                   "plan_digest": report["plan_digest"],
                                   "matches_current_project": "not_asserted"})
        native = "source" in raw
        manifest = {
            "schema_version": 1, "status": "PASS", "project": "project.json",
            "portability": "requires_native_review" if native else "project_and_declared_assets",
            "files": files, "asset_mapping": mapping, "deliveries": deliveries,
            "notes": [
                "Render caches and mutable job status are not exported; run rebuilds them.",
                "Copied deliveries are the last checked versions, not certification of later edits.",
                "source-check.json preserves original provenance paths; use this manifest's relative paths and hashes for copied files.",
            ] + (["Native .blend internal library/texture paths are not rewritten. Repack or relink resources and validate a build before claiming portability."] if native else []),
        }
        write_json(stage / "export-manifest.json", manifest)
        # A same-volume rename commits only a fully checked export and never replaces a target.
        require(not target.exists(), "Export destination was created by another process")
        os.rename(stage, target)
        return {"status": "PASS", "project": str(target / "project.json"),
                "manifest": str(target / "export-manifest.json"), "files": len(files),
                "deliveries": len(deliveries), "portability": manifest["portability"]}
    finally:
        if stage.exists():
            # Only our freshly allocated staging directory may be removed.
            require(stage.parent == target.parent and stage.name.startswith(".animation-export-"),
                    "Unexpected export staging path")
            shutil.rmtree(stage)
