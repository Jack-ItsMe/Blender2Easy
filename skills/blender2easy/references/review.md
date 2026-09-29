# Agent-directed visual review

Use a review when the user needs to judge or refine a concrete part of a prepared result. First translate the animation request into meaningful segments, prepare the result for the current stage, and choose an initial solution. If the user wants to confirm the model before animation work, prepare that model review first. The agent handles requirements that are already clear. Avoid opening an empty editor or asking the user to make every production decision.

## Choose the current adjustment

State one useful question and focus the relevant segment, objects, source frame and camera. Offer a small number of natural controls, ordinarily one to four, with sensible ranges. Model, motion, camera and delivery are stages of one shared workflow:

| Stage | Possible judgment | Scope example |
| --- | --- | --- |
| `model` | Does the prepared object have the intended proportions and appearance? | Selected dimensions, component position, color |
| `motion` | Is the action clear and paced correctly? | Relevant pose value, action timing or pause |
| `camera` | Does this shot show the important detail? | Selected framing or camera values |
| `delivery` | Does the prepared result suit its destination? | Explicit resolution, frame rate or shot duration |

These examples do not confer stage-wide permission. Every editable leaf must be listed in `controls`; the same stage can have different controls for different objects. If a later correction requires changing the confirmed model, prepare a new model review for that change. Do not force unrelated products into the box/lamp examples.

## Create the request

Write a JSON spec after inspecting the normalized project. The spec contains `title`, `question`, `context`, `stage`, `segments`, `focus` and `controls`. Segments describe the story and source frame ranges; focus identifies the part under review. Control bindings use JSON Pointer paths into existing leaves of the frozen normalized project. Resolve actual object, shot and camera IDs from that project; do not guess IDs or copy example paths without checking them.

Set optional top-level `ui_language` to the current conversation's main language:
`"zh-Hans"` for Simplified Chinese, `"zh-Hant"` for Traditional Chinese, or `"en"`
for English. For example, include `"ui_language": "zh-Hans"` in a review prepared
for this Chinese conversation. Common locale aliases such as `zh-CN`, `zh_TW`
and `en-US` normalize to those three values. This field travels through the normal
`--spec`/`create_request` flow and is frozen with the request; it does not translate
titles, questions, object labels, IDs, or project content. Unsupported values are
rejected. Omitting it preserves legacy requests.

Generated review links carry `context_lang` as the conversation default, including
when reopening a request or using a custom server port. It differs from an explicit
`lang` URL override: a user's saved manual language selection takes precedence over
the conversation default. With language set to automatic and no conversation
context, the browser language remains the fallback. Pass the actual conversation
language rather than guessing it from the browser or the example project.

Each segment has `id`, `title` and `source_range: [first, last]`. Focus requires `shot_id`, `segment_id`, `object_ids`, `source_frame`, `source_range` and `camera_id`. Its range must lie inside the selected shot and include the selected segment; its frame must lie inside that range. Optional `focus.object_labels` maps real object IDs to readable display names, for example `{"shade": "灯罩"}`; labels are 1–80 characters, at most 30 mappings are accepted, and every ID must exist. This changes display names only, preserving canonical IDs in bindings and feedback. Optional `media: {"path": "..."}` attaches an existing PNG/JPG/MP4, useful for delivery review of a real rendered result. Media paths resolve relative to the project directory or may be absolute.

Check the semantic reach of each binding before freezing the request. A material color can be shared by several objects even when the page focuses on one. If only the lampshade should change, inspect material reuse and, when necessary, prepare an independent material with the same initial appearance for that part before creating the review. Binding validation limits JSON writes; it cannot infer whether a shared material also changes parts the user intended to keep unchanged.

For a prepared hinged-object scene, a number control might map an intuitive positive opening angle to negative X rotation at two existing key poses:

```json
{
  "id": "opening",
  "label": "打开角度",
  "kind": "number",
  "unit": "°",
  "min": 60,
  "max": 120,
  "step": 1,
  "value": 108,
  "bindings": [
    {"path": "/scene/animation/0/keys/2/value/0", "scale": -1, "offset": 0},
    {"path": "/scene/animation/0/keys/3/value/0", "scale": -1, "offset": 0}
  ]
}
```

