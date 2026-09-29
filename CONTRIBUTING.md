# Contributing

Thanks for helping make Blender2Easy easier to use and inspect. Useful contributions include small reproducible bug reports, clearer setup instructions, platform verification, focused interaction improvements and examples with explicit evaluation criteria.

## Report a problem

Include:

- OS, Python, Blender and browser versions, plus `animation.py doctor` output.
- The command or agent request, expected behavior and actual result.
- A minimal project or steps that reproduce the issue; a screenshot for visual problems.
- Whether it happens in the browser preview, a Blender render, a saved review or an exported delivery.

Remove private file paths, credentials and assets you cannot redistribute. A tiny scene that reproduces a problem is more useful than an unexplained large `.blend`. Windows is currently tested; label macOS/Linux reports with the exact environment rather than assuming platform-wide support.

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

For a substantial new capability, open an issue describing the user task, how it fits the current workflow and how it can be verified. Small fixes can go directly to a pull request.
