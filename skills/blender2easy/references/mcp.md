# Optional Blender2Easy MCP adapter

Use this only when a host needs MCP access to the fixed local CLI operations. Ordinary project work and quality commands do not require MCP. The adapter uses the official Python MCP SDK; [requirements-mcp.txt](../scripts/requirements-mcp.txt) is authoritative for its pinned version and includes the production dependencies. It does not install an add-on or open a persistent live Blender connection.

## Environment and host configuration

Use a dedicated Python 3.10+ virtual environment for MCP dependencies when setting up this integration. Install the requirements from the skill into that environment, then use its absolute Python path and the absolute `scripts/animation.py` path:

```text
<mcp-python> <skill>/scripts/animation.py mcp --config
<mcp-python> <skill>/scripts/animation.py mcp
```

`--config` works without the SDK and prints the command/arguments object for the selected Python environment; it does not edit host settings or register a server. Configure the intended host explicitly when that integration is requested. Keep any existing production Python environment unchanged unless the task requires updating it. Blender is needed only for operations that evaluate/import/render assets; other CLI dependencies remain operation-specific.

## Exposed operations

The server identifies itself as `blender2easy`. The adapter exposes 14 tools; their existing `animation_*` names are retained for compatibility. Arguments retain CLI scope and validation; it offers no arbitrary Python or shell execution.

| Tool | Operation / boundary |
| --- | --- |
| `animation_version` | Installed toolkit version |
| `animation_doctor` | Local Python/Blender/FFmpeg discovery; installs nothing |
| `animation_quality_catalog` | Available quality tools and dependency information |
| `animation_quality` | [Quality run](quality-tools.md) with a tool/spec, optional `timeout_seconds` 1–7200 and `reuse` |
| `animation_snapshot` | [Diagnostic snapshot](diagnostics.md); explicit 1–32 distinct frames, timeout 1–3600 seconds |
| `animation_describe` | Scoped/paginated snapshot facts; optional object/descendants/frame/offset/limit |
| `animation_diagnose` | Analyze an explicit snapshot and contract into a new report |
| `animation_compare` | Compare before/after snapshots with an explicit contract into a new report |
| `animation_asset_search` | [Mixamo/Pixabay browser handoff](asset-handoffs.md); URL preparation only |
| `animation_review_create` | [Create review](review.md) with explicit controlling `thread_id` and spec; no browser opening |
| `animation_review_status` | Read durable feedback and response identity |
| `animation_review_wait` | Explicit task/request; timeout 0–60 seconds, default 30; no wake-up of a finished agent |
| `animation_review_apply` | Explicit task/request and exact confirmed response digest |
| `animation_review_close` | Explicit task/request and optional message; preserves history |

`review open` remains a CLI operation. Attach diagnostic or supported quality reports through the review spec. Source, task and frozen-request checks still apply; a tool call does not grant wider editing scope.

Completed diagnostic `FAIL` returns usable findings with `isError: false`; inspect status and severity. Execution failures and stale inputs remain tool errors. Findings are limited to 50 items / 200 KB with total count, truncation flag and full report path retained. Missing-dependency discovery is a completed doctor report, not proof of readiness.

The server serializes its own tool jobs and supports cancellation. It does not schedule independently launched CLI workers or other servers. Completed quality runs may return a bounded PNG inline; complete artifacts remain at returned paths.

## Other transports

The bundled upstream [BAS server and viewer](../vendor/bas/plugins/blender-agent-studio/mcp/) are a separate optional Bun integration with their own package dependencies. The upstream [scene analyzer](../vendor/bas/plugins/blender-agent-studio/runtime/Cargo.toml) additionally uses a Rust build and Bun wrapper; local [diagnostics](diagnostics.md) work without them. Source inclusion does not install or activate these components.

For an explicitly requested live Blender connection or transport comparison, read the [BAS integration specialist](../vendor/bas/plugins/blender-agent-studio/skills/blender-mcp-integration/SKILL.md). Choose from tools actually available in the host; do not infer live execution, provider access or viewer support from bundled tool names.
