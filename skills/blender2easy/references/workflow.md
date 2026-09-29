# Commands and workflow

Use `python <skill>/scripts/animation.py <command>`. The skill folder may move; commands locate templates relative to the script. Each project occupies its own directory and contains one `project.json`. The `.animation` directory holds builds, plans, cache, status, previews and deliveries. External assets are read-only inputs.

```text
animation.py doctor
animation.py editor --open
animation.py editor <project.json> --open
animation.py init <new-project-directory> --template blank
animation.py init <new-project-directory> --template box
animation.py validate <project.json>
animation.py build <project.json>
animation.py plan <project.json> --shot <id>
animation.py preview <project.json> --shot <id> --frames 1,24,48
animation.py run <project.json> --shot <id>
animation.py status <project.json>
animation.py verify <project.json> --shot <id>
animation.py export <project.json> --to <new-delivery-directory>
```

For evaluated scene facts and declared relationship/revision checks, use `diagnose snapshot`, `describe`, `analyze` and `compare`; read [diagnostics.md](diagnostics.md) for contracts, provenance and fresh-file outputs. For fixed BAS inspection, reference, camera and render tools, use `quality catalog` and `quality run TOOL --spec SPEC`; read [quality tools](quality-tools.md) for specs and [specialists](specialists.md) for domain workflows. Read [MCP integration](mcp.md) only when configuring the optional stdio entry. These commands operate on asset/report paths and do not require a parameterized project.

For user judgments on a prepared project, use `review create`, `status`, `wait`, `open`, `apply` and `close` as described in [review.md](review.md). Reviews can attach current diagnostic reports through `--diagnostics REPORT` or `evidence.reports` in the spec. They preserve their own frozen evidence and edit scope.

`editor` runs the local review preview at `http://127.0.0.1:8766`; `--port` changes the port, `--workspace` changes the directory used for newly created projects, and `--open` opens the browser. Windows users can double-click `启动编辑器.cmd` to launch or reopen the default preview. When no project is supplied, it restores its remembered project or creates a separate box-template project. Read [editor.md](editor.md) for scoped viewing, native `.blend` assets and explicitly requested `--authoring` access. The JavaScript dependencies are bundled, so viewing needs no CDN, cloud service or API key.

`run` builds if necessary, renders missing source images, composes/encodes, and verifies the video. Omit `--shot` for all shots. `preview` defaults to first/middle/last frames and returns composed stills rather than a movie. `plan` may build a missing native scene but does not render images. `render` only produces native PNGs. `compose` requires a matching prior render report and performs no image rendering. `verify` strictly decodes the last recorded delivery; it does not apply later project edits.

`export` requires a new destination outside the original project directory. It copies the project JSON, declared assets and last recorded deliveries, fully decodes the videos before copying and verifies copied hashes. Project asset paths become relative to the exported project. Read `export-manifest.json` for transferred paths, hashes and portability status. Generated native builds, render caches and job status are not copied; `run` rebuilds them in the exported project. Exported deliveries do not certify later project edits. A `source` project receives `requires_native_review`: internal `.blend` paths are unchanged, so repack or relink resources and check a build before claiming native portability. Use `--ffmpeg <path>` if FFmpeg discovery needs an override.

Blender and FFmpeg resolve through PATH, `ANIMATION_BLENDER`/`ANIMATION_FFMPEG`, or `--blender`/`--ffmpeg`. `doctor` is read-only. Python dependencies are in `scripts/requirements.txt`; use available packages rather than reinstalling routinely. Discovery checks standard Blender locations on Windows/macOS and imageio-ffmpeg's bundled FFmpeg.

```text
animation.py change project.json --set /render/samples 32
animation.py change project.json --set /scene/objects/0/dimensions "[2.4,1.2,0.5]"
animation.py change project.json --set /shots/0/timing/0/frames 36
```

The value is JSON; shell quoting varies. Pointers must address existing fields. Add objects/tracks by editing JSON then validating. A successful `change` archives the preceding project JSON and a change record under `.animation`. Invalid updates leave the file intact. Restore by copying an archived JSON to `project.json`, then validate; keep old deliveries.

Production commands return one JSON result on stdout; `editor` stays running as the local server. Use returned `video`, `check`, `contact_sheet`, preview and log paths, not assumed cache paths. The editor serializes its Blender jobs; separate CLI processes and editor servers are not globally coordinated, so avoid competing jobs on one GPU. A project OS lock prevents simultaneous writes by pipeline commands. Editor saves also check the project path and revision and archive the preceding JSON.

Reuse camera/light/render configurations and transform controllers across categories. A new product's geometry and behavior remain project data or its native Blender asset. The browser edits those shared parameters, while complex rigs, modifiers, shader graphs and mesh modeling remain Blender responsibilities.
