# Fixed quality tools

Use these adapters when the task needs evaluated inspection, selected evidence views, a reference comparison, camera fitting, authored rendering or local animated-FBX import. They preserve the input asset and write a separate output. For workflow selection, read only the relevant [specialist](specialists.md).

```text
python <skill>/scripts/animation.py quality catalog
python <skill>/scripts/animation.py quality run TOOL --spec spec.json --timeout 300
```

The adapters need Python and Blender; Blender supplies numpy. They do not need MCP, Bun, Node, Rust or a network connection. Blender resolves through `--blender PATH`, `ANIMATION_BLENDER`, PATH or the platform resolver. Default wall timeout is 300 seconds; the range is 1–7200 seconds.

## Common spec and provenance

Every spec has `input` and `outputDir`. Relative paths resolve against the spec file's directory. Normally `outputDir` must not exist, including an empty directory; [verified reuse](#reuse-a-completed-run) is the explicit exception. The output contains `payload/`, `blender.log` and `provenance.json`.

`reference`, `camera-fit` and `authored-render` accept `.blend`. `mixamo-import` accepts only `.fbx`. The other tools accept `.blend`, `.glb`, `.gltf`, `.fbx` and `.obj`. Optional `dependencies` names up to 128 existing files to fingerprint; it does not discover or relink resources. `dependenciesComplete` is a boolean assertion used for reuse.

Unknown fields and arbitrary Python/argument passthrough are rejected. The spec, input, explicitly supplied images and declared dependencies receive before/after SHA-256 fingerprints; changed inputs invalidate the run. Outputs, adapter code, fixed vendored scripts and the Blender executable are also fingerprinted. Failed/timed-out runs retain logs and provenance.

CLI exit 0 with `status: complete` means the fixed script produced its report and the declared inputs stayed unchanged. Read that report's issues, hard gates, metrics and images before deciding whether the asset meets the task. Completed inspections can contain failed asset gates. Runtime failure/timeout returns 1; invalid specs or setup errors return 2.

## Tool-specific fields

| Tool | Additional spec fields | Report / output |
| --- | --- | --- |
| `inspect` | `frame` | `metrics.json`: evaluated mesh statistics, materials, actions and hard gates |
| `topology` | `frame`, exact `object`, `limit` (1–100) | `topology.json`: bounded ranked degenerate faces/edges and witnesses |
| `motion` | Required increasing `frames` (2–12), exact mesh `targets` (1–8) | `motion.json`: evaluated geometry hashes, transforms, modifiers and cache evidence |
| `scene-ir` | `frame` | `scene-ir.json`: upstream portable scene representation; use [diagnostics](diagnostics.md) for local relationship/report/compare rules |
| `evidence` | `frame`, `frames` (1–32), `views`, `resolution` (128–1024), `presentation`, `materialMode`, `hideObjects`, `headTexture` | `evidence.json`, fixed views/contact sheets; `frame` selects the main multiview pose |
| `reference` | Required `reference`; optional reviewed `mask`, `camera`, `frame`, `maxEdge` (128–1024), `landmarks` | `comparison.json` and reference/silhouette/overlay panels |
| `camera-fit` | Required `width`, `height` (1–8192), `landmarks` (3–32); optional `camera`, `frame` | New `camera-fit.blend`, `camera-fit.json`; fits lens/scale/shift with camera position/orientation and geometry fixed |
| `authored-render` | `inspectOnly`, `scene`, exact `cameras` (up to 6), `frames`, `maxEdge` (128–4096), `samples` (1–1024), `timeLimit` (1–600), `device`, `denoise` | `render-manifest.json` and at most 12 total camera/frame PNGs |
| `mixamo-import` | Required `clipName` (1–120 chars); `fps` (24/30/60, default 30) | `mixamo-import.json` and new `animation.blend`; imported skeleton/actions, no retargeting |

```json
{"input":"assembly.blend","outputDir":"quality/motion-01","frames":[1,24,48],"targets":["hinge","lid"]}
```

```json
{"input":"assembly.blend","outputDir":"quality/reference-01","reference":"front.png","mask":"front-mask.png","camera":"Reference_Front","frame":24,"maxEdge":512,"landmarks":[{"name":"top-left","objectName":"lid","localPoint":[-1,0,1],"referenceUv":[0.25,0.2]}]}
```

Landmark UVs are normalized from the image's top-left corner. Camera fitting needs at least three spatially separated correspondences. `reference` reports projection metrics only with an explicit reviewed foreground mask; it does not invent segmentation, image similarity, pose estimation or hidden geometry. Inspect the overlay before retaining a camera-fit candidate, then carry accepted parameters into the [durable source](source-delivery.md).

Allowed choices:

- `views`: `perspective`, `front`, `back`, `left`, `right`, `top`.
- `presentation`: `auto`, `neutral`, `dark`, `light`.
- `materialMode`: `source`, `vrchat-fit` (diagnostic styling).
- `device`: `auto`, `cpu`, `OPTIX`, `CUDA`, `HIP`, `METAL`, `ONEAPI`.
- `denoise`: `preserve`, `preview`, `final`, `off`.

For imported motion, inspect poses and use the report's actual frame range/FPS; FBX import may shift the frame origin. See [asset handoffs](asset-handoffs.md) when acquisition or import settings are part of the task.

## Reuse a completed run

```text
python <skill>/scripts/animation.py quality run evidence --spec evidence.json --reuse
```

Reuse is opt-in and requires `dependenciesComplete: true` in the original spec. Set it only after establishing that the asset is self-contained/packed or all external dependencies are listed. This is the caller's assertion, not automatic discovery.

A missing output directory still executes the first run. Existing output must match the completed manifest, exact spec/inputs/dependencies, adapter and worker code, Blender binary, log and full payload inventory. A changed/missing/extra artifact, failed/partial run or legacy manifest rejects reuse without overwriting or running Blender. A hit returns `reused: true` and leaves prior evidence intact. For an intentional revision, use a new spec/output directory.

## Evidence use and limits

Completed `inspect`, `topology` and `reference` runs can feed source-bound findings/images into a user review through their `provenance.json`. Read [the quality evidence bridge](review.md#bas-quality-results-in-the-same-review) when preparing that interaction; these tools do not by themselves require user review.

Fixed scripts and disabled embedded scripts are not an operating-system sandbox. Evaluation can require substantial memory despite output and time bounds. Bounds overlap, sparse motion samples and cache-file presence do not prove exact contact, continuous collision freedom, complete bake coverage or aesthetic quality. Apply only the checks relevant to the [delivery contract](source-delivery.md).
