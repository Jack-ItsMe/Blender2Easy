"""Loopback-only Three.js editor and local Blender job bridge."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import traceback
from urllib.parse import urlparse, parse_qs, unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from animkit import __version__
from animkit.common import file_lock, read_json, sha256, write_json, digest
from animkit.project import load_project, normalize_project, compile_plans


class APIError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def clean(project):
    return {key: value for key, value in project.items() if not key.startswith("_")}


class Editor:
    def __init__(self, workspace, initial=None, authoring=False):
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(32)
        self.guard = threading.RLock()
        self.path = None
        self.jobs = {}
        self.active_job = None
        self.native_loading = False
        self.artifacts = {}
        self.previews = {}
        self.manifests = {}
        self.preview_fingerprints = {}
        self.manifest_fingerprints = {}
        self.known = {}
        self.authoring = authoring
        if initial:
            self.open(initial)
        else:
            index = self.workspace / "editor-state.json"
            if index.exists():
                try:
                    remembered = read_json(index)
                    for entry in remembered.get("projects", []):
                        if Path(entry["path"]).is_file():
                            self.known[entry["path"]] = entry
                    if remembered.get("current") and Path(remembered["current"]).is_file():
                        self.open(remembered["current"])
                except (OSError, ValueError, KeyError):
                    pass
            if self.path is None:
                self.new("box", "包装盒 · 开合演示")

    def remember(self, path, project):
        self.known[str(path)] = {"id": project["id"], "title": project["id"], "path": str(path)}
        write_json(self.workspace / "editor-state.json", {"current": str(self.path), "projects": list(self.known.values())})

    @staticmethod
    def native_fingerprint(project):
        """The viewport base excludes overrides but includes every native input."""
        if "source" not in project:
            return None
        return digest({"scene": project["source"]["scene"],
                       "asset_hashes": project["_asset_hashes"]})

    def response(self):
        if self.path is None:
            raise APIError("请先打开或新建项目")
        p = load_project(self.path)
        native = "source" in p
        key = str(self.path)
        fingerprint = self.native_fingerprint(p)
        if key in self.previews and (not native or self.preview_fingerprints.get(key) != fingerprint):
            self.previews.pop(key, None)
            self.preview_fingerprints.pop(key, None)
        if key in self.manifests and (not native or self.manifest_fingerprints.get(key) != fingerprint):
            self.manifests.pop(key, None)
            self.manifest_fingerprints.pop(key, None)
        preview = self.previews.get(key)
        manifest = self.manifests.get(key)
        return {"project": clean(p), "path": str(self.path), "revision": sha256(self.path),
                "mode": "native" if native else "procedural", "preview": preview,
                "manifest": manifest, "warnings": (["实时预览用于构图与动作调整；材质、灯光与曲线效果以 Blender 渲染为准。"]
                  + (manifest.get("warnings", []) if manifest else []))}

    def session(self):
        with self.guard:
            return {"token": self.token, "version": __version__, "authoring": self.authoring, "projects": list(self.known.values()),
                    "current": self.response() if self.path else None}

    def review_response(self, base_url="http://127.0.0.1:8766"):
        from animkit.review import get_review, review_url, _check_reference_hashes
        with self.guard:
            review = get_review(self.path) if self.path else None
            if review:
                review["url"] = review_url(review["request"], base_url)
                if review['status'] in ('pending', 'submitted'):
                    _check_reference_hashes(review['request'])
                media = review.get("request", {}).get("media")
                if media:
                    review["media_url"] = self.review_media(media)
                references = review.get("request", {}).get("evidence", {}).get("references", [])
                review["reference_urls"] = {reference["id"]: self.review_media(reference, reference=True)
                                            for reference in references}
            return {"review": review, "current": self.response() if self.path else None}

    def review_media(self, media, reference=False):
        source = Path(media["path"])
        expected = media["sha256"]
        if reference and source.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            raise APIError("参考图必须是本地 PNG 或 JPG 图片", 409)
        if not source.is_file() or sha256(source) != expected:
            raise APIError("参考图已变化，请由 Agent 创建新预览任务" if reference
                           else "成片已变化，请由 Agent 为新版本创建预览任务", 409)
        # Freeze served bytes as well as the review metadata. An existing URL must
        # never silently start serving a replacement render at the same source path.
        frozen = self.path.parent / ".animation/review/media" / (expected + source.suffix.lower())
        frozen.parent.mkdir(parents=True, exist_ok=True)
        if not frozen.is_file() or sha256(frozen) != expected:
            temporary = frozen.with_name(frozen.name + "." + secrets.token_hex(6) + ".tmp")
            try:
                shutil.copyfile(source, temporary)
                if sha256(temporary) != expected:
                    raise APIError("参考图在加载时发生变化，请重新创建预览任务" if reference
                                   else "成片在加载时发生变化，请重新创建预览任务", 409)
                os.replace(temporary, frozen)
            finally:
                temporary.unlink(missing_ok=True)
        return self.artifact(frozen)

    def activate_review(self, path, request_id, base_url="http://127.0.0.1:8766"):
        from animkit.review import get_review
        with self.guard:
            if self.active_job or self.native_loading:
                raise APIError("预览准备中，请完成后再切换调整任务", 409)
            candidate = Path(path).expanduser().resolve()
            review = get_review(candidate)
            if not review or review["request"]["id"] != request_id:
                raise APIError("调整任务已变更，请使用当前任务的新预览入口", 409)
            self.open(candidate)
            return self.review_response(base_url)

    def open(self, path):
        with self.guard:
            candidate = Path(path).expanduser().resolve()
            if candidate.suffix.lower() != ".json" or not candidate.is_file():
                raise APIError("请选择存在的项目 JSON 文件")
            p = load_project(candidate)
            self.path = candidate
            self.remember(candidate, p)
            return self.response()

    def new_directory(self, name):
        name = str(name or "新项目").strip()[:60]
        slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name).rstrip(". ") or "project"
        target = self.workspace / (slug + "-" + secrets.token_hex(3))
        target.mkdir()
        return target

    def new(self, template="box", name="新项目"):
        with self.guard:
            if template not in {"box", "lamp", "blank"}:
                raise APIError("未知模板")
            target = self.new_directory(name)
            raw = read_json(ROOT / "assets/templates" / (template + ".json"))
            raw["id"] = template + "-" + secrets.token_hex(3)
            write_json(target / "project.json", raw)
            return self.open(target / "project.json")

    def import_native(self, path, name):
        candidate = Path(path).expanduser().resolve()
        if not candidate.is_file() or candidate.suffix.lower() != ".blend":
            raise APIError("请选择存在的 .blend 文件")
        with self.guard:
            if self.active_job or self.native_loading:
                raise APIError("请等待当前 Blender 任务完成后导入", 409)
            target = self.new_directory(name or candidate.stem)
            self.native_loading = True
        from animkit.editor_bridge import discover_native
        try:
            manifest = discover_native(candidate, target / ".animation/editor/import")
        finally:
            with self.guard:
                self.native_loading = False
        cameras = manifest.get("cameras", [])
        if not cameras:
            raise APIError("原生工程没有可用相机；请在 Blender 中添加相机后导入")
        start = max(1, int(manifest.get("frame_start", 1)))
        end = max(start, int(manifest.get("frame_end", start + 47)))
        raw = {"schema_version": 1, "id": "native-" + secrets.token_hex(3), "units": "m", "assets": [],
               "source": {"blend": str(candidate), "scene": manifest["scene"],
                          "dependencies": manifest.get("dependencies", [])},
               "render": {"fps": min(120, max(1, round(manifest.get("fps", 24)))),
                          "resolution": [960, 540], "samples": 16, "engine": "BLENDER_EEVEE", "transparent": False},
               "shots": [{"id": "main", "title": "主镜头", "source_range": [start, end],
                          "camera": cameras[0]["id"], "timing": [{"source_range": [start, end], "frames": end-start+1, "anchors": [start, end]}],
                          "overlays": []}]}
        path = target / "project.json"
        normalized = normalize_project(raw, path)
        write_json(path, raw)
        with self.guard:
            self.manifests[str(path)] = manifest
            self.manifest_fingerprints[str(path)] = self.native_fingerprint(normalized)
            return self.open(path)

    def check_project_path(self, project_path):
        if not self.path or not project_path or Path(project_path).expanduser().resolve() != self.path:
            raise APIError("项目已在另一窗口切换，请重新打开当前项目后再操作", 409)

    def save(self, raw, revision, project_path):
        with self.guard:
            self.check_project_path(project_path)
            path = self.path
            if path is None:
                raise APIError("请先打开项目")
            if self.active_job and self.jobs[self.active_job]["path"] == str(path):
                raise APIError("当前项目正在渲染，请在任务完成后保存", 409)
            with file_lock(path.parent / ".animation/project.lock"):
                if not revision or sha256(path) != revision:
                    raise APIError("项目已被其他窗口或程序修改，请重新打开后再保存", 409)
                previous = read_json(path)
                normalized = normalize_project(raw, path)
                if sha256(path) != revision:
                    raise APIError("校验期间项目被外部程序修改，请重新打开", 409)
                backup = path.parent / ".animation/revisions" / (revision + ".json")
                if not backup.exists():
                    write_json(backup, previous)
                if sha256(path) != revision:
                    raise APIError("项目被外部程序修改，请重新打开", 409)
                write_json(path, clean(normalized))
                write_json(path.parent / ".animation/changes" / (sha256(path) + ".json"), {
                    "time": datetime.now(timezone.utc).isoformat(), "origin": "threejs-editor",
                    "before_sha256": revision, "after_sha256": sha256(path)})
                if previous.get("source", {}).get("blend") != normalized.get("source", {}).get("blend"):
                    self.previews.pop(str(path), None)
                    self.manifests.pop(str(path), None)
                    self.preview_fingerprints.pop(str(path), None)
                    self.manifest_fingerprints.pop(str(path), None)
            self.remember(path, normalized)
            return self.response()

    def plan(self, raw, shot, project_path):
        with self.guard:
            self.check_project_path(project_path)
            p = normalize_project(raw, self.path)
        plans = compile_plans(p, {"key": "web-preview", "blend": "preview.blend", "blender_version": "preview"})
        plan = next((item for item in plans if item["id"] == shot), plans[0] if not shot else None)
        if plan is None:
            raise APIError("镜头不存在")
        return {"sourceFrames": [row["main"][0]["source"] for row in plan["frames"]],
                "fps": plan["fps"], "total": len(plan["frames"]), "sourceRange": plan["source_range"]}

    def artifact(self, path):
        file = Path(path).resolve()
        if not file.is_file():
            return None
        with self.guard:
            # Stable URLs for already registered bytes; never expose arbitrary path access.
            key = digest({"path": str(file), "size": file.stat().st_size, "stamp": file.stat().st_mtime_ns})[:32]
            self.artifacts[key] = file
        return "/artifact/" + key

    def enhance(self, result):
        result = deepcopy(result)
        for entry in result.get("results", []):
            for field in ("video", "check", "contact_sheet"):
                if entry.get(field):
                    entry[field + "_url"] = self.artifact(entry[field])
            entry["previews_urls"] = [self.artifact(p) for p in entry.get("previews", [])]
        return result

    def start_job(self, operation, shot=None, frames=None, revision=None, project_path=None):
        if operation not in {"preview", "run", "native-preview"}:
            raise APIError("不支持的任务")
        with self.guard:
            self.check_project_path(project_path)
            if self.active_job or self.native_loading:
                raise APIError("已有 Blender 任务运行中，请等待完成", 409)
            if not self.path or revision != sha256(self.path):
                raise APIError("请先保存当前参数，再生成 Blender 预览或视频", 409)
            p = load_project(self.path)
            if shot and shot not in {s["id"] for s in p["shots"]}:
                raise APIError("镜头不存在")
            if frames is not None and (not isinstance(frames, list) or not frames or len(frames) > 20 or any(type(f) is not int or f < 1 for f in frames)):
                raise APIError("预览帧必须是至多 20 个正整数")
            ident = secrets.token_hex(8)
            job = {"id": ident, "operation": operation, "status": "queued", "path": str(self.path),
                   "revision": revision, "started_at": datetime.now(timezone.utc).isoformat()}
            self.jobs[ident] = job
            self.active_job = ident
            threading.Thread(target=self.execute_job, args=(ident, shot, frames), daemon=True).start()
            return {"id": ident, "status": "queued"}

    def execute_job(self, ident, shot, frames):
        with self.guard:
            job = self.jobs[ident]
            job["status"] = "running"
            path = Path(job["path"])
        try:
            if job["operation"] == "native-preview":
                from animkit.editor_bridge import export_preview
                with file_lock(path.parent / ".animation/project.lock"):
                    if sha256(path) != job["revision"]:
                        raise APIError("任务开始前项目已改变，请重新生成")
                    project = load_project(path)
                    fingerprint = self.native_fingerprint(project)
                    # Keep original animation in the viewport base so undo/removing an
                    # override can restore it. Three.js applies the current declarative
                    # overrides; the ordinary Blender render still uses all saved edits.
                    if "source" in project:
                        project["source"].pop("overrides", None)
                    exported = export_preview(project)
                    exported["manifest"]["preview_base"] = True
                    exported["manifest"]["applied_overrides"] = {}
                result = {"url": self.artifact(exported["path"]), "manifest": exported["manifest"]}
                with self.guard:
                    self.previews[str(path)] = result
                    self.manifests[str(path)] = result["manifest"]
                    self.preview_fingerprints[str(path)] = fingerprint
                    self.manifest_fingerprints[str(path)] = fingerprint
            else:
                args = [sys.executable, str(ROOT / "scripts/animation.py"), job["operation"], str(path), "--expected-revision", job["revision"]]
                if shot:
                    args += ["--shot", shot]
                if frames and job["operation"] == "preview":
                    args += ["--frames", ",".join(map(str, frames))]
                if sha256(path) != job["revision"]:
                    raise APIError("任务开始前项目已改变，请重新生成")
                run = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace",
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                try:
                    result = json.loads(run.stdout.strip())
                except ValueError:
                    raise APIError("制作程序未返回结果：" + (run.stderr or run.stdout)[-2000:])
                if run.returncode:
                    raise APIError(result.get("error", "Blender 任务失败"))
                result = self.enhance(result)
            with self.guard:
                job["status"], job["result"] = "complete", result
        except Exception as exc:
            with self.guard:
                job["status"], job["error"] = "failed", str(exc)
            traceback.print_exc(file=sys.stderr)
        finally:
            with self.guard:
                job["finished_at"] = datetime.now(timezone.utc).isoformat()
                self.active_job = None

    def job(self, ident):
        with self.guard:
            if ident not in self.jobs:
                raise APIError("任务不存在", 404)
            job = deepcopy(self.jobs[ident])
        status = Path(job["path"]).parent / ".animation/status.json"
        if job["status"] == "running" and status.exists():
            try:
                progress = read_json(status)
                if datetime.fromisoformat(progress.get("updated_at", "")) >= datetime.fromisoformat(job["started_at"]):
                    job["progress"] = progress
            except (OSError, ValueError):
                pass
        return job


class Handler(BaseHTTPRequestHandler):
    server_version = f"Blender2Easy/{__version__}"

    @property
    def editor(self):
        return self.server.editor

    def log_message(self, fmt, *args):
        if self.path.startswith(("/api/job", "/api/review")) or self.path == "/api/health":
            return
        super().log_message(fmt, *args)

    def json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def allowed_host(self):
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in allowed:
            raise APIError("Only this local editor origin is accepted", 403)
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + h for h in allowed}:
            raise APIError("Cross-origin requests are not accepted", 403)

    def do_POST(self):
        try:
            self.allowed_host()
            if not secrets.compare_digest(self.headers.get("X-Editor-Token", ""), self.editor.token):
                raise APIError("编辑器会话已更新，请刷新页面", 403)
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 8 * 1024 * 1024:
                raise APIError("请求太大", 413)
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise APIError("请求须为对象")
            route = urlparse(self.path).path
            if route in {"/api/open", "/api/new", "/api/import-blend", "/api/save"}:
                if not self.editor.authoring:
                    raise APIError("此预览只开放 agent 指定的调整项，请通过当前调整任务提交", 403)
                if route == "/api/save":
                    from animkit.review import get_review
                    active = get_review(self.editor.path)
                    if active and active["status"] in {"pending", "submitted"}:
                        raise APIError("当前存在局部调整任务，请先由 agent 完成该任务", 409)
            if route == "/api/review/activate":
                if set(data) - {"path", "request_id"}:
                    raise APIError("激活请求包含不支持的字段")
                value = self.editor.activate_review(data["path"], data["request_id"],
                                                    f"http://127.0.0.1:{self.server.server_port}")
            elif route in {"/api/review/preview", "/api/review/submit"}:
                from animkit.review import preview_review, submit_review
                allowed = {"path", "request_id", "revision", "values"}
                if route.endswith("/submit"):
                    allowed |= {"decision", "note", "annotation"}
                if set(data) - allowed:
                    raise APIError("只允许提交本次调整项的值和反馈")
                with self.editor.guard:
                    self.editor.check_project_path(data.get("path"))
                    if route.endswith("/preview"):
                        value = preview_review(self.editor.path, data["request_id"], data["revision"], data["values"])
                    else:
                        submit_review(self.editor.path, data["request_id"], data["revision"], data["values"],
                                      data["decision"], data.get("note", ""), data.get("annotation"))
                        value = self.editor.review_response(f"http://127.0.0.1:{self.server.server_port}")
            elif route == "/api/open":
                value = self.editor.open(data["path"])
            elif route == "/api/new":
                value = self.editor.new(data.get("template", "blank"), data.get("name", "新项目"))
            elif route == "/api/import-blend":
                value = self.editor.import_native(data["path"], data.get("name"))
            elif route == "/api/save":
                value = self.editor.save(data["project"], data.get("revision"), data.get("path"))
            elif route == "/api/plan":
                value = self.editor.plan(data["project"], data.get("shot"), data.get("path"))
            elif route == "/api/job":
                if not self.editor.authoring and data.get("operation") != "native-preview":
                    raise APIError("本次预览由 agent 负责制作，提交反馈后继续处理", 403)
                value = self.editor.start_job(data["operation"], data.get("shot"), data.get("frames"), data.get("revision"), data.get("path"))
            else:
                raise APIError("接口不存在", 404)
            self.json(value)
        except (APIError, ValueError, KeyError, OSError, RuntimeError) as exc:
            self.json({"error": str(exc)}, getattr(exc, "status", 400))

    def do_GET(self):
        try:
            self.allowed_host()
            parsed = urlparse(self.path)
            route = unquote(parsed.path)
            if route == "/api/session":
                self.json(self.editor.session())
            elif route == "/api/review":
                self.json(self.editor.review_response(f"http://127.0.0.1:{self.server.server_port}"))
            elif route == "/api/project":
                with self.editor.guard:
                    self.json(self.editor.response())
            elif route == "/api/job":
                self.json(self.editor.job(parse_qs(parsed.query).get("id", [""])[0]))
            elif route == "/api/health":
                self.json({"status": "READY", "version": __version__, "authoring": self.editor.authoring})
            elif route.startswith("/artifact/"):
                with self.editor.guard:
                    path = self.editor.artifacts.get(route.rsplit("/", 1)[-1])
                if path is None:
                    raise APIError("文件不存在", 404)
                self.file(path)
            else:
                base = ROOT / "editor/web"
                if route in {"/authoring", "/authoring.html"}:
                    if not self.editor.authoring:
                        raise APIError("完整编辑工具需要 agent 显式启用 authoring 模式", 403)
                    filename = "authoring.html"
                elif route in {"/", "/preview/model", "/preview/motion", "/preview/camera", "/preview/delivery"}:
                    filename = "index.html"
                else:
                    filename = route.lstrip("/")
                path = (base / filename).resolve()
                if not path.is_relative_to(base.resolve()) or not path.is_file():
                    raise APIError("文件不存在", 404)
                self.file(path)
        except (APIError, ValueError, KeyError, OSError, RuntimeError) as exc:
            self.json({"error": str(exc)}, getattr(exc, "status", 400))

    def file(self, path):
        mime = {".js": "text/javascript", ".mjs": "text/javascript", ".glb": "model/gltf-binary"}.get(path.suffix.lower()) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        total = path.stat().st_size
        start, end, status = 0, total - 1, 200
        ranges = self.headers.get("Range")
        if ranges:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", ranges)
            if not match or not any(match.groups()):
                raise APIError("Invalid byte range", 416)
            if match.group(1):
                start = int(match.group(1)); end = min(total - 1, int(match.group(2))) if match.group(2) else total - 1
            else:
                start = max(0, total - int(match.group(2)))
            if not 0 <= start <= end < total:
                raise APIError("Invalid byte range", 416)
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(end-start+1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' blob:; worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        self.end_headers()
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = end-start+1
            while remaining:
                chunk = stream.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--project")
    parser.add_argument("--workspace", default=str(ROOT / "editor/projects"))
    parser.add_argument("--info-file")
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--authoring", action="store_true", help="Explicitly enable full project authoring tools")
    args = parser.parse_args()
    editor = Editor(args.workspace, args.project, authoring=args.authoring)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    server.editor = editor
    url = f"http://127.0.0.1:{server.server_port}"
    info = {"status": "READY", "url": url, "pid": os.getpid(), "workspace": str(editor.workspace)}
    from animkit.review import get_review, review_url
    current_review = get_review(editor.path) if editor.path else None
    if current_review:
        info["review_url"] = review_url(current_review["request"], url)
    if args.info_file:
        write_json(args.info_file, info)
    print(json.dumps(info), flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(info.get("review_url", url))
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    main()
