// node --experimental-vm-modules inspection-snap-checks.mjs
// Actual bundled Three geometry, raycasting, transforms and camera projection.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '../../skills/blender2easy/editor/web');
const context = vm.createContext({console, Intl, URL, URLSearchParams, setTimeout, clearTimeout,
  navigator: {languages: ['en']}, document: {documentElement: {dataset: {}, style: {}}, querySelectorAll: () => [], getElementById: () => null}});
const modules = new Map();
async function load(filename) {
  filename = path.resolve(filename);
  if (!modules.has(filename)) modules.set(filename, new vm.SourceTextModule(await readFile(filename, 'utf8'), {context, identifier: filename}));
  return modules.get(filename);
}
function resolve(specifier, source) {
  if (specifier === 'three') return path.join(root, 'vendor/three/build/three.module.js');
  if (specifier.startsWith('three/addons/')) return path.join(root, 'vendor/three/examples/jsm', specifier.slice(13));
  if (specifier.startsWith('/')) return path.join(root, specifier.slice(1));
  return path.resolve(path.dirname(source), specifier);
}
const module = await load(path.join(root, 'viewport.js'));
await module.link((specifier, source) => load(resolve(specifier, source.identifier))); await module.evaluate();
const {Viewport} = module.namespace;
const THREE = (await load(path.join(root, 'vendor/three/build/three.module.js'))).namespace;
const {RoundedBoxGeometry} = (await load(path.join(root, 'vendor/three/examples/jsm/geometries/RoundedBoxGeometry.js'))).namespace;
const material = () => new THREE.MeshBasicMaterial({side: THREE.DoubleSide});
function orthographic() {
  const camera = new THREE.OrthographicCamera(-2, 2, 2, -2, .1, 100);
  camera.position.set(0, 0, 10); camera.lookAt(0, 0, 0); camera.updateMatrixWorld(true); return camera;
}
function fixture(geometry, camera = orthographic()) {
  const content = new THREE.Group(), source = new THREE.Group(); source.userData.editorId = 'part';
  const mesh = new THREE.Mesh(geometry, material()); source.add(mesh); content.add(source);
  const view = Object.assign(Object.create(Viewport.prototype), {content, cameras: new Map(), cameraId: null, freeCamera: camera,
    inspection: {tools: new Set(['point', 'measure']), objectIds: new Set(['part'])}, inspectionMode: 'measure', inspectionSnapEnabled: true,
    inspectionPoints: [], inspectionMarkers: new THREE.Group(), measurementLabel: {style: {}}, surfaceCursor: {style: {}, dataset: {}},
    rect: {x: 0, y: 0, width: 400, height: 400}, renderer: {domElement: {getBoundingClientRect: () => ({left: 0, top: 0})}}});
  content.updateMatrixWorld(true);
  return {view, mesh, source, content, camera};
}
const event = (x, y) => ({clientX: x, clientY: y});
function screen(world, camera) {
  camera.updateMatrixWorld(true); const point = world.clone().project(camera); return {x: (point.x + 1) * 200, y: (1 - point.y) * 200};
}
const checks = [];
let f = fixture(new THREE.PlaneGeometry(2, 2, 1, 1));
for (const [x, y] of [[200, 200], [245, 155]]) {
  const result = f.view.inspectionSample(event(x, y));
  assert.ok(result.surface); assert.equal(result.candidate, undefined, 'A planar triangle diagonal is not a feature');
}
let result = f.view.inspectionSample(event(306, 195));
assert.equal(result.candidate?.kind, 'edge');
assert.ok(Math.abs(result.surface.world[0] - 1) < 1e-9);
result = f.view.inspectionSample(event(305, 105));
assert.equal(result.candidate?.kind, 'vertex');
assert.deepEqual(Array.from(result.surface.world), [1, 1, 0]);
result = f.view.inspectionSample(event(312, 195));
assert.equal(result.surface, null, '12px is outside the 11px edge threshold');
f.view.setInspectionSnap(false);
result = f.view.inspectionSample(event(306, 195)); assert.equal(result.surface, null);
result = f.view.inspectionSample(event(297, 195)); assert.ok(result.surface); assert.equal(result.candidate, undefined);
assert.ok(Math.abs(result.surface.world[0] - .97) < 1e-9, 'Disabled snapping preserves the actual ray hit');
checks.push('Screen thresholds, endpoint priority, real edge coordinates, no planar diagonal and disabled raw-surface behavior');

const template = JSON.parse(await readFile(path.resolve(root, '../../assets/templates/box.json'), 'utf8'));
const lid = template.scene.objects.find(object => object.id === 'lid');
f = fixture(new RoundedBoxGeometry(...lid.dimensions, 3, lid.bevel));
const fixedEdges = new THREE.EdgesGeometry(f.mesh.geometry, 30);
assert.equal(fixedEdges.getAttribute('position').count, 0, 'Actual rounded template has no 30-degree fixed edges'); fixedEdges.dispose();
result = f.view.inspectionSample(event(200 + lid.dimensions[0] / 2 * 100 + 5, 197));
assert.ok(result.candidate, 'The actual rounded lid still provides its visible silhouette');
assert.ok(Math.abs(result.surface.world[0] - lid.dimensions[0] / 2) < 1e-6);
checks.push('Actual template lid with bevel .035 / segments 3 snaps to its silhouette even though EdgesGeometry(30°) is empty');

