# Project format v1

Validate with `animation.py validate project.json`. Unknown fields, duplicate IDs, missing assets, parent cycles, invalid keys, impossible timing, and off-canvas overlays fail before rendering. Start from bundled JSON examples rather than reading all implementation files.

Top-level: `schema_version: 1`, stable `id`, `units`, `assets`, exactly one of `scene` or `source`, `render`, and nonempty `shots`. Project and procedural IDs use letters, digits, hyphens and underscores; native Blender names in `source.overrides` can include spaces and non-ASCII characters. Asset paths resolve relative to project JSON; absolute read-only inputs are supported. Declared files are content-hashed. Each asset has `id`, `path`, optional expected `sha256`. The asset list records dependencies; it does not import meshes or attach textures to a procedural scene. Prepare those features in a native `.blend` and use `source`.

**Procedural scene**

`scene` contains `background` (three sRGB components 0..1), `world_strength`, `materials`, `objects`, `cameras`, `lights`, `animation`. Color is converted from sRGB once. This is a modeling starter, not a CAD or simulation system.

- Material: `id`, `color` RGBA 0..1, `roughness` 0..1, `metallic` 0..1.
- Object: `id`, `type` (`cube`, `cylinder`, `sphere`, `empty`), `dimensions`, `location`, `rotation_deg`, `scale`, optional `material`, `parent`, `bevel`. Dimensions and transforms are local; parent scale affects children. Parent order is irrelevant.
- Camera: `id`, `location`, `target`, `type` (`ORTHO`/`PERSP`), `ortho_scale`, `lens`. Look-at establishes initial orientation; explicit rotation tracks may override it.
- Light: `id`, `type` (`AREA`/`POINT`/`SUN`), `location`, `target`, `energy`, `size`.
- Animation: `target`, `property` (`location`, `rotation_deg`, `scale`), `keys`. Each key has native integer `frame`, three-component `value`, and `interpolation` (`LINEAR`, `BEZIER`, `CONSTANT`). Keys ascend uniquely. Use parented empties for hinges and rigid assemblies.

`units` may be m/cm/mm. Geometry, locations, targets, bevel, orthographic scale, light size and location-animation values convert to meters in Blender. Scale is unitless, rotations are degrees, lens remains millimeters, energy is not a length. Native source scenes retain their existing units.

**Existing Blender scene**

```json
"source": {
  "blend": "assets/model.blend",
  "scene": "Scene",
  "dependencies": ["assets/label.png"]
}
```

Declare external dependencies explicitly, or use a self-contained packed `.blend`. Unpacked dependencies discovered by Blender must be declared and match their hashes. Every UDIM tile must be declared. Unpacked image sequences are rejected, even if their first file is declared. Browser import discovers dependencies and creates a new JSON project referencing the original `.blend`; missing external files produce an error. The input is never saved over. Change complex geometry through the original modeling workflow, then select the new native file. Native camera names and scene membership are checked during build/render, not by JSON validation alone. The pipeline renders cameras in the selected scene and disables old compositor/sequencer output; it does not reproduce arbitrary legacy compositor graphs.

Optional `source.overrides` records native edits separately from the source file. Example:

```json
"overrides": {
  "objects": [{"id": "Lid hinge", "rotation_deg": [35, 0, 0]}],
  "materials": [{"id": "Shell", "color": [0.2, 0.4, 0.7, 1], "roughness": 0.4}],
  "cameras": [{"id": "Camera", "location": [4, -6, 4], "target": [0, 0, 1], "lens": 50}]
}
```

- Objects accept `location`, `rotation_deg` and `scale`. Values are Blender local transforms in the original scene's coordinates; the project's `units` setting does not rescale native edits. Rotation overrides use XYZ Euler degrees. Scale components must be nonzero. Native dimensions are inspect-only.
- Materials accept sRGB RGBA `color`, `roughness` and `metallic`. Editing requires a direct active Principled BSDF surface and unlinked sockets. Shared materials change for all their users. Texture-driven properties and mixed/custom shader graphs must be edited in Blender.
- Cameras accept world `location`, world `target`, `lens` in millimeters and `ortho_scale` in native scene units. Pose edits require an unparented, unconstrained camera; camera type is retained. Lens edits isolate shared camera data.

Each override needs an existing native `id` and at least one edited property; unknown fields, duplicate IDs, nonfinite values and nonexistent targets fail. Do not duplicate the same native object in both the object and camera override lists. Build copies the original scene and removes the edited property's original animation curves from that copy so the override remains effective throughout the shot. Unedited animation properties remain intact. Transform edits controlled by active constraints, drivers or NLA, linked objects, nonidentity parent inverse matrices, delta transforms and bone/vertex parenting require preparation in Blender and are explicitly rejected. Material/camera property drivers and active NLA are likewise rejected. See [editor.md](editor.md) for the browser's original-animation preview base and undo behavior.

**Rendering and shots**

`render`: integer `fps`, `resolution` [width,height], `samples`, `engine` (`BLENDER_EEVEE`/`CYCLES`), `transparent`. H264 dimensions must be even. PNG transparency is flattened to background in MP4. Default output is silent H264.

Shot: `id`, `title`, inclusive native `source_range`, `camera`, optional `timing`, optional `overlays`. Native camera names may include spaces. Different shots can select separate ranges of one native scene.

Timing phases cover the entire shot without gaps/overlaps. Phase: `source_range`, positive output `frames`, protected native `anchors`. Endpoints are protected. Target count must fit distinct anchors. Shorter phases sample poses; longer phases repeat frames. No optical flow or smooth slow-motion synthesis.

Overlay: `id`, `camera`, `size` (native render pixels), `rect` [x,y,width,height] in output pixels from top left, `source_range` for visibility, `alpha`, `fade_frames` in output frames, `border`, `radius`, `border_rgb`. Set `size` explicitly for layout-only edits: moving the rectangle reuses its plate; changing native render size creates new inputs.

Plans retain output and original native frame numbers; main/detail use the mapped source frame. Full maps stay on disk. One native file per project and synchronized views are supported; independent source clocks, fluid solvers and layered multi-native compositions require other tooling.
