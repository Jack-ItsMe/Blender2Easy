# Tests

Run from the repository root with Python 3.11 or newer:

```sh
python -m pip install -r skills/blender2easy/scripts/requirements.txt
python scripts/check.py --require-node
```

The frontend checks require Node.js 22 or newer. They use the bundled Three.js
and Node's VM module support; no npm install, browser, Blender, FFmpeg, or GPU
is needed. They exercise real geometry and raycasting plus minimal DOM test
doubles. They do not replace browser layout, accessibility, font decoding, or
visual review. Pass `--node /path/to/node` if Node is not on PATH, or
`--python-only` to explicitly omit frontend checks. Without `--require-node`,
an absent Node executable is reported as a skipped frontend suite.

Python tests cover review permissions and lifecycle, HTTP boundaries,
references and annotations, locale routing, diagnostic analysis, quality
tool arguments and cache identity, asset handoffs, local font integrity,
document links, and vendored provenance. All writable test projects use
temporary directories; fixture thread IDs are synthetic. HTTP tests listen
only on loopback using ephemeral ports. They do not access external services.
Installer and release tests also use tiny temporary sources: they check
refused overwrites, backups outside skill discovery, legacy migration,
rollback on a failed install, state exclusions, and reproducible ZIP hashes.

The optional protocol tests use the pinned official MCP SDK and temporary
child processes to check handshake negotiation, bounded output, cancellation,
queue limits, and cleanup:

```sh
python -m pip install -r skills/blender2easy/scripts/requirements-mcp.txt
python scripts/check.py --python-only --with-mcp
```

The separate Blender integration fixture is disabled by default. It creates
small temporary cube scenes and tests evaluated snapshots and imports, with
no product models or renders. With Blender installed, run:

```sh
python scripts/check.py --python-only --with-blender
```

`ANIMATION_BLENDER` can select the executable for this opt-in fixture. A
missing executable is reported as a skip. CI runs the unit/frontend and MCP
suites on Windows and Linux; it does not enable Blender integration.