f = fixture(new THREE.PlaneGeometry(2, 2));
const floor = new THREE.Mesh(new THREE.PlaneGeometry(20, 20), material()); floor.position.z = -2; floor.userData.editorId = 'floor'; f.content.add(floor);
result = f.view.inspectionSample(event(306, 197));
assert.ok(result.candidate, 'A farther out-of-scope background permits outside-contour snapping');
const cover = new THREE.Mesh(new THREE.PlaneGeometry(.5, 2), material()); cover.position.set(1, 0, 1); cover.userData.editorId = 'cover'; f.content.add(cover);
result = f.view.inspectionSample(event(306, 197));
assert.equal(result.candidate, undefined); assert.equal(result.reason, 'out-of-scope');
delete cover.userData.editorId;
result = f.view.inspectionSample(event(306, 197));
assert.equal(result.candidate, undefined); assert.equal(result.reason, 'no-surface', 'An unmapped front occluder also blocks snapping');
cover.material.visible = false;
result = f.view.inspectionSample(event(306, 197)); assert.ok(result.candidate, 'Invisible material must not block a real edge');
f.source.visible = false;
result = f.view.inspectionSample(event(306, 197)); assert.equal(result.candidate, undefined, 'An invisible ancestor never supplies candidates');
checks.push('Visible outside silhouette works over a background floor; foreground mapped/unmapped covers block; material/ancestor visibility is respected');

f = fixture(new THREE.PlaneGeometry(2, 2));
f.mesh.geometry.clearGroups(); f.mesh.geometry.addGroup(0, 3, 0); f.mesh.geometry.addGroup(3, 3, 1);
f.mesh.material = [material(), material()]; f.mesh.material[0].visible = false;
result = f.view.inspectionSample(event(250, 110)); assert.ok(!result.candidate, 'An invisible material group supplies no top edge');
result = f.view.inspectionSample(event(250, 290)); assert.equal(result.candidate?.kind, 'edge', 'The visible material group still supplies its true boundary');
checks.push('Material-array groups contribute candidates only from rendered faces');

const perspective = new THREE.PerspectiveCamera(42, 1, .1, 100);
perspective.position.set(4, 3, 7); perspective.lookAt(0, 0, 0); perspective.updateMatrixWorld(true);
f = fixture(new THREE.BoxGeometry(2, 2, 2), perspective);
f.source.rotation.z = .17; f.mesh.scale.set(1.4, .7, .5); f.mesh.rotation.y = .25; f.content.updateMatrixWorld(true);
const a = new THREE.Vector3(1, 1, 1).applyMatrix4(f.mesh.matrixWorld), b = new THREE.Vector3(1, -1, 1).applyMatrix4(f.mesh.matrixWorld);
const ap = screen(a, perspective), bp = screen(b, perspective), s = .43;
const near = {x: ap.x + (bp.x - ap.x) * s, y: ap.y + (bp.y - ap.y) * s};
result = f.view.inspectionSample(event(near.x, near.y));
assert.equal(result.candidate?.kind, 'edge');
const world = new THREE.Vector3(...result.surface.world), segment = new THREE.Line3(a, b), onSegment = segment.closestPointToPoint(world, true, new THREE.Vector3());
assert.ok(world.distanceTo(onSegment) < 1e-7, 'Snapped world point is on the actual transformed edge');
const actualScreen = screen(world, perspective);
assert.ok(Math.hypot(actualScreen.x - near.x, actualScreen.y - near.y) < 1e-6, 'Perspective correction reproduces the closest screen point');
assert.ok(world.distanceTo(new THREE.Vector3(...result.surface.local).applyMatrix4(f.source.matrixWorld)) < 1e-9, 'Source-owner local coordinates preserve parent transform');
const naïve = a.clone().lerp(b, s); assert.ok(naïve.distanceTo(world) > .001, 'The test would catch uncorrected screen lerp');
checks.push('Perspective correction, rotated parents and nonuniform scale keep exact edge/world/source-local coordinates');

f = fixture(new THREE.BoxGeometry(2, 2, 2));
const hiddenBack = {mesh: f.mesh, source: f.source, world: new THREE.Vector3(1, 0, -1), projected: {x: 300, y: 200, depth: 11}};
assert.equal(f.view.inspectionCandidateVisible(hiddenBack, f.camera), false, 'Same object is insufficient: its front surface hides the back edge');
f.mesh.position.z = 12;
result = f.view.inspectionSample(event(300, 200)); assert.equal(result.candidate, undefined, 'Behind-camera features are excluded');
checks.push('Backside depth rejection and camera clipping prohibit false visible candidates');

