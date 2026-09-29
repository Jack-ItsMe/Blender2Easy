"""Bounded adapters for the pinned Blender Agent Studio scripts.

Importing this module starts no processes. No user Python or shell expressions
are accepted. Runs create new evidence directories unless verified reuse is
explicitly requested.
"""
from pathlib import Path
import json
import math
import os
import subprocess
import time

from .common import read_json, resolve_tool, sha256, write_json

SKILL_ROOT = Path(__file__).resolve().parents[2]
VENDOR_ROOT = SKILL_ROOT / "vendor" / "bas"
PLUGIN = VENDOR_ROOT / "plugins" / "blender-agent-studio"
VALIDATION = "skills/blender-asset-validation/scripts/"
COMMON_FIELDS = {"input", "outputDir", "dependencies", "dependenciesComplete"}
TOOLS = {
    "inspect": (VALIDATION + "inspect_asset.py", "metrics.json", {"frame"}),
    "topology": (VALIDATION + "diagnose_topology.py", "topology.json", {"object", "limit", "frame"}),
    "motion": (VALIDATION + "inspect_motion.py", "motion.json", {"frames", "targets"}),
    "scene-ir": (VALIDATION + "extract_scene_ir.py", "scene-ir.json", {"frame"}),
    "evidence": (VALIDATION + "render_evidence.py", "evidence.json", {"frame", "frames", "views", "resolution", "materialMode", "hideObjects", "headTexture", "presentation"}),
    "reference": (VALIDATION + "compare_reference.py", "comparison.json", {"reference", "mask", "camera", "frame", "maxEdge", "landmarks"}),
    "camera-fit": (VALIDATION + "fit_reference_camera.py", "camera-fit.json", {"camera", "frame", "landmarks", "width", "height"}),
    "authored-render": ("skills/blender-rendering-workflow/scripts/render_scene.py", "render-manifest.json", {"inspectOnly", "scene", "cameras", "frames", "maxEdge", "samples", "device", "denoise", "timeLimit"}),
    "mixamo-import": ("skills/blender-animation-workflow/scripts/import_mixamo.py", "mixamo-import.json", {"clipName", "fps"}),
}
SPECIALISTS = [
    ("modeling", "blender-modeling-workflow", "Reproducible geometry, staged refinement, modeling contract and image-to-3D decisions", "Read workflow; preserve native assets or author deterministic bpy according to the selected source mode"),
    ("intake", "blender-art-direction-intake", "Art direction, references, assumptions and acceptance evidence", "Read workflow; image generation is optional and requires its available tool"),
    ("validation", "blender-asset-validation", "Inspection, topology, evaluated motion, references, camera fitting, multiview evidence", "quality run: all validation adapters; Python + Blender"),
    ("refinement", "blender-iterative-refinement", "Evidence-backed defect ledger and focused second pass", "Read workflow; quality adapters provide measurements and images"),
    ("animation", "blender-animation-workflow", "Articulation, motion truth, export verification, optional Mixamo import", "Read workflow; quality run motion; quality run mixamo-import creates a separate candidate from a local authorized FBX without retargeting"),
    ("procedural", "blender-procedural-workflow", "Geometry Nodes, deterministic seeds, parameters, evaluated outputs", "Read workflow; create with Blender; inspect evaluated scene using quality run scene-ir"),
    ("rendering", "blender-rendering-workflow", "Authored camera/light preservation, material libraries, denoising and bounded samples", "quality run authored-render; optional Poly Haven CLI requires Bun and network"),
    ("simulation", "blender-simulation-workflow", "Bake/cache provenance, determinism, sampled physical evidence", "Read workflow; bake with Blender; quality run motion diagnoses sampled output"),
    ("character", "blender-character-workflow", "Anatomy, rigging, deformation, export and hair fit", "Read workflow; direct scripts/fit_vrchat_hair.py uses Blender and local input assets"),
    ("benchmark", "blender-agent-benchmark", "Isolated baseline comparisons, evidence scores, trace/cost provenance", "Source included; optional harness requires Bun, configured Codex CLI and agent/model access; not automatically launched"),
    ("integration", "blender-mcp-integration", "Transport choice, bounded tools, path safety and fallbacks", "animation.py mcp exposes local quality, diagnostics and scoped review over Python stdio; explicit host configuration, no global registration. Optional upstream Bun MCP/Rust source remains separate"),
]


