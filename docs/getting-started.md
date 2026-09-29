# Getting started

[简体中文](getting-started.zh-CN.md) · [Back to README](../README.md)

## 1. Prepare the environment

Use Python, Blender and a browser with WebGL support. The documented workflow uses a local Codex host with permission to read/write project files and launch commands. The browser is a review surface; it does not contain an agent or language model.

Windows is the tested platform. macOS/Linux commands and discovery paths are present, but those platforms have not yet been verified. MCP is optional and uses a separate dependency set; leave it out for the first run.

The checked Windows environment uses **Python 3.12.14, Blender 5.2.1 LTS and FFmpeg 7.1**. These are tested versions, not a claim that every earlier or later combination works.

Clone into any directory you own, then use one Python environment consistently:

```sh
git clone https://github.com/Jack-ItsMe/Blender2Easy.git
cd Blender2Easy
python -m pip install -r skills/blender2easy/scripts/requirements.txt
python skills/blender2easy/scripts/animation.py doctor
```

If your Python command is `python3`, substitute it throughout. A virtual environment is useful if you want to isolate dependencies; the agent must use that same environment's interpreter.

The dependency file installs Pillow and imageio-ffmpeg. It does not install Blender. `doctor` prints the Python interpreter, discovered tools, versions and readiness status. It is read-only and exits with code 2 when dependencies are missing.

If Blender or FFmpeg is not discovered, put it on `PATH`, set `ANIMATION_BLENDER` / `ANIMATION_FFMPEG`, or pass its path to the commands that support an override:

```sh
python skills/blender2easy/scripts/animation.py doctor --blender "/absolute/path/to/blender"
```

Replace the example with the executable on your machine. `--blender` and `--ffmpeg` are also available on production commands such as `preview` and `run`.

## 2. Install the skill

From the repository root:

```sh
python scripts/install.py
```

The default destination is `CODEX_HOME/skills/blender2easy` when `CODEX_HOME` is set, otherwise `~/.codex/skills/blender2easy`. You can also copy the complete `skills/blender2easy` directory there manually. Preserve its scripts, references, assets and vendor directories together.

The installer does not overwrite an existing installation by default. Use `--replace` to replace it while retaining a backup outside the skills directory; this also migrates an older `object-animation` installation if present. `--dest /path/to/skills` selects a different **parent skills directory**, into which the installer creates `blender2easy`.

Keep the repository checkout if you want to inspect or contribute to the source. The installed copy and the checkout are separate; editing one does not automatically update the other. Open a Codex chat that can discover the installed skill and invoke `$blender2easy`.

Before using `--replace`, stop editor, rendering and MCP processes launched from the old installation. The command backs up the entire old installation outside the skills directory; it does not merge projects into the new copy. If you kept projects under the old `editor/projects`, they remain in the printed backup path. Reopen them with an explicit project path and `--workspace`, or relocate the workspace after stopping its processes. Projects stored outside the installed skill directory remain at their existing paths.

Installing a skill does not configure a model, enable MCP, or install a Blender add-on. Host access to files and commands is still required.

## 3. Start with a small request

> Use $blender2easy to create a short hinged-box opening animation. Prepare a first version, then let me judge just the opening angle and pause in a focused review. Check the Blender preview before rendering the final video.

The agent should prepare the scene before opening a review. In the browser, adjust permitted controls or mark the part that needs attention, then submit. The response is saved locally. The agent must read and apply it; if its turn has ended, return to the same chat and say “Continue with my saved feedback.”

## 4. Try the CLI independently

These commands run from the repository root and create a disposable learning project:

```sh
python skills/blender2easy/scripts/animation.py init work/box-demo --template box
python skills/blender2easy/scripts/animation.py validate work/box-demo/project.json
python skills/blender2easy/scripts/animation.py editor work/box-demo/project.json --open
```

`init` requires a new or empty directory. The editor command keeps running; use another terminal for subsequent CLI commands, or stop the server with Ctrl+C first. The default address is `http://127.0.0.1:8766`. With no review request, the page is read-only.

Render a few actual Blender frames before the full video:

```sh
python skills/blender2easy/scripts/animation.py preview work/box-demo/project.json --shot opening --frames 1,24,48
python skills/blender2easy/scripts/animation.py run work/box-demo/project.json --shot opening
python skills/blender2easy/scripts/animation.py verify work/box-demo/project.json --shot opening
```

Commands report artifact paths as JSON. Use those paths to inspect the stills, video and checks. `verify` checks the last recorded delivery, not newer unrendered edits. Avoid running multiple rendering jobs against one GPU at the same time.

The project keeps builds, reports and caches under `.animation`. Repeating `run` can reuse valid frames. Keep these files to resume work; do not assume an old rendered delivery represents a newly edited project.

## Common questions

**The page is empty or says there is nothing to adjust.** Open a project for viewing. To get adjustment controls, ask the agent to create a review with a concrete question and permitted fields. This is expected behavior without a request.

**Port 8766 is in use.** Start the editor with `--port 8770 --open`, or use the URL returned by the agent. A different port has its own browser display preferences.

**The model looks different from Blender.** The browser uses approximate display behavior. Native scenes are exported to a preview mesh; not every shader, constraint or effect survives that representation. Check actual Blender frames for final judgments.

**I submitted feedback but nothing happened in chat.** The feedback is durable, but cannot wake an agent after its turn ends. Ask the same chat to continue with the saved response.

**The skill is not available in my host.** Check that the installed directory contains `SKILL.md` directly, that the host reads that skill location, and that its Python environment has the dependencies. You can still run the CLI from the checkout to isolate environment problems.

For exact command and schema details, use the [workflow](../skills/blender2easy/references/workflow.md), [review](../skills/blender2easy/references/review.md), and [optional MCP](../skills/blender2easy/references/mcp.md) references.
