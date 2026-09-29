# Changelog

## 0.10.2

- Resolve temporary fixture paths before comparing them in tests, including
  Windows 8.3 aliases used by hosted runners. Production workflow behavior is unchanged.

This is the release recommended for the public launch. Version 0.10.1 records
the initial repository upload and remains available for reference.

## 0.10.1

First GitHub release under the **Blender2Easy** name, continuing the local
Object Animation toolkit (0.10.0).

- Renamed the skill, agent invocation, interface branding and MCP server identity.
- Organized the repository with installation instructions, examples and tests.
- Added a local installer with backups and a reproducible release packager.
- Retained existing project schemas, preview state keys and the `animkit` Python module for compatibility.

This release includes the existing Blender workflow, scoped Three.js review,
edge/vertex snapping, preview measurements, three interface languages, dark/light
themes and resumable rendering. The UI screenshots use a small procedural test
scene; they are not final Blender renders. See the README for limitations and
the tested environment.
