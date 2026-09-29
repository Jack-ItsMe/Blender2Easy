# Durable source and delivery contract

Choose source and deliverables from the user's task and existing assets. These rules govern bundled specialist instructions where their default Python/GLB workflow would expand that scope. A technical capability is not a requirement to use it.

## Choose the source mode

| Work | Durable source | How to revise it |
| --- | --- | --- |
| A supported simple assembly with parameterized transforms/materials | Project JSON and its declared assets | Edit validated fields; generated Blender builds remain derived artifacts. Use [project format](project-format.md) for supported geometry and bindings. |
| An existing or manually authored Blender asset | Native `.blend`, its dependencies, and any local patch scripts needed to repeat scripted edits | Preserve a baseline and edit a separate candidate or project overrides. Retain authored geometry, rigs, modifiers, materials and animation unless the task changes them. Do not reconstruct the whole asset as Python merely to satisfy a specialist's default. |
| A newly generated procedural asset | Deterministic generation script, configuration/seeds and required input assets | Regenerate candidates from the script in a clean Blender process. Record relevant executable/version and inputs; carry accepted changes back into this source. |

Hybrid projects may use more than one mode. State which source owns a component or edit so later regeneration cannot silently discard it. A Blender scene can remain the durable source for manual modeling; a patch script need only reproduce its local change, not reconstruct unrelated assets.

Keep source and dependencies sufficient to reopen or regenerate the contracted result. Pack resources or record external files where appropriate; linked libraries, textures and simulation caches need explicit coverage. A source-file hash alone does not verify its external dependencies. Do not overwrite the only usable baseline while testing a candidate.

## Deliver what the task requires

| Contract | Required evidence and handoff |
| --- | --- |
| Image or video | The requested media, its applicable render/encoding evidence, and any source handoff the user requested. Inspect actual images; inspect continuous playback when timing or causality matters. No GLB export is required solely for this task. |
| Editable native scene | The requested `.blend`/project/script with dependencies and relevant reopening or regeneration checks for its source mode. State unresolved portability limits. |
| Exported asset | The user's requested format and relevant source/evidence. Re-import that format in a clean process and check the properties needed downstream: geometry, scale, materials, hierarchy, actions or deformation as applicable. GLB is required only when selected by the contract. |
| Focused repair | The accepted source revision and evidence that the requested defect improved while explicit preservation constraints still hold. Additional delivery formats follow the existing contract. |

Rendering may internally create a GLB for the browser preview. That transport artifact does not add a user-facing GLB delivery or export-quality promise. Likewise, successful encoding and numerical gates do not establish reference fidelity or visual quality.

## Scope a repair and its recheck

Record the intended change and explicit invariants before editing. Preserve accepted dimensions, relationships, appearance, motion or exports outside the changed scope. Revisit affected construction stages and evidence; do not repeat an unrelated full pipeline because a specialist lists a general completion checklist. An edit with broad effects, such as rigging, shared materials or export-sensitive modifiers, may require broader checks—choose them from its actual dependencies.

Use the same relevant views, poses and constraints for before/after comparison. Preserve a historical snapshot when using [revision diagnostics](diagnostics.md), and rerun current checks after the source changes. Retain a repair only when the scoped evidence supports it; disclose remaining uncertainty instead of promoting a preview annotation or partial check to a complete validation.

For direct Blender helper scripts, inspect their arguments and use a new candidate/output. The batch invocation pattern is `--background --factory-startup --disable-autoexec --python-exit-code 17 --python SCRIPT -- ...`. This disables embedded scripts; it is not an operating-system sandbox. For production recovery and cache reuse, read [validation](validation.md).
