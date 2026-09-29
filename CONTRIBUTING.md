# Contributing

[简体中文](CONTRIBUTING.zh-CN.md) · [Back to README](README.md)

You can help Blender2Easy with a reproducible bug report, clearer instructions, a platform check, a focused fix or a small example. You do not need to start with a large code change.

## Start here

1. Check [open issues](https://github.com/Jack-ItsMe/Blender2Easy/issues) for related work. Add useful evidence to an existing issue instead of opening a duplicate.
2. For a substantial capability or behavior change, open an issue first to discuss the user task, proposed scope and how to verify it. Small fixes can go directly to a pull request.
3. For public contributions, fork the repository into your own account and work on a branch. You do not need write access to this repository to propose a pull request from a fork.

Replace `YOUR-USERNAME` and choose a branch name that describes your change:

```sh
git clone https://github.com/YOUR-USERNAME/Blender2Easy.git
cd Blender2Easy
git switch -c fix/short-description
python -m pip install -r skills/blender2easy/scripts/requirements.txt
```

Make one focused change, run the relevant checks below, then commit and push your branch to your fork. Open a pull request targeting this repository's default branch. Explain the problem, resulting behavior and evidence; link the related issue if there is one. A small, reviewable pull request makes it easier to understand and discuss the change.

## Report a problem

Include:

- OS, Python, Blender and browser versions, plus `animation.py doctor` output.
- The command or agent request, expected behavior and actual result.
- A minimal project or steps that reproduce the issue; a screenshot for visual problems.
- Whether it happens in the browser preview, a Blender render, a saved review or an exported delivery.

Remove private file paths, credentials and assets you cannot redistribute. A tiny scene that reproduces a problem is more useful than an unexplained large `.blend`.

Use the [platform check form](https://github.com/Jack-ItsMe/Blender2Easy/issues/new?template=platform-check.yml) to report an environment you tried. Record exact versions and distinguish automated tests from actually opening the preview or inspecting a Blender render. A passing CI run alone does not verify a platform's full interactive or rendering workflow.

## Work on the code

Start with [getting started](docs/getting-started.md). Develop in the repository copy; your installed skill is a separate copy.

| Location | Purpose |
| --- | --- |
| `skills/blender2easy/SKILL.md` | Agent entry point and reference routing |
| `skills/blender2easy/scripts/` | CLI, production, diagnostics, review contracts and optional MCP |
| `skills/blender2easy/editor/` | Local server and browser interface |
| `skills/blender2easy/references/` | Operation-specific instructions and schemas |
| `skills/blender2easy/vendor/bas/` | Attributed upstream source and adaptations |
| `docs/` | User-facing guides and demonstration media |

Keep changes focused on a reproducible problem. Explain the trigger, resulting behavior and validation in the pull request. For interface changes, include before/after screenshots at a desktop and narrow width, and check English, Simplified Chinese and Traditional Chinese where affected.

The important workflow boundaries are:

- Viewing, picking and measurement must not mutate the model.
- A review can change only its declared fields and must reject stale source/response identities.
- Browser display is approximate; final Blender output and diagnostic evidence need their own checks.
- Existing asset sources and unrelated confirmed properties should remain intact.
- Cached outputs can be reused only when their recorded inputs and files remain valid.

Run the repository checks with Python 3.11+ and Node.js 22+:

```sh
python scripts/check.py --require-node
```

The default suite does not launch Blender. `--python-only` runs only Python tests; without `--require-node`, a missing Node executable skips the frontend checks. Optional `--with-blender` runs a small Blender integration fixture. Optional `--with-mcp` runs SDK integration checks after installing `skills/blender2easy/scripts/requirements-mcp.txt`.

Also exercise the affected CLI operation or review flow with a small fixture; inspect real Blender output when a change affects geometry, animation or rendering. Report what you ran, what passed, any skipped checks and what remains untested. Avoid expensive full renders when a few frames answer the question.

## Documentation and upstream code

Keep both READMEs consistent for user-visible features and limitations. Label screenshots and videos as preview, prepared example or final render. Do not present a successful encode or numerical check as proof of visual accuracy.

Bundled BAS files have recorded upstream hashes and local adaptations in [PROVENANCE.json](skills/blender2easy/vendor/bas/PROVENANCE.json). Preserve attribution and update the relevant provenance records when changing that code. Keep unrelated upstream refreshes separate from feature fixes.

## Before opening a pull request

- Keep the diff focused and explain the behavior it changes; link an existing issue when relevant.
- List validation commands, results and skipped or untested paths. Documentation-only changes need link and command review, not an unrelated render.
- Include relevant UI screenshots and language/viewport checks, and update affected English and Chinese documentation.
- Keep private paths, credentials, local projects and generated caches out of the contribution. Preserve third-party attribution and recorded provenance.