def catalog():
    return {
        "schemaVersion": 1,
        "commands": [{"tool": name, "script": str(PLUGIN / row[0]),
                      "fields": sorted(COMMON_FIELDS | row[2]), "report": row[1],
                      "runtime": "Python standard library + Blender (includes numpy)"}
                     for name, row in TOOLS.items()],
        "specialists": [{"name": name, "skill": str(PLUGIN / "skills" / skill / "SKILL.md"),
                         "capability": capability, "execution": execution}
                        for name, skill, capability, execution in SPECIALISTS],
        "localMcp": {"command": "python scripts/animation.py mcp", "script": str(SKILL_ROOT / "scripts" / "studio_mcp.py"),
                     "runtime": "Python + official MCP SDK (scripts/requirements-mcp.txt); Blender for Blender operations",
                     "capabilities": ["version/doctor", "quality catalog/run/reuse", "asset browser handoffs", "diagnostic snapshot/describe/analyze/compare", "scoped review create/status/wait/apply/close"],
                     "registration": "Explicit host configuration only; never globally registered by this skill"},
        "optionalHelpers": [
            {"name": "Mixamo browser workflow", "source": "scripts/mixamo.ts", "localCommand": "assets search mixamo --query QUERY", "requires": "Python creates the handoff without Bun; host browser/Adobe sign-in for actual results/download; no provider connection installed"},
            {"name": "Pixabay audio browser workflow", "source": "scripts/pixabay.ts", "localCommand": "assets search pixabay --query QUERY", "requires": "Python creates the handoff; host browser/network/license review for actual assets; not an audio API"},
            {"name": "Poly Haven", "source": "skills/blender-rendering-workflow/scripts/poly-haven-cli.ts", "requires": "Bun and network; downloads must be explicitly in task scope"},
            {"name": "Scene relationship analysis", "source": "scripts/scene-analysis.ts", "requires": "Optional upstream Bun/Rust route; use animation.py diagnose for the local Python route"},
            {"name": "Upstream MCP viewer/server", "source": "mcp/server.ts", "requires": "Optional Bun + package dependencies; use animation.py mcp for integrated local quality/diagnostic/review tools without Bun. Upstream server is not installed, activated, or registered"},
        ],
        "specGuide": str(SKILL_ROOT / "references" / "quality-tools.md"),
        "specPaths": "Resolve relative input/output/dependency paths against the spec file directory.",
        "reuse": {"flag": "--reuse", "default": False,
                  "behavior": "Requires spec dependenciesComplete:true, an explicit assertion that resources are packed or every external resource is declared. Reuse only a completed, unchanged run at the same outputDir after checking provenance and every output hash; reject stale or partial outputs without overwriting them.",
                  "coverage": "Spec, source, explicitly declared dependencies/images, quality adapter code, fixed vendor scripts, Blender executable, log and all payload files. Pack external asset resources or declare them in dependencies; unlisted resources are not discovered or certified."},
        "limitations": ["Fixed entrypoints and disabled embedded scripts are not an OS sandbox.",
                        "Pack .blend dependencies or list external files in dependencies for provenance coverage.",
                        "Timeout bounds wall time; complex Blender evaluation can still require substantial memory.",
                        "Metrics and frame samples do not establish visual quality or continuous collision freedom."]}


def _integer(value, field, lo, hi):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f"{field} must be an integer from {lo} to {hi}")
    return value


def _name(value, field):
    if not isinstance(value, str) or not value or len(value) > 512 or value.startswith("-") or "\0" in value:
        raise ValueError(f"{field} must be a nonempty name (up to 512 characters, no leading '-')")
    return value


def _names(value, field, limit=32, comma=False):
    if not isinstance(value, list) or not 1 <= len(value) <= limit:
        raise ValueError(f"{field} must contain 1 to {limit} names")
    items = [_name(v, field) for v in value]
    if len(set(items)) != len(items) or (comma and any("," in v for v in items)):
        raise ValueError(f"{field} requires unique names without commas")
    return items


