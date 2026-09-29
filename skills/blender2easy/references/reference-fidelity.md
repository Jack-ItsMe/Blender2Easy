# Reference-led models and mechanisms

Use this workflow when the user's supplied object, image or existing asset is a target to reproduce or revise. An explicit request for an original design, stylization or alternate mechanism can change that scope; the presence of a reference image alone does not authorize such changes.

## Establish what must remain true

Inspect the actual reference views. Keep a short project-local contract of the observations that determine identity and motion: primary proportions, component arrangement, openings, material regions and, for articulated objects, hinge locations, owning parts, axis directions, contacts and folded nesting. Tie each important relationship to a reference view or crop. Preserve original references and record crop bounds/source links when preparing comparison images.

Separate observations from inferred hidden geometry and illustrative dimensions. Do not turn missing dimensions into permission to change a visible mechanism. If different interpretations would materially change the target, prepare evidence for that specific uncertainty and ask the user through the scoped review. Make routine choices autonomously when the references settle them. A task-local contract need not become a long form or a mandatory approval gate.

For a folding product, define more than an opening angle: which edge owns each hinge, which face points inward when closed, which component nests above/below another, and which parts stay fixed. Rotating a plausible assembly is not evidence that the reference's folding action has been reproduced.

## Resolve structure before polishing

Prepare a simple model and the poses that expose the binding relationships. Match the reference's useful view, framing and pose before judging silhouettes; a convenient hero camera can hide a wrong hinge or changed proportion. Use a complementary side/rear view when depth or attachment is ambiguous.

Check the folded/start pose, usable/end pose and transitions where parts pass closest. Inspect actual rendered images side by side with the reference. Fix a wrong joint location, face direction, nesting or primary silhouette in the model source before spending effort on materials, tiny hardware or a complete final render.

For mechanically connected parts, derive attachment positions from the owning assembly's evaluated transform. Where a numeric check is useful, compare world-space anchors and test explicitly selected moving surfaces across the relevant transition. State which surfaces and frames were checked. A bounding-box test, coincident object origins, or absence of visible penetration in one camera does not establish full collision freedom or engineering validity. Intentional mating contacts need different treatment from forbidden plate intersections.

Use [evaluated diagnostics](diagnostics.md) to capture the relevant source frames and check declared connection anchors, hinge axes, contacts and preservation invariants. For a revision, capture the baseline before editing. Use [quality adapters](quality-tools.md) for multiview evidence, topology witnesses, sampled motion or a reference overlay. `reference` needs a reviewed foreground mask for projection metrics; `camera-fit` writes a candidate camera fit with geometry and camera pose fixed. Inspect the overlay before accepting it, so camera fitting does not conceal a wrong shape.

Keep reference-fit, motion/clearance and appearance findings distinct. After a repair, repeat the same affected views and neighboring poses; keep the camera fixed while judging a geometry change. Reuse valid production frames only when inputs and the pipeline's fingerprints permit it.

## Invite a precise contribution

Use the review's `evidence.references` and `evidence.checkpoints` to make the current comparison inspectable: the user sees a reference and model, jumps directly to the relevant pose/camera, and can mark a location. Ask one concrete question about the remaining uncertainty. Offer only the few semantic controls that are actually supported and necessary; known structural mistakes should be corrected by the agent before this step.

Do not expose a rotation slider as a substitute for fixing the hinge relationship. For unsupported native geometry or keyframe edits, receive the user's location/note, revise the Blender source, inspect the relevant evidence, and prepare a new review. A visual-only review with no parameter controls is appropriate when the user's contribution is to identify a mismatch. Reference markings do not confer extra project-write permissions.

Confirmation applies to the shown question and evidence, not to every hidden surface or all later animation. Preserve a reference/structure decision when modifying timing, materials or delivery. If a later change must alter a binding relationship, surface that concrete conflict rather than silently redesigning it.

## Report what has actually been established

Report execution evidence separately from target fidelity. A valid scene, finite transforms, in-frame geometry and decodable video can all pass while the product or mechanism is wrong. Keep a visible mismatch unresolved until the relevant reference comparison supports the correction or the user explicitly accepts a changed target.

If the evidence is insufficient for exact reconstruction, state the specific unseen or unmeasured details. Do not describe an illustrative model as a 100% or manufacturing-accurate reconstruction. This need not block completing the observed geometry and requested animation.

For scripted Blender materials, select existing nodes by their type or create the intended node graph explicitly; display names can vary with localization. Inspect rendered material regions before relying on a successful render process.
