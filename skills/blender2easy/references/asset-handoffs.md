# Asset handoffs and local motion import

Use this when external assets are part of the requested result. Bundled helpers do not establish provider access, current license terms or permission to download. Preserve the source page and license/access information for assets actually acquired.

## Mixamo and Pixabay browser handoffs

```text
python <skill>/scripts/animation.py assets search mixamo --query "walking"
python <skill>/scripts/animation.py assets search pixabay --query "mechanical click"
```

These commands prepare an encoded URL and browser instructions using Python. Queries contain 1–200 characters without control characters. They return `browser_required`; no network request, sign-in, live search or download is performed. Use available browser tools to inspect real results and continue the user's authorized asset acquisition.

Mixamo may require the user's Adobe sign-in. Inspect the motion and record its title, source page, character, in-place setting and download FPS. Pixabay's helper targets sound effects; it provides a browser workflow, not an audio catalog API. Inspect the selected sound's duration, creator, source page and current license before use. Verify that a requested download actually completed before attempting a local import.

The detailed [Mixamo guide](../vendor/bas/plugins/blender-agent-studio/skills/blender-animation-workflow/references/mixamo.md) covers browser settings and compatibility limits. Its upstream MCP names are optional; the local commands above work without Bun.

## Import a local animated FBX

```text
python <skill>/scripts/animation.py assets import-motion --spec motion-import.json
```

```json
{"input":"downloaded.fbx","outputDir":"motion/new-clip","clipName":"Walk","fps":30}
```

`assets import-motion` aliases `quality run mixamo-import`. It needs Blender, accepts a local `.fbx`, and writes a separate `.blend` and report. `clipName` is 1–120 characters; `fps` is 24, 30 or 60, default 30. It shares the [quality tool](quality-tools.md) path resolution, timeout, provenance and explicit reuse rules, including `--blender`, `--timeout` and `--reuse`.

The importer keeps the downloaded skeleton/actions. It neither authenticates the source as Mixamo nor retargets to an existing rig. Inspect poses and use the report's actual frame range/FPS because FBX import may shift the frame origin. Carry accepted animation into the [appropriate durable source](source-delivery.md).

## Materials and HDRIs

The upstream [Poly Haven CLI](../vendor/bas/plugins/blender-agent-studio/skills/blender-rendering-workflow/scripts/poly-haven-cli.ts) requires Bun and network access. Read [its material workflow](../vendor/bas/plugins/blender-agent-studio/skills/blender-rendering-workflow/references/poly-haven-materials.md) when acquiring textures or HDRIs is in scope. Keep download hashes and source/license details. The local Python adapter does not expose these provider downloads.

External models, textures, motion clips, audio and services retain their own licenses; the bundled BAS license covers source code, not those assets. See [third-party notices](../THIRD_PARTY_NOTICES.md) for the source bundle's provenance and exclusions.