def _frames(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 32:
        raise ValueError("frames must contain 1 to 32 unique frame integers")
    values = [_integer(v, "frame", -1048574, 1048574) for v in value]
    if len(set(values)) != len(values):
        raise ValueError("frames must be unique")
    return values


def _landmarks(value, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= 32:
        raise ValueError(f"landmarks requires {minimum} to 32 items")
    for item in value:
        if not isinstance(item, dict) or set(item) - {"name", "objectName", "referenceUv", "localPoint"}:
            raise ValueError("Each landmark has name, objectName, referenceUv and optional localPoint")
        _name(item.get("name"), "landmark name")
        _name(item.get("objectName"), "landmark objectName")
        for key, length in (("referenceUv", 2), ("localPoint", 3)):
            vector = item.get(key, [0, 0, 0] if key == "localPoint" else None)
            if not isinstance(vector, list) or len(vector) != length or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
                raise ValueError(f"{key} requires {length} finite numeric coordinates")
            if key == "referenceUv" and not all(0 <= v <= 1 for v in vector):
                raise ValueError("referenceUv must be normalized coordinates from image top-left")
    return json.dumps(value, separators=(",", ":"), allow_nan=False)


def _path(value, field, base, existing=True):
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError(f"{field} must be a path")
    path = Path(value).expanduser()
    path = (base / path).resolve() if not path.is_absolute() else path.resolve()
    if existing and not path.is_file():
        raise ValueError(f"{field} file does not exist: {path}")
    return path


def prepare(tool, spec, base, *, allow_existing=False):
    """Validate before creating any output; return fixed script and argument plan."""
    if tool not in TOOLS:
        raise ValueError(f"Unknown quality tool: {tool}")
    if not isinstance(spec, dict):
        raise ValueError("Spec must be a JSON object")
    script, report_name, fields = TOOLS[tool]
    unknown = set(spec) - COMMON_FIELDS - fields
    if unknown:
        raise ValueError("Unknown spec fields: " + ", ".join(sorted(unknown)))
    if "dependenciesComplete" in spec and type(spec["dependenciesComplete"]) is not bool:
        raise ValueError("dependenciesComplete must be boolean")
    source = _path(spec.get("input"), "input", base)
    formats = {".fbx"} if tool == "mixamo-import" else ({".blend"} if tool in {"reference", "camera-fit", "authored-render"} else {".blend", ".glb", ".gltf", ".obj", ".fbx"})
    if source.suffix.lower() not in formats:
        raise ValueError(f"Unsupported input format for {tool}")
    output = _path(spec.get("outputDir"), "outputDir", base, False)
    if output.exists() and not allow_existing:
        raise ValueError("outputDir must be new; use --reuse only to verify a completed unchanged run")
    payload = output / "payload"
    report = payload / report_name
    args = ["--input", str(source)]
    args += ["--output", str(report)] if tool in {"inspect", "topology", "motion", "scene-ir"} else ["--output-dir", str(payload)]
    inputs = [("input", source)]
    dependencies = spec.get("dependencies", [])
    if not isinstance(dependencies, list) or len(dependencies) > 128:
        raise ValueError("dependencies must be a list of at most 128 files")
    inputs += [("dependency", _path(v, "dependency", base)) for v in dependencies]
    def option(key, flag, value):
        args.extend([flag, str(value)])
    if "frame" in spec:
        option("frame", "--frame", _integer(spec["frame"], "frame", -1048574, 1048574))
    if tool == "topology":
        option("limit", "--limit", _integer(spec.get("limit", 20), "limit", 1, 100))
        if "object" in spec: option("object", "--object", _name(spec["object"], "object"))
    if tool == "motion":
        frames = _frames(spec.get("frames"))
        if not 2 <= len(frames) <= 12 or frames != sorted(frames):
            raise ValueError("motion requires 2 to 12 increasing distinct frames")
        # A comma-separated list starting with '-' otherwise looks like a new
        # argparse option, even though negative source frames are valid.
        args.append("--frames=" + ",".join(map(str, frames)))
        args.extend(["--targets", *_names(spec.get("targets"), "targets", 8)])
    if tool == "evidence":
        if "frames" in spec: args.append("--frames=" + ",".join(map(str, _frames(spec["frames"]))))
        option("resolution", "--resolution", _integer(spec.get("resolution", 384), "resolution", 128, 1024))
        views = _names(spec.get("views", ["perspective", "front", "back", "left", "right", "top"]), "views", 6)
        if set(views) - {"perspective", "front", "back", "left", "right", "top"}: raise ValueError("Unknown fixed evidence view")
        option("views", "--views", ",".join(views))
        if "hideObjects" in spec: option("hideObjects", "--hide-objects", ",".join(_names(spec["hideObjects"], "hideObjects", 128, True)))
        for key, flag, choices, default in (("presentation", "--presentation", {"auto", "neutral", "dark", "light"}, "auto"), ("materialMode", "--material-mode", {"source", "vrchat-fit"}, "source")):
            value = spec.get(key, default)
            if not isinstance(value, str) or value not in choices: raise ValueError(f"Invalid {key}")
            option(key, flag, value)
    if tool in {"reference", "camera-fit"}:
        if "camera" in spec: option("camera", "--camera", _name(spec["camera"], "camera"))
        option("landmarks", "--landmarks-json", _landmarks(spec.get("landmarks", []), 3 if tool == "camera-fit" else 0))
    for key, flag in (("reference", "--reference"), ("mask", "--mask"), ("headTexture", "--head-texture")):
        if key in spec or (key == "reference" and tool == "reference"):
            path = _path(spec.get(key), key, base)
            inputs.append((key, path)); option(key, flag, path)
    if tool == "camera-fit":
        for key in ("width", "height"): option(key, "--" + key, _integer(spec.get(key), key, 1, 8192))
    if tool == "reference":
        option("maxEdge", "--max-edge", _integer(spec.get("maxEdge", 512), "maxEdge", 128, 1024))
    if tool == "authored-render":
        if "inspectOnly" in spec and type(spec["inspectOnly"]) is not bool: raise ValueError("inspectOnly must be boolean")
        if spec.get("inspectOnly"): args.append("--inspect-only")
        if "scene" in spec: option("scene", "--scene", _name(spec["scene"], "scene"))
        if "cameras" in spec:
            for name in _names(spec["cameras"], "cameras", 6): option("camera", "--camera", name)
        if "frames" in spec: args.extend(["--frames", *map(str, _frames(spec["frames"]))])
        if len(spec.get("frames", [0])) * len(spec.get("cameras", [0])) > 12:
            raise ValueError("authored-render permits at most 12 camera/frame renders")
        for key, flag, default, lo, hi in (("maxEdge", "--max-edge", 1280, 128, 4096), ("samples", "--samples", 64, 1, 1024), ("timeLimit", "--time-limit", 120, 1, 600)):
            option(key, flag, _integer(spec.get(key, default), key, lo, hi))
        for key, choices, default in (("device", {"auto", "cpu", "OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"}, "auto"), ("denoise", {"preserve", "preview", "final", "off"}, "preserve")):
            value = spec.get(key, default)
            if not isinstance(value, str) or value not in choices: raise ValueError(f"Invalid {key}")
            option(key, "--" + key, value)
    if tool == "mixamo-import":
        clip = _name(spec.get("clipName"), "clipName")
        if not clip.strip() or len(clip) > 120:
            raise ValueError("clipName requires 1 to 120 characters")
        fps = _integer(spec.get("fps", 30), "fps", 24, 60)
        if fps not in (24, 30, 60): raise ValueError("fps must be 24, 30 or 60")
        option("clipName", "--clip-name", clip)
        option("fps", "--fps", fps)
    return {"script": PLUGIN / script, "args": args, "inputs": inputs,
            "output": output, "payload": payload, "report": report}


def _fingerprint(role, path):
    return {"role": role, "path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def _code_fingerprints(plan):
    source_files = sorted(p for p in plan["script"].parent.glob("*.py") if not p.name.startswith(("test_", "_blender")))
    local_files = ["scripts/animation.py", "scripts/quality_cli.py", "scripts/animkit/__init__.py",
                   "scripts/animkit/common.py", "scripts/animkit/quality_tools.py"]
    adapter = {"path": str(Path(__file__).relative_to(SKILL_ROOT)), "sha256": sha256(__file__),
               "cliSha256": sha256(SKILL_ROOT / "scripts" / "quality_cli.py"),
               "scripts": [{"path": name, "sha256": sha256(SKILL_ROOT / name)} for name in local_files]}
    upstream = {"url": "https://github.com/ifBars/blender-agent-studio", "commit": "748b18ba4cbb5df6fc1da854e00e4c3526fdd128",
                "scripts": [{"path": str(p.relative_to(VENDOR_ROOT)), "sha256": sha256(p)} for p in source_files]}
    return adapter, upstream


def _payload_fingerprints(payload):
    """Require an ordinary output tree; never hash files reached by links."""
    def is_link(path):
        return path.is_symlink() or getattr(path, "is_junction", lambda: False)()
    if not payload.is_dir() or is_link(payload):
        raise ValueError("Payload must be an ordinary directory")
    files = []
    for root, directories, names in os.walk(payload, followlinks=False):
        for name in directories + names:
            path = Path(root) / name
            if is_link(path) or not path.resolve().is_relative_to(payload.resolve()):
                raise ValueError("Payload links are not reusable evidence")
        files.extend(Path(root) / name for name in names)
    return [_fingerprint("output", p) for p in sorted(files)]


def _summary(result, reused=False):
    return {key: result[key] for key in ("schemaVersion", "tool", "status", "outputDir", "report", "log", "provenance", "inputUnchanged", "durationSeconds")} | {"reused": reused} | ({"error": result["error"]} if "error" in result else {})


def _reuse_completed(plan, expected, started):
    """Reject rather than repair stale evidence, preserving the prior run."""
    def reject(reason):
        raise ValueError("Cannot reuse outputDir: " + reason + "; use a new outputDir for a new run")
    try:
        saved = read_json(expected["provenance"])
        if not isinstance(saved, dict) or saved.get("reuseSchemaVersion") != 1:
            reject("missing or unsupported reuse provenance")
        if saved.get("status") != "complete" or saved.get("inputUnchanged") is not True or saved.get("executionUnchanged") is not True or type(saved.get("returnCode")) is not int or saved["returnCode"] != 0:
            reject("prior run is incomplete, failed or changed during execution" + (": " + str(saved["error"]) if saved.get("error") else ""))
        for key in ("schemaVersion", "tool", "outputDir", "report", "log", "provenance", "inputs", "dependenciesComplete", "adapter", "upstream", "command"):
            if saved.get(key) != expected[key]:
                reject(key + " changed")
        if saved.get("inputsAfter") != expected["inputs"]:
            reject("recorded input verification differs")
        runtime = saved.get("runtime", {})
        if not isinstance(runtime, dict) or any(runtime.get(key) != expected["runtime"][key] for key in ("executable", "executableSha256")):
            reject("Blender executable changed")
        outputs = _payload_fingerprints(plan["payload"])
        if not outputs or outputs != saved.get("outputs") or not any(item["path"] == expected["report"] for item in outputs):
            reject("payload inventory or content changed")
        if _fingerprint("log", Path(expected["log"])) != saved.get("logFingerprint"):
            reject("Blender log changed")
        if not isinstance(read_json(plan["report"]), dict):
            reject("required report is not a JSON object")
        if [_fingerprint(item["role"], Path(item["path"])) for item in expected["inputs"]] != expected["inputs"]:
            reject("input changed while verifying reuse")
        result = _summary(saved, reused=True)
        result["reuseVerificationSeconds"] = round(time.monotonic() - started, 3)
        return result
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("Cannot reuse outputDir:"):
            raise
        reject("unreadable or invalid evidence (" + str(exc) + ")")


def run_tool(tool, spec_path, blender=None, timeout=300, reuse=False):
    operation_started = time.monotonic()
    timeout = _integer(timeout, "timeout", 1, 7200)
    if type(reuse) is not bool: raise ValueError("reuse must be boolean")
    spec_path = Path(spec_path).resolve()
    if spec_path.stat().st_size > 1024 * 1024: raise ValueError("Spec exceeds 1 MiB")
    spec = read_json(spec_path)
    if reuse and (not isinstance(spec, dict) or spec.get("dependenciesComplete") is not True):
        raise ValueError("--reuse requires spec dependenciesComplete:true: assert that resources are packed or all external resources are listed in dependencies")
    plan = prepare(tool, spec, spec_path.parent, allow_existing=reuse)
    executable = resolve_tool("blender", blender)
    before = [_fingerprint(role, path) for role, path in [("spec", spec_path), *plan["inputs"]]]
    adapter, upstream = _code_fingerprints(plan)
    argv = [executable, "--background", "--factory-startup", "--disable-autoexec", "--python-exit-code", "17", "--python", str(plan["script"]), "--", *plan["args"]]
    manifest_path = plan["output"] / "provenance.json"
    log = plan["output"] / "blender.log"
    result = {"schemaVersion": 1, "reuseSchemaVersion": 1, "tool": tool, "status": "running", "outputDir": str(plan["output"]),
              "report": str(plan["report"]), "log": str(log), "provenance": str(manifest_path),
              "inputs": before, "inputUnchanged": None,
              "dependenciesComplete": spec.get("dependenciesComplete", False),
              "runtime": {"executable": executable, "executableSha256": sha256(executable), "timeoutSeconds": timeout},
              "adapter": adapter, "upstream": upstream,
              "command": argv, "outputs": []}
    if reuse and plan["output"].exists():
        return _reuse_completed(plan, result, operation_started)
    # Allocate atomically after validation. A competing creation is not reused.
    plan["output"].mkdir(parents=True, exist_ok=False)
    if tool != "mixamo-import":
        plan["payload"].mkdir()
    write_json(manifest_path, result)
    started = time.monotonic()
    try:
        with log.open("wb") as stream:
            process = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT, shell=False, timeout=timeout)
        result["returnCode"] = process.returncode
        if process.returncode: raise RuntimeError(f"Blender exited {process.returncode}; inspect {log}")
        if not plan["report"].is_file(): raise RuntimeError("Blender completed without its required report")
        report = read_json(plan["report"])
        if not isinstance(report, dict): raise RuntimeError("Blender report must be a JSON object")
        result["status"] = "complete"
    except subprocess.TimeoutExpired:
        result["status"] = "timeout"; result["error"] = f"Blender exceeded {timeout} seconds and was terminated"
    except Exception as exc:
        result["status"] = "failed"; result["error"] = str(exc)
    finally:
        after = []
        for item in before:
            try: after.append(_fingerprint(item["role"], Path(item["path"])))
            except OSError: after.append({"role": item["role"], "path": item["path"], "missing": True})
        result["inputsAfter"] = after
        result["inputUnchanged"] = before == after
        if not result["inputUnchanged"]:
            result["status"] = "failed"; result["error"] = "An input changed during the run; evidence is invalid"
        result["durationSeconds"] = round(time.monotonic() - started, 3)
        if log.is_file():
            with log.open(encoding="utf-8", errors="replace") as stream:
                for index, line in enumerate(stream):
                    if line.startswith("Blender "):
                        result["runtime"]["reportedVersion"] = line.strip()
                        break
                    if index >= 2000: break
        try:
            result["executionUnchanged"] = (_code_fingerprints(plan) == (adapter, upstream)
                                             and sha256(executable) == result["runtime"]["executableSha256"])
            if not result["executionUnchanged"]:
                raise ValueError("Execution code or Blender executable changed during the run")
            result["outputs"] = _payload_fingerprints(plan["payload"]) if plan["payload"].exists() else []
            result["logFingerprint"] = _fingerprint("log", log)
        except (OSError, ValueError) as exc:
            result["status"] = "failed"
            result["error"] = (result.get("error", "") + "; " + str(exc)).lstrip("; ")
        write_json(manifest_path, result)
    return _summary(result)