This is a binding example, not a universal scene schema or complete spec. Choose the semantic parameters that fit the object and action. For unsupported semantic edits, the agent should prepare the change in Blender or JSON and issue another focused request.

Number controls enforce finite minimum, maximum, step and optional binding scale/offset. Color controls map `#rrggbb` to an existing color vector while preserving alpha. Choice controls provide `options: [{"value": "...", "label": "..."}]`, a default `value`, and a `choices` map in each binding from every option value to its stored scalar/vector. A request permits at most 12 controls. Any stage may use `controls: []` for a visual-only confirmation or mismatch report; this grants no parameter writes. Avoid filling that limit simply because fields are available. Bindings must be permitted both for the stage and the listed leaf: model allows eligible transforms/dimensions/materials, motion allows existing key poses and shot timing, camera allows eligible framing and shot-camera choices, and delivery allows output settings and timing. They cannot replace whole objects/arrays, change asset/source paths or object IDs, alter parent links, or create unrestricted write access.

## Reference evidence and precise locations

An optional `evidence` object attaches up to six existing PNG/JPG reference images and up to twelve named pose checkpoints. Inspect the project first and use its actual camera/object IDs. Example shape:

```json
{
  "references": [{"id": "folded-photo", "title": "折叠参考", "path": "references/folded.jpg"}],
  "checkpoints": [{
    "id": "folded", "title": "折叠", "source_frame": 1,
    "camera_id": "Camera", "reference_id": "folded-photo",
    "object_ids": ["tray"]
  }]
}
```

This is the value of `spec.evidence`, not a complete request. Reference files are resolved relative to the project or may use absolute paths, then frozen by SHA256. Checkpoint source frames are integers within the frozen focus range; checkpoints name an existing camera and attached reference, and may focus only a subset of `focus.object_ids`. Checkpoints navigate an existing pose/view; they do not change parameters or expand permissions. References can be supplied without checkpoints.

The page receives `reference_urls` for the frozen images. In the comparison view, choosing a checkpoint shows its reference and jumps to the specified frame/camera. Clicking the actual image can record `annotation.reference_id` and `annotation.reference_uv: [u,v]`, normalized from the image's top-left corner. The receipt may also contain `annotation.checkpoint_id` together with the exact `source_frame`, and the existing optional `object_id` identifies a model part. A reference mark is a location, not proof of agreement or an automatic geometry correction.

A checkpoint annotation must match that checkpoint's frame and, if supplied, its reference ID. Invalid IDs or out-of-image coordinates are rejected. Reference changes invalidate the frozen review just as source changes do; create a new request after revising the evidence. Existing requests without evidence retain their original behavior.

For a native Blender model with unsupported structural or keyframe edits, use an empty control list and a concrete comparison question. Read the submitted reference mark, object/frame and note, then edit the source in Blender and issue a fresh scoped review when another judgment is needed. Do not invent a live slider that cannot produce the promised model change.

## Diagnostic findings

Attach a completed [diagnostic report](diagnostics.md) to the same `evidence` object:

```json
{
  "reports": [{"path": "inspection/findings.json", "finding_ids": ["ACTUAL_REPORT_FINDING_ID"]}]
}
```

Read the report and use its real finding IDs. `finding_ids` is optional: without it, attachment selects non-`info` findings and informational changes marked `review_required` whose nonempty object list is wholly inside `focus.object_ids` and whose frame is in the focus range. An explicit selection may include `info` but rejects a finding outside that scope. The request permits at most four reports and 24 total findings. Diagnostic reports use `object-animation.diagnostic-report/1`; the explicit quality bridge below accepts completed BAS adapter provenance. JSON files are limited to 8 MB and paths resolve relative to the project directory or as absolute paths.

The report must describe this project's unchanged native source with no overrides, or a current successful build whose recorded inputs match the project. Diagnose the built `.blend` when procedural geometry or overrides affect the shown result. Attaching an unrelated asset's report is rejected. Reports, current sources, snapshot files and a supplied contract are hash-bound to the review. A historical comparison may retain the before snapshot after its original asset has changed; its current after source must still match. Changing any frozen evidence requires a new report/request.

