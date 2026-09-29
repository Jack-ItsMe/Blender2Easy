---
name: blender2easy
description: Create or revise physical-object models and presentation animations in Blender, including existing assets, reference matching, scoped Three.js review, and resumable verified rendering.
---

# Blender2Easy

Use this workflow when Blender fits the request. Preserve useful assets and the user's chosen deliverable. Keep object-specific design and geometry in the project.

Choose the durable source that fits the work: parameterized JSON for supported simple assemblies, native `.blend` for existing or manually authored assets, and deterministic scripts for new procedural generation. Do not rebuild an existing asset merely to change its source format. Apply [source and delivery rules](references/source-delivery.md) when choosing or revising that contract.

Preserve a supplied target's identity, proportions, component relationships and mechanism. Distinguish observed structure from inferred dimensions. For reference-led work, read [reference fidelity](references/reference-fidelity.md) and compare matching views and critical poses before polish. For animation, divide the requested story into meaningful segments and inspect continuous motion when still frames cannot establish the behavior.

Make decisions already settled by the request. Resolve consequential ambiguity before dependent work while continuing independent preparation. For a visual judgment or requested adjustment, prepare a concrete result and a scoped review exposing its question, object/frame/camera focus and only the permitted controls. Viewing and annotations grant no model writes. Read saved feedback before continuing an existing review. Read [the review contract](references/review.md) when creating, receiving or applying one; use [the preview guide](references/editor.md) for browser startup or explicitly requested authoring access. A finished agent turn is not automatically awakened by browser feedback.

When creating a review, set `ui_language` from the user's current conversation language (`zh-Hans`, `zh-Hant` or `en`). Write agent-authored titles, questions, control labels and object display labels in that same language; preserve source object IDs and user-provided content. A browser's language is only a fallback when conversation context is unavailable.

Treat Three.js as an inspection preview: its shading, interpolation and measurements are approximate. Inspect actual Blender images and relevant motion before claiming visual correctness. A decoded video, passing numerical check or user confirmation establishes only what that evidence covers. Recheck affected evidence after an edit and preserve explicit invariants outside its scope.

Read only the references needed for the current operation:

| Need | Read |
| --- | --- |
| Set up, render or resume a project | [Command workflow](references/workflow.md); start with `scripts/animation.py doctor` |
| Author project fields | [Project format](references/project-format.md) |
| Model, rig, simulate, render or refine with specialist guidance | [BAS routing](references/specialists.md) |
| Inspect evaluated structure, relationships or before/after invariants | [Diagnostics](references/diagnostics.md) |
| Run fixed inspection, reference, evidence or import tools | [Quality tools](references/quality-tools.md) |
| Connect a host through optional MCP | [MCP adapter](references/mcp.md) |
| Find external materials, audio or motion assets | [Asset handoffs](references/asset-handoffs.md) |
| Recover interrupted work, verify caches or transfer assets | [Validation and recovery](references/validation.md) |

Resume with the existing project and recorded artifacts. Production reuses valid frames; optional quality-tool reuse requires verified unchanged inputs and outputs. `verify` checks the last delivered version, not later unrendered edits. Report exact artifact paths, evidence scope and any unfinished work.
