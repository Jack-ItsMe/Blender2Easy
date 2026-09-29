# Third-party notices

## Three.js

The local preview bundles Three.js 0.186.1 under `editor/web/vendor/three/`.
Copyright © 2010–2026 three.js authors. Distributed under the MIT License;
the full notice is retained in
[editor/web/vendor/three/LICENSE](editor/web/vendor/three/LICENSE).

## Interface fonts

The interface bundles Inter, Noto Sans SC and Noto Sans TC as unmodified WOFF2
files distributed by Google Fonts. They load from local assets; no font CDN is
contacted when the application runs. The font files, original source URLs and
SHA-256 hashes are recorded in [editor/web/fonts/manifest.json](editor/web/fonts/manifest.json).
The SIL Open Font License 1.1 is retained for each family:
[Inter](editor/web/fonts/Inter-OFL.txt),
[Noto Sans SC](editor/web/fonts/NotoSansSC-OFL.txt), and
[Noto Sans TC](editor/web/fonts/NotoSansTC-OFL.txt).

## Blender Agent Studio

The source and workflow documents under `vendor/bas/` are adapted from
[Blender Agent Studio](https://github.com/ifBars/blender-agent-studio), commit
`748b18ba4cbb5df6fc1da854e00e4c3526fdd128`.

Copyright (c) 2026 Bars. Distributed under the MIT License. The complete
copyright and permission notice is retained in [vendor/bas/LICENSE](vendor/bas/LICENSE)
and the original plugin license is retained within the vendored plugin tree.
`vendor/bas/PROVENANCE.json` lists the frozen upstream files, original SHA-256
hashes and local modifications. Local changes add explicit frame selection,
disable embedded scripts when opening assets, protect fresh evidence outputs,
and preserve explicit diagnostic cameras after frame evaluation. Version 0.7
also unifies native/scripted source and requested-delivery rules, scopes repair
checks, and centralizes the shared Blender guidance. Original upstream hashes
remain alongside hashes of the locally adapted documents. The Python
quality adapter and capability routing are local integration code. The Python
browser handoffs in `scripts/animkit/asset_tools.py` adapt the bundled BAS
Mixamo/Pixabay helpers under the same retained MIT notice.

The original [upstream notices](vendor/bas/THIRD_PARTY_NOTICES.md) are retained
for provenance. Their Blender icon and documentation-site font/build notices
describe upstream content that is **not bundled here**. No Blender logo, site
fonts, node_modules or compiled Rust targets are included. Optional dependency
manifests and source remain for reproducibility; the dependencies and services
are not installed, registered, or licensed by inclusion of these source files.

Blender and the Blender logo are trademarks of the Blender Foundation.
This skill is not affiliated with or endorsed by the Blender Foundation.

External models, textures, HDRIs, motion clips, audio and provider services
retain their own licenses and access requirements. Record those separately
when a task actually acquires such assets.

## Optional MCP SDK

The MCP entry depends on the official
[Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk), installed
separately through `scripts/requirements-mcp.txt`. The SDK and its dependencies
are not vendored in this skill archive; their package distributions retain their
own licenses. The production CLI does not import the SDK unless MCP is started.