The page shows each selected finding as a location shortcut to its source frame, camera and first object. Its title and severity are copied from the report; numerical details and the `hard`/`review_required` distinction stay in the original report. Read those details before asking a question. Finding IDs are namespaced on attachment, with the original IDs retained in the frozen `finding_map`. Feedback refers to the frozen ID as `annotation.finding_id` and must carry that finding's exact `source_frame`.

For an agent-observed visual mismatch, `evidence.findings` may instead contain an authored item with `id`, `title`, `severity` (`info`, `warning` or `error`), nonempty `object_ids`, `source_frame`, `camera_id`, and optional attached `reference_id`. The objects must lie inside the review focus, the frame inside its range, and the camera/reference must exist. Label the observed issue factually; an authored item has no automated diagnostic provenance. Findings locate a question and grant no parameter writes. They describe the frozen baseline and are not automatically rechecked after a control changes or feedback is applied.

## BAS quality results in the same review

For completed `quality run inspect`, `topology` or `reference`, add an explicit
quality entry pointing to `provenance.json`, not the raw report:

```json
{"reports":[{"kind":"quality","path":"quality/reference-01/provenance.json"}]}
```

The bridge verifies the completed run, unchanged inputs, report and all recorded
outputs, and binds the input asset to this project's current build/source.
Changing a frozen input, image, report or build record invalidates the review.
Explicit `finding_ids` use original report positions such as `landmark:0`,
`topology:0` or `inspect:0:non_manifold_edges`; inspect the source report first.
Out-of-scope objects/frames are rejected for explicit selection and skipped for
automatic selection. Findings get immutable namespaced IDs after attachment.

Reference comparisons attach the normalized reference and projected overlay,
one recorded camera/frame checkpoint, and factual landmark pixel-offset findings.
The report's camera must match the focus camera. Offsets invite judgment; no
unrequested tolerance or automatic geometry repair is inferred. Inspect/topology
use reported object names and frame; their camera is only review navigation, not
camera-calibrated diagnostic evidence. Element indexes/world centers stay in
the full report and are not converted to invented Three.js surface points.

For native multi-scene assets, direct `inspect` evidence must name the selected
scene and include declared dependencies. Topology/reference do not record scene
identity, so run them on the verified project build. Existing image/checkpoint/
finding limits still apply. Other quality tool reports are not yet normalized
by this bridge and must be read through their returned reports/artifacts.

The finding trail visibly identifies evidence from the original. After parameter
changes it labels the candidate as unchecked; comparing the original or resetting
parameters restores the original indication. This does not run diagnostics in
the browser. After applying changes, rerun the relevant check on the new build.

## Scoped surface inspection

An optional top-level `inspection` object enables only the tools useful for the current question:

```json
{
  "tools": ["point", "measure", "isolate", "xray"],
  "object_ids": ["ACTUAL_FOCUSED_OBJECT_ID"]
}
```

Replace the example ID with the inspected project's real ID. The list permits 1–30 unique objects, all inside `focus.object_ids`; tool names must be unique and drawn from these four values. Omit tools that do not help. This is viewing/annotation scope, separate from `controls` and their write bindings. The clean page hides inspection tools for delivery reviews.

`point` records one surface location; `measure` records two and their straight-line distance. `isolate` and `xray` change the permitted objects' preview presentation. They do not edit Blender geometry, create cut sections, resolve collisions or expose unrestricted transforms. Point picking requires a current valid preview, and changing frame or relevant preview values clears obsolete picked points.

Feedback stores one or two `annotation.points`, each with an allowed `object_id` and three-component `local` and `world` preview coordinates, plus the exact `source_frame`. The server marks `coordinate_space: "three-preview"`. For parameterized scenes, it expresses the distance in meters and adds `display_distance`/`display_units` using the frozen project's units; native GLB assets retain `preview_world_units`. Every measurement remains `verified_geometry: false`: coordinates supplied by the browser are annotation evidence, not authenticated Blender geometry or an engineering clearance result. Verify any consequential dimension or contact in evaluated Blender geometry before treating it as established.

Surface feedback also records `preview_variant: original|candidate`. The server
derives `sampled_values` from the frozen original controls or validated candidate,
separately from the proposed `values`. This prevents an original-view measurement
being mistaken for a measurement on adjusted geometry. Older clients without the
field default to candidate. The field does not authenticate browser coordinates.

