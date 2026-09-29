# BAS specialist routing

Select only the workflows needed by the request. Their domain guidance supplements the project's [source and delivery contract](source-delivery.md) and [scoped review rules](review.md); it does not add unrelated exports, rebuilds or user approval gates.

| Task | Specialist |
| --- | --- |
| Geometry, surfaces and construction | [Modeling](../vendor/bas/plugins/blender-agent-studio/skills/blender-modeling-workflow/SKILL.md) |
| Consequential ambiguity in subject, style or deliverables | [Art-direction intake](../vendor/bas/plugins/blender-agent-studio/skills/blender-art-direction-intake/SKILL.md) |
| Asset inspection or required clean re-import | [Asset validation](../vendor/bas/plugins/blender-agent-studio/skills/blender-asset-validation/SKILL.md) |
| Evidence-backed repair of a completed candidate | [Iterative refinement](../vendor/bas/plugins/blender-agent-studio/skills/blender-iterative-refinement/SKILL.md) |
| Articulated motion, pivots and critical poses | [Animation](../vendor/bas/plugins/blender-agent-studio/skills/blender-animation-workflow/SKILL.md) |
| Geometry Nodes and parametric systems | [Procedural workflow](../vendor/bas/plugins/blender-agent-studio/skills/blender-procedural-workflow/SKILL.md) |
| Materials, lighting, cameras and final rendering | [Rendering](../vendor/bas/plugins/blender-agent-studio/skills/blender-rendering-workflow/SKILL.md) |
| Fluids, cloth, rigid bodies and other physics | [Simulation](../vendor/bas/plugins/blender-agent-studio/skills/blender-simulation-workflow/SKILL.md) |
| Characters, rigs, deformation and fitted accessories | [Character workflow](../vendor/bas/plugins/blender-agent-studio/skills/blender-character-workflow/SKILL.md) |
| An explicitly requested controlled capability comparison | [Benchmarking](../vendor/bas/plugins/blender-agent-studio/skills/blender-agent-benchmark/SKILL.md) |
| Choosing or troubleshooting Blender tool transport | [MCP integration](../vendor/bas/plugins/blender-agent-studio/skills/blender-mcp-integration/SKILL.md) |

Links resolve within this bundled tree. Resolve a specialist's relative references from that specialist, and `plugins/...` paths in the [BAS router](../vendor/bas/SKILL.md) from `vendor/bas/`. Do not substitute a different installed plugin with a similar name.

Upstream `blender_*` names describe optional integrations, not available host tools. Choose the relevant local route:

- [Quality tools](quality-tools.md) for fixed inspection, motion samples, reference comparison, camera fitting and rendered evidence.
- [Diagnostics](diagnostics.md) for evaluated scene descriptions, declared relationships and revision invariants.
- [MCP adapter](mcp.md) only when connecting these operations to a host.
- [Asset handoffs](asset-handoffs.md) only when the task needs external assets or local FBX import.

The source bundle is pinned to BAS commit `748b18ba4cbb5df6fc1da854e00e4c3526fdd128`. [Provenance](../vendor/bas/PROVENANCE.json) records upstream hashes and local adaptations; [notices](../THIRD_PARTY_NOTICES.md) retain licensing. Inclusion does not install provider connections, Bun/Rust dependencies or benchmark access. A requested benchmark additionally needs its documented Bun harness and configured model access; source availability is not a benchmark result.
