# Verification and recovery

Builds and outputs use versioned paths. A build record is reused only with matching native hash. Native image identity includes build, camera, resolution, render settings and implementation/runtime identity. PNG checks cover dimensions, required structure and all chunk CRCs. Layout/timing changes do not by themselves invalidate unchanged plates. Native scene changes currently invalidate the whole build, not individual mesh dependencies.

Composition depends on the plan, actual images, implementation and encoding/runtime profile. Videos are fully decoded and checked for size, FPS and frame count; check records bind SHA-256. Missing/uncommitted checks or mismatching bytes are not complete deliveries. PASS establishes encoding integrity, not visual/physical correctness: inspect actual previews and movement.

After interruption, run the same command. OS locks release when a process dies; leftover lock files need no deletion. Valid frames are reused, invalid/missing frames regenerated. Keep logs until diagnosed. Do not launch a second worker around an active project lock.

`status` is a snapshot, not a promise a process remains alive. If unchanged, inspect the log and actual process. A shell window or assistant turn ending does not establish render failure. There is no background supervisor or remote scheduling.

`verify` checks the last recorded shot delivery, including full decode. It does not certify later unrendered edits. Prefer current check records and exact versions over prose checkpoints.

Native external resources must be declared and hashed. Packed resources are preferable for transfer. Linked libraries and simulation caches need explicit attention; unpacked image sequences are rejected by the current worker. Use a suitable self-contained asset rather than assuming every `.blend` is automatically portable.

Blender/FFmpeg/toolkit changes may create new versioned results. Do not manually copy images into a new signature directory. Deliver video, contact sheet/check record, project parameters and native build as appropriate; inspect dependencies before claiming native portability.

For `export` deliveries, use relative paths and hashes from `export-manifest.json` to check the transferred files. `source-check.json` preserves the original delivery record and its original paths; it is provenance, not a relocated pipeline check. A successful export establishes copy and video integrity, not native portability or completion of unrendered edits.

Token efficiency has not been benchmarked. Measure fixed tasks at equal quality, include subagent/retry usage, and separate initial development from subsequent runs. Compact responses and reusable programs are intentional efficiency choices, not a guaranteed percentage saving.
