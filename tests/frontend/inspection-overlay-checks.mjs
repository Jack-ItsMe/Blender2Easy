// Real Three projection and measurement methods with a minimal DOM boundary.
// Run: node --experimental-vm-modules inspection-overlay-checks.mjs
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';

class Element {
  constructor(tag) {this.tagName = tag; this.attributes = new Map(); this.children = []; this.style = {}; this.hidden = false;}
  setAttribute(key, value) {this.attributes.set(key, String(value));}
  getAttribute(key) {return this.attributes.get(key) ?? null;}
  toggleAttribute(key, force) {if (force) this.setAttribute(key, ''); else this.attributes.delete(key);}
  append(...nodes) {this.children.push(...nodes);}
  appendChild(node) {this.append(node); return node;}
  remove() {this.removed = true;}
  get offsetWidth() {return this.className === 'measurement-label' ? 110 : 20;}
  get offsetHeight() {return this.className === 'measurement-label' ? 34 : 20;}
}
const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '../../skills/blender2easy/editor/web');
const document = {createElement: tag => new Element(tag), createElementNS: (ns, tag) => new Element(tag),
  documentElement: {dataset: {}, style: {}}, querySelectorAll: () => [], getElementById: () => null};
const context = vm.createContext({console, Intl, URL, URLSearchParams, setTimeout, clearTimeout, document, navigator: {languages: ['en']}});
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
await module.link((specifier, source) => load(resolve(specifier, source.identifier)));
await module.evaluate();
const THREE = (await load(path.join(root, 'vendor/three/build/three.module.js'))).namespace;
const {Viewport} = module.namespace;
const i18n = (await load(path.join(root, 'i18n.js'))).namespace;
const camera = new THREE.OrthographicCamera(-2, 2, 1.2, -1.2, .1, 100);
camera.position.set(0, 0, 10); camera.lookAt(0, 0, 0); camera.updateMatrixWorld(true);
const view = Object.assign(Object.create(Viewport.prototype), {container: new Element('div'),
  inspectionPoints: [], inspectionMarkers: new THREE.Group(), measurementLabel: new Element('output'),
  cameraId: null, cameras: new Map(), freeCamera: camera, rect: {x: 40, y: 30, width: 400, height: 240},
  project: {units: 'cm', scene: {background: [1, 1, 1]}}});
view.measurementLabel.className = 'measurement-label';
view.createInspectionOverlay();
const point = (x, y = 0, z = 0) => ({object_id: 'unchanged-model', local: [x, y, z], world: [x, y, z]});
const points = [point(-.5), point(.5)];
const checks = [];
view.setInspectionPoints([points[0]]); view.updateInspectionOverlay();
assert.equal(view.inspectionMeasurement(), null);
assert.equal(view.inspectionOverlay.getAttribute('hidden'), null);
assert.equal(view.inspectionPointOverlays[0].label.textContent, 'A');
assert.equal(view.inspectionPointOverlays[0].label.hidden, false);
assert.equal(view.inspectionPointOverlays[1].label.hidden, true);
assert.equal(view.inspectionPointOverlays[0].marker.getAttribute('visibility'), 'visible');
assert.equal(view.inspectionLine.getAttribute('visibility'), 'hidden');
assert.equal(view.measurementLabel.hidden, true);
checks.push('Single sampled point has a visible A marker; no incomplete distance is invented');

view.setInspectionPoints(points); view.updateInspectionOverlay();
assert.equal(view.inspectionMarkers.children.length, 3, 'Existing temporary 3D group contract retained');
assert.deepEqual(JSON.parse(JSON.stringify(view.inspectionMeasurement())), {distance: 1, display_distance: 100, display_units: 'cm', calibrated: false});
assert.equal(view.measurementLabel.textContent, '100 cm');
assert.equal(view.measurementLabel.hidden, false);
assert.equal(view.inspectionPointOverlays[1].label.textContent, 'B');
assert.equal(view.inspectionPointOverlays[1].label.hidden, false);
assert.equal(view.inspectionLine.getAttribute('visibility'), 'visible');
assert.equal(view.inspectionLineOutline.getAttribute('visibility'), 'visible');
assert.equal(view.inspectionLine.getAttribute('x1'), '150');
assert.equal(view.inspectionLine.getAttribute('x2'), '250');
assert.equal(view.inspectionLine.getAttribute('y1'), '120');
assert.equal(view.inspectionLine.getAttribute('stroke-width'), '2');
assert.equal(view.inspectionLineOutline.getAttribute('stroke-width'), '6');
assert.equal(view.inspectionOverlay.style.left, '40px');
assert.equal(view.inspectionOverlay.style.top, '30px');
assert.equal(view.inspectionOverlay.getAttribute('viewBox'), '0 0 400 240');
checks.push('Completed A/B endpoints and screen-width contrast line use actual camera projection and camera-rect origin');

camera.position.x = .25; camera.lookAt(.25, 0, 0);
view.updateInspectionOverlay();
assert.equal(view.inspectionLine.getAttribute('x1'), '125', 'Camera matrix refreshes before projection');
camera.position.x = 0; camera.lookAt(0, 0, 0);
view.setInspectionPoints([point(-5), point(5)]); view.updateInspectionOverlay();
assert.equal(view.measurementLabel.hidden, false, 'Cross-view line retains distance despite offscreen endpoints');
assert.ok(view.inspectionPointOverlays.every(({label}) => label.hidden));
assert.equal(view.measurementLabel.style.left, '240px');
view.setInspectionPoints([point(-10), point(-5)]); view.updateInspectionOverlay();
assert.equal(view.measurementLabel.hidden, true, 'Fully offscreen segment has no detached label');
view.setInspectionPoints([point(-.5, 0, 11), point(.5, 0, 11)]); view.updateInspectionOverlay();
assert.equal(view.inspectionLine.getAttribute('visibility'), 'hidden');
assert.equal(view.measurementLabel.hidden, true);
assert.ok(view.inspectionPointOverlays.every(({label}) => label.hidden));
checks.push('Camera changes stay aligned; crossing segments, offscreen segments and points behind camera are handled');