## Publish the prepared review

Create the request through the main CLI:

```text
python <skill>/scripts/animation.py review create PROJECT --spec SPEC --thread THREAD_ID --open
python <skill>/scripts/animation.py review create PROJECT --spec SPEC --diagnostics REPORT --thread THREAD_ID --open
```

`--diagnostics` may be repeated for up to four reports and adds them to `evidence.reports`; use the JSON form when selecting specific findings. `--port` selects the preview server port (default 8766).

`--thread` defaults to the caller's `CODEX_THREAD_ID`; explicitly override it only to bind the intended current task when necessary. The thread ID is routing context, not permission to send messages to another task, and this command sends none. A subagent must not substitute its own thread ID for the controlling agent's task. `--open` opens the clean preview. The server and CLI share the same project and review state.

Creation freezes the normalized project, disk revision, asset fingerprints, focus and permitted bindings under the project's `.animation/review` directory. A new current request can supersede an earlier request without deleting its record. The page cannot invent controls or submit arbitrary project JSON.

## Receive and continue

Use `review status` to inspect a pending request or saved response. After inviting a visual adjustment, use `review wait` with bounded waiting intervals while remaining responsive to the current conversation. The page uses the wait heartbeat to indicate whether the agent is currently listening; server availability alone does not mean the agent is waiting.

```text
python <skill>/scripts/animation.py review status PROJECT
python <skill>/scripts/animation.py review wait PROJECT --request REQUEST_ID --timeout 30
python <skill>/scripts/animation.py review open PROJECT --port 8766
```

`wait` accepts 0–60 seconds and acknowledges receipt when it returns submitted feedback. A `status` read does not mark feedback received. Use the returned request ID and response digest for subsequent operations. `wait`, `apply` and `close` check the caller's task binding through `CODEX_THREAD_ID` or an explicit matching `--thread`.

The user submits one of two decisions: `confirm` with optional notes, or `revise` with a required description of what needs further work. The durable response includes the request/task/project/revision identity, values, exact before/after changes, stage, focus, optional finding/reference/surface annotation and note. A submission only records the proposed result. It does not modify the project. Identical repeated submissions are idempotent; different submissions to a completed response are rejected.

Read the whole compact response, including notes and annotation, before taking the next action:

- For confirmed values consistent with the user's request, run `review apply` to apply that immutable response. Revalidate the result and inspect an appropriate Blender preview when visual correctness requires it.
- For `revise`, interpret the note and location, make the required prepared revision, then create a new bounded request if another judgment is needed. A revise response is never automatically applied.
- Use `review close` when the adjustment is no longer needed; preserve the response history.

```text
python <skill>/scripts/animation.py review apply PROJECT --request REQUEST_ID --response RESPONSE_DIGEST
python <skill>/scripts/animation.py review close PROJECT --request REQUEST_ID --message "已根据备注准备下一版"
```

Application requires the exact response digest the agent read. It checks that the response belongs to the current request, matches its digest, original disk revision and source asset fingerprints, stays inside the frozen bindings, and produces a schema-valid project. It writes atomically under the project lock and archives the previous JSON. If the source project changed, inspect the new state and prepare a new request instead of forcing a stale response onto it. Repeated application of the same accepted response is idempotent or explicitly reported as already applied.

After applying a change, check adjacent animation segments and relevant framing, and rerun affected diagnostic checks before describing an old finding as resolved. The agent continues the existing preview/render/verify production workflow; review confirmation is not evidence that a final video has been rendered or checked.

## When the agent is not actively waiting

Feedback persists across page reloads and the end of the agent turn. If a wait has expired, the page reports that the feedback is saved and asks the user to return to the bound task to continue. On the next turn, check `review status` before generating another request. Preserve unanswered feedback rather than silently superseding it.

The current integration does not automatically wake a finished desktop turn. A `codex://threads/<thread-id>` link opens the existing task; it does not send a prompt. Do not simulate an agent reply, equate an HTTP save with agent receipt, spawn a second CLI agent on the same live thread, or create recurring automation to conceal this limitation. The available CLI actions are `create`, `status`, `wait`, `apply`, `close` and `open`; consult their `--help` for the installed flags.
