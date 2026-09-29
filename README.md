# Blender2Easy

[![Tests](https://github.com/Jack-ItsMe/Blender2Easy/actions/workflows/ci.yml/badge.svg)](https://github.com/Jack-ItsMe/Blender2Easy/actions/workflows/ci.yml)

**Build with Blender. Review with your agent.**

[简体中文](README.zh-CN.md) · [Getting started](docs/getting-started.md) · [Examples](docs/examples.md) · [Contributing](CONTRIBUTING.md)

Blender2Easy is an agent skill and local toolkit for creating and refining 3D objects and presentation animations. Your agent prepares the scene in Blender, then opens a focused Three.js workspace when you need to judge a shape, motion, camera angle or rendered result.

You can point to a part, compare a reference, or adjust the few parameters relevant to the current question. The agent receives that context, checks the proposed changes and continues the work.

**Version 0.10.1 · Early release · Tested on Windows; macOS and Linux are not yet verified.**

![Blender2Easy review workspace showing a model and focused adjustment controls](docs/media/workspace.jpg)

*Interface demonstration with a prepared example scene. The browser preview is not a final Blender render or evidence of automatic product reconstruction.*

## What it brings together

| Capability | What you can do |
| --- | --- |
| Focused visual review | Review a model, an animation segment, a camera or a delivery. The agent chooses the question, initial view and permitted controls. |
| Precise feedback | Mark a visible surface or reference image, measure two preview points, isolate parts and use X-ray when enabled for the review. Supported preview geometry also offers vertex and edge snapping. |
| Reference and structure checks | Use reference-comparison tools, evaluated scene snapshots, declared connection and hinge checks, and before/after invariants. Findings can link back to a review location. |
| Existing or new assets | Work from a native `.blend`, a deterministic Blender script, or JSON for supported simple assemblies. Preserve useful existing assets. |
| Resumable production | Reuse valid frames, rerender missing or invalid frames, encode and decode-check videos, and export declared project assets with recorded hashes. |
| A quiet interface | A large model canvas, contextual tools, dark/light/system themes, and English, Simplified Chinese and Traditional Chinese interface text. |

The workflow is **request → agent prepares → focused review → agent applies → Blender renders**. Reviews are useful where visual judgment matters; they are not required for every production step.

## Try it

You need a locally running agent host that can read skills, edit files and execute Python/Blender commands. **Codex is the documented installation target.** Other hosts may use the CLI or optional MCP adapter, but their integration is not verified here.

You also need Python, Blender, a WebGL-capable browser, and the Python dependencies below. FFmpeg is required for video output; `imageio-ffmpeg` can supply its executable. Use the same Python environment for setup and subsequent agent commands.

From a directory where you keep source code:

```sh
git clone https://github.com/Jack-ItsMe/Blender2Easy.git
cd Blender2Easy
python -m pip install -r skills/blender2easy/scripts/requirements.txt
python skills/blender2easy/scripts/animation.py doctor
python scripts/install.py
```

`doctor` reports dependencies without installing anything. Resolve any `MISSING_DEPENDENCIES` before rendering. The installer copies the skill to your Codex skills directory; see [setup details](docs/getting-started.md) for paths and a manual installation.

In a Codex chat where the installed skill is available, try:

> Use $blender2easy to create a short animation of a hinged box opening. First prepare the model and motion. If my judgment is needed, open a focused review for the opening angle and pause. Render a preview before the final video.

For a quick look without an agent:

```sh
python skills/blender2easy/scripts/animation.py init work/box-demo --template box
python skills/blender2easy/scripts/animation.py editor work/box-demo/project.json --open
```

Keep the server running. Without an agent-created review, the default page is a read-only preview. The `box` and `lamp` templates are learning examples, not limits on what an agent can author in Blender.

## Know the boundaries

- **Three.js is an inspection preview.** Its materials, interpolation and measurements may differ from Blender. Snapping follows supported visible preview geometry, not analytic CAD geometry. Final appearance and motion need Blender evidence.
- **Diagnostics check declared conditions.** They do not infer the correct mechanism, guarantee collision freedom, or prove faithful reconstruction from a photograph.
- **Feedback is a saved proposal.** Submitting a review does not directly save the candidate into the project or start a render. After the agent's turn ends, return to the chat and ask it to continue; browser feedback cannot wake it automatically.
- **Complex scene editing remains Blender work.** Arbitrary shaders, rigs, physics and compositor behavior are not fully reproduced or editable in the browser.
- **Local tools do not imply a local language model.** The browser server binds to loopback and its UI assets load locally. Your agent host/model has its own network, data-handling and billing behavior. External asset services have separate access and licensing requirements.

## Explore further

- [Getting started and troubleshooting](docs/getting-started.md)
- [Example prompts and a reproducible template walkthrough](docs/examples.md)
- [CLI workflow](skills/blender2easy/references/workflow.md)
- [Review contract](skills/blender2easy/references/review.md) and [preview behavior](skills/blender2easy/references/editor.md)
- [Diagnostics](skills/blender2easy/references/diagnostics.md), [quality tools](skills/blender2easy/references/quality-tools.md) and [optional MCP](skills/blender2easy/references/mcp.md)

## Acknowledgments

Blender2Easy adapts specialist workflows and tools from [Blender Agent Studio](https://github.com/ifBars/blender-agent-studio) by Bars, from commit [`748b18b`](https://github.com/ifBars/blender-agent-studio/tree/748b18ba4cbb5df6fc1da854e00e4c3526fdd128). The bundled source retains its attribution and records upstream hashes and local changes in [PROVENANCE.json](skills/blender2easy/vendor/bas/PROVENANCE.json).

The preview uses Three.js and bundled interface fonts. See [third-party notices](skills/blender2easy/THIRD_PARTY_NOTICES.md) for the included components and their licenses. Blender2Easy is an independent project and is not affiliated with or endorsed by the Blender Foundation.

Blender2Easy's original code is available under the [MIT License](LICENSE). Bundled components retain their own notices.

Bug reports, platform checks and small reproducible examples are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md).