f = fixture(new THREE.PlaneGeometry(2, 2));
result = f.view.inspectionSample(event(305, 190)); assert.ok(result.candidate);
const position = f.mesh.geometry.getAttribute('position');
for (let i = 0; i < position.count; i++) position.setX(i, position.getX(i) + .4);
position.needsUpdate = true;
result = f.view.inspectionSample(event(345, 190));
assert.ok(result.candidate); assert.ok(Math.abs(result.surface.world[0] - 1.4) < 1e-6, 'Position version invalidates bounds and feature cache');
for (let i = 0; i < position.count; i++) position.setX(i, position.getX(i) + 4);
position.needsUpdate = true; f.camera.position.x = 4; f.camera.lookAt(4, 0, 0);
result = f.view.inspectionSample(event(345, 190));
assert.ok(result.candidate); assert.ok(Math.abs(result.surface.world[0] - 5.4) < 1e-6, 'Raycast bounding sphere also refreshes outside the former bounds');

f = fixture(new THREE.PlaneGeometry(2, 2));
const morphed = f.mesh.geometry.getAttribute('position').clone();
for (let i = 0; i < morphed.count; i++) morphed.setZ(i, .25);
f.mesh.geometry.morphAttributes.position = [morphed]; f.mesh.updateMorphTargets(); f.mesh.morphTargetInfluences[0] = 1;
result = f.view.inspectionSample(event(295, 195));
assert.equal(result.candidate, undefined); assert.equal(result.hover?.reason, 'deformed');
assert.ok(Math.abs(result.surface.world[2] - .25) < 1e-7, 'Fallback uses the actual morphed surface');
const geometry = new THREE.PlaneGeometry(2, 2), vertexCount = geometry.getAttribute('position').count;
geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(new Uint16Array(vertexCount * 4), 4));
const weights = new Float32Array(vertexCount * 4); for (let i = 0; i < vertexCount; i++) weights[i * 4] = 1;
geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute(weights, 4));
const skinned = new THREE.SkinnedMesh(geometry, material()), bone = new THREE.Bone(); skinned.add(bone); skinned.bind(new THREE.Skeleton([bone]));
f.source.remove(f.mesh); f.source.add(skinned); bone.position.z = .3; f.content.updateMatrixWorld(true); skinned.skeleton.update();
result = f.view.inspectionSample(event(295, 195));
assert.equal(result.candidate, undefined); assert.equal(result.hover?.reason, 'deformed');
assert.ok(Math.abs(result.surface.world[2] - .3) < 1e-7, 'Fallback uses the actual skinned surface');
bone.position.set(4, 0, .8); f.camera.position.x = 4; f.camera.lookAt(4, 0, 0);
result = f.view.inspectionSample(event(295, 195));
assert.equal(result.hover?.reason, 'deformed'); assert.ok(Math.abs(result.surface.world[2] - .8) < 1e-7, 'Animated bounds refresh after the skeleton moves outside its initial extent');
f = fixture(new THREE.PlaneGeometry(2, 2));
const instanced = new THREE.InstancedMesh(new THREE.PlaneGeometry(2, 2), material(), 1);
instanced.setMatrixAt(0, new THREE.Matrix4().makeTranslation(.4, 0, .5));
f.source.remove(f.mesh); f.source.add(instanced);
result = f.view.inspectionSample(event(295, 195));
assert.equal(result.hover?.reason, 'instanced'); assert.equal(result.candidate, undefined); assert.ok(Math.abs(result.surface.world[2] - .5) < 1e-7);
f = fixture(new THREE.PlaneGeometry(2, 2, 160, 160));
result = f.view.inspectionSample(event(295, 195)); assert.equal(result.candidate, undefined); assert.equal(result.hover?.reason, 'dense');
checks.push('Geometry edits invalidate caches; real morph/skinning and dense geometry report explicit fallback while preserving actual surface hits');

f = fixture(new THREE.PlaneGeometry(2, 2)); result = f.view.inspectionSample(event(305, 105));
const hover = []; f.view.onInspectionHover = info => hover.push(info?.kind ?? null);
f.view.showInspectionHover(result); f.view.clearInspectionHover(); f.view.showInspectionHover(result);
assert.deepEqual(hover, ['vertex', null, 'vertex']);
let saved; f.view.select = () => {}; f.view.onSurfacePick = point => {saved = point;};
f.view.pick(event(305, 105));
assert.deepEqual(Object.keys(saved).sort(), ['local', 'object_id', 'world']);
f.view.inspectionPoints = [{object_id: 'part', local: [0, 0, 0], world: [0, 0, 0]}];
f.view.setInspectionSnap(false); assert.equal(f.view.inspectionPoints.length, 1, 'Toggling snap never clears an existing A point');
checks.push('Hover callback resets after misses/clears, point payload stays schema-compatible, and toggle preserves A');
console.log(JSON.stringify({status: 'PASS', checks}, null, 2));