view.setInspectionPoints([point(1.97, 1.17), point(1.99, 1.19)]); view.updateInspectionOverlay();
assert.ok(parseFloat(view.measurementLabel.style.left) <= view.rect.x + view.rect.width - 63);
assert.ok(parseFloat(view.measurementLabel.style.top) >= view.rect.y + 42);
for (const {label} of view.inspectionPointOverlays) {
  assert.ok(parseFloat(label.style.left) <= view.rect.x + view.rect.width - 13);
  assert.ok(parseFloat(label.style.top) >= view.rect.y + 13);
}
view.project = {source: {path: 'original.blend'}};
view.setInspectionPoints(points); i18n.setLanguage('zh-Hant'); view.refreshMeasurementLabel();
assert.equal(view.inspectionMeasurement().display_units, 'preview_world_units');
assert.equal(view.measurementLabel.textContent, '1 預覽單位');
view.setInspectionPoints([]);
assert.equal(view.inspectionOverlay.getAttribute('hidden'), '');
assert.equal(view.measurementLabel.hidden, true);
assert.ok(view.inspectionPointOverlays.every(({label}) => label.hidden));
assert.equal(view.inspectionMeasurement(), null);
checks.push('Edge labels remain inside camera rect; preview units stay uncalibrated; clearing removes all screen feedback immediately');

// Exercise actual ray picking against an allowed part and an out-of-scope cover.
const content = new THREE.Group();
const target = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial());
target.userData.editorId = 'lid'; content.add(target);
const cover = new THREE.Mesh(new THREE.BoxGeometry(1.2, 1.2, .2), new THREE.MeshBasicMaterial());
cover.userData.editorId = 'lid-lining'; cover.position.z = 1; content.add(cover);
content.updateMatrixWorld(true);
const misses = [], hits = [], selections = [];
Object.assign(view, {content, helpers: new THREE.Group(), raycaster: new THREE.Raycaster(), pointer: new THREE.Vector2(),
  inspection: {objectIds: new Set(['lid'])}, inspectionMode: 'measure',
  renderer: {domElement: {getBoundingClientRect: () => ({left: 0, top: 0})}},
  select: id => selections.push(id), onSelect: id => selections.push(id),
  onSurfacePick: hit => hits.push(hit), onInspectionMiss: reason => misses.push(reason)});
view.helpers.visible = false;
view.setInspectionPoints([{object_id: 'lid', local: [0, 0, .5], world: [0, 0, .5]}]);
const preserved = JSON.stringify(view.inspectionPoints);
view.pick({clientX: 20, clientY: 150});
view.pick({clientX: 430, clientY: 40});
view.pick({clientX: 240, clientY: 150});
assert.deepEqual(misses, ['outside-view', 'no-surface', 'out-of-scope']);
assert.equal(hits.length, 0, 'Cannot penetrate a visible out-of-scope cover');
assert.equal(selections.length, 0, 'Misses preserve selection');
assert.equal(JSON.stringify(view.inspectionPoints), preserved, 'Misses preserve the existing A point');
delete cover.userData.editorId;
view.pick({clientX: 240, clientY: 150});
assert.equal(misses.at(-1), 'no-surface');
assert.equal(hits.length, 0, 'An unmapped foreground surface still occludes the allowed part');
cover.visible = false;
view.pick({clientX: 240, clientY: 150});
assert.equal(hits.length, 1);
assert.equal(hits[0].object_id, 'lid');
const missCount = misses.length;
view.inspectionMode = null;
view.pick({clientX: 20, clientY: 150});
view.pick({clientX: 430, clientY: 40});
assert.equal(misses.length, missCount, 'Ordinary selection does not emit inspection guidance');
delete view.onInspectionMiss; view.inspectionMode = 'measure';
assert.doesNotThrow(() => view.pick({clientX: 20, clientY: 150}), 'Callback remains optional for existing clients');
checks.push('Real pick misses explain outside-view / no-surface / out-of-scope, preserve A and selection, and never penetrate blocked surfaces');

// Rendering must not restore the whole-object box over the surface tool visuals.
Object.assign(view, {objects: new Map([['lid', target]]), interaction: {editable: false, helpers: false},
  transform: {detach() {}}, selection: new THREE.Box3Helper(new THREE.Box3()), selectedId: 'lid',
  orbit: {update() {}}, decorations: [], viewTheme: {background: 0x191a1c}, width: 480, height: 300,
  renderer: {setScissorTest() {}, setViewport() {}, setClearColor() {}, clear() {}, setScissor() {}, render() {}}});
delete view.select;
view.select('lid'); view.draw();
assert.equal(view.selection.visible, false);
assert.equal(view.selectedId, 'lid');
view.inspectionMode = null; view.draw();
assert.equal(view.selection.visible, false, 'Retained surface points still hide the selection box');
view.setInspectionPoints([]); view.select('lid'); view.draw();
assert.equal(view.selection.visible, true, 'Ordinary object selection keeps its box');
view.inspectionMode = 'point'; view.draw();
assert.equal(view.selection.visible, false, 'A point tool hides the box before the first sample');
checks.push('Point/measure modes and retained samples hide only the selection box; selectedId and ordinary selection remain intact');
console.log(JSON.stringify({status: 'PASS', checks}, null, 2));
