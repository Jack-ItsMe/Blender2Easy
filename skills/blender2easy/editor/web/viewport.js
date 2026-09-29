import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {TransformControls} from 'three/addons/controls/TransformControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {RoundedBoxGeometry} from 'three/addons/geometries/RoundedBoxGeometry.js';
import {RectAreaLightUniformsLib} from 'three/addons/lights/RectAreaLightUniformsLib.js';
import {unitScale, blenderQuaternion, blenderEuler, sampleTrack, nativeFrameSeconds, cameraProjection} from './math.js';
import {registerMessages, t, formatNumber, getTheme, onLocaleChange, onThemeChange} from './i18n.js';
import {messages} from './locales/viewport.js';

registerMessages(messages);

// Viewing aids only. Authored objects, materials, lights and render settings never
// read this palette. Keep the shell background in sync with theme.css.
const VIEWPORT_THEMES = {
  dark: {background: 0x1b1d20, grid: 0x656669, gridCenter: 0x909195, selection: 0x9cb6cc,
    empty: 0x94a7b3, camera: 0xa4a6bb, light: 0xb6ad99},
  light: {background: 0xf1f1ef, grid: 0xaaabad, gridCenter: 0x77787c, selection: 0x4f6b84,
    empty: 0x627988, camera: 0x777991, light: 0x887c61},
};

const Z_UP = new THREE.Vector3(0, 0, 1);
const color = value => new THREE.Color().setRGB(...value.slice(0, 3), THREE.SRGBColorSpace);
const vector = (value, factor = 1) => new THREE.Vector3(...value).multiplyScalar(factor);
const materialsOf = object => object.material ? (Array.isArray(object.material) ? object.material : [object.material]) : [];
const svgElement = (name, attributes = {}) => {
  const element = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
};
const featureCache = new WeakMap();
const featureBoundsCache = new WeakMap();
const SNAP_VERTEX_PX = 8, SNAP_EDGE_PX = 11;

// Weld only the topology lookup, never the asset. Split UV/normal vertices at
// identical positions must share adjacency, or every render triangle is an edge.
function featureTopology(geometry) {
  const position = geometry.getAttribute('position'), index = geometry.index;
  if (!position) return null;
  const signature = [position.version, index?.version, position.count, index?.count,
    geometry.drawRange.start, geometry.drawRange.count, JSON.stringify(geometry.groups)].join(':');
  const cached = featureCache.get(geometry);
  if (cached?.position === position && cached?.index === index && cached.signature === signature) return cached.topology;
  const count = index?.count ?? position.count;
  if (count / 3 > 40000) return {unavailable: 'dense'};
  const bounds = new THREE.Box3().setFromBufferAttribute(position);
  const tolerance = Math.max(bounds.getSize(new THREE.Vector3()).length() * 1e-7, 1e-12);
  const vertices = [], weld = new Map(), ids = [];
  for (let i = 0; i < position.count; i++) {
    const point = new THREE.Vector3().fromBufferAttribute(position, i);
    const key = [point.x, point.y, point.z].map(value => Math.round(value / tolerance)).join(',');
    if (!weld.has(key)) {weld.set(key, vertices.length); vertices.push(point);}
    ids.push(weld.get(key));
  }
  const faces = [], edges = new Map();
  const start = Math.max(0, geometry.drawRange.start), end = Math.min(count, start + geometry.drawRange.count);
  for (let offset = start; offset + 2 < end; offset += 3) {
    const triangle = [0, 1, 2].map(delta => ids[index ? index.getX(offset + delta) : offset + delta]);
    const [a, b, c] = triangle.map(id => vertices[id]);
    const normal = b.clone().sub(a).cross(c.clone().sub(a));
    if (normal.lengthSq() < tolerance ** 4) continue;
    const group = geometry.groups.find(entry => offset >= entry.start && offset < entry.start + entry.count);
    const faceIndex = faces.length;
    faces.push({normal: normal.normalize(), center: a.clone().add(b).add(c).multiplyScalar(1 / 3), materialIndex: group?.materialIndex ?? 0});
    for (let side = 0; side < 3; side++) {
      const first = triangle[side], second = triangle[(side + 1) % 3];
      const key = first < second ? `${first}:${second}` : `${second}:${first}`;
      if (!edges.has(key)) edges.set(key, {a: first, b: second, faces: []});
      edges.get(key).faces.push(faceIndex);
    }
  }
  const topology = {vertices, faces, edges: [...edges.values()], size: bounds.getSize(new THREE.Vector3()).length()};
  featureCache.set(geometry, {position, index, signature, topology});
  return topology;
}

function isVisibleHit(hit) {
  for (let node = hit.object; node; node = node.parent) if (!node.visible) return false;
  const materials = materialsOf(hit.object);
  const material = materials[hit.face?.materialIndex ?? 0];
  return material?.visible !== false;
}

function projectFeature(world, camera, rect) {
  const clip = new THREE.Vector4(world.x, world.y, world.z, 1).applyMatrix4(camera.matrixWorldInverse);
  const depth = -clip.z;
  clip.applyMatrix4(camera.projectionMatrix);
  if (clip.w <= 0) return null;
  const z = clip.z / clip.w;
  if (z < -1 || z > 1) return null;
  return {x: (clip.x / clip.w + 1) * rect.width / 2, y: (1 - clip.y / clip.w) * rect.height / 2, w: clip.w, depth};
}

function disposeTree(root) {
  const geometries = new Set(), materials = new Set(), textures = new Set();
  for (const material of root.userData.unusedMaterials ?? []) materials.add(material);
  root.traverse(object => {
    if (object.geometry) geometries.add(object.geometry);
    for (const material of materialsOf(object)) {
      materials.add(material);
      for (const value of Object.values(material)) if (value?.isTexture) textures.add(value);
    }
  });
  for (const texture of textures) texture.dispose();
  for (const material of materials) material.dispose();
  for (const geometry of geometries) geometry.dispose();
}

function applyTransform(object, spec, factor) {
  object.position.copy(vector(spec.location ?? [0, 0, 0], factor));
  object.quaternion.fromArray(blenderQuaternion(spec.rotation_deg ?? [0, 0, 0]));
  object.scale.fromArray(spec.scale ?? [1, 1, 1]);
  object.userData.rotationReference = [...(spec.rotation_deg ?? [0, 0, 0])];
}

function geometryFor(spec, factor) {
  const [x, y, z] = (spec.dimensions ?? [1, 1, 1]).map(value => value * factor);
  if (spec.type === 'cube') {
    const radius = Math.min((spec.bevel ?? 0) * factor, x / 2, y / 2, z / 2);
    return radius > 0 ? new RoundedBoxGeometry(x, y, z, 3, radius) : new THREE.BoxGeometry(x, y, z);
  }
  if (spec.type === 'cylinder') {
    const geometry = new THREE.CylinderGeometry(0.5, 0.5, 1, 64);
    geometry.rotateX(Math.PI / 2);
    geometry.scale(x, y, z);
    return geometry;
  }
  const geometry = new THREE.SphereGeometry(0.5, 48, 24);
  geometry.rotateX(Math.PI / 2);
  geometry.scale(x, y, z);
  return geometry;
}

/** Blender-compatible Z-up editor viewport. All external transforms use declared units. */
export class Viewport {
  constructor(container, {onSelect = () => {}, onTransform = () => {}, onSurfacePick = () => {}, onInspectionMiss = () => {}, onInspectionHover = () => {}} = {}) {
    this.container = container;
    this.onSelect = onSelect;
    this.onTransform = onTransform;
    this.onSurfacePick = onSurfacePick;
    this.onInspectionMiss = onInspectionMiss;
    this.onInspectionHover = onInspectionHover;
    this.inspectionSnapEnabled = true;
    this.inspectionHoverPointer = null;
    this.inspectionHoverCandidate = null;
    this.inspectionHoverKey = null;
    this.inspection = null;
    this.inspectionMode = null;
    this.inspectionPoints = [];
    this.isolationIds = null;
    this.xrayEnabled = false;
    this.visibilityBaseline = new Map();
    this.xrayMaterials = new Map();
    this.objects = new Map();
    this.cameras = new Map();
    this.nativeBases = new Map();
    this.nativeMaterials = new Map();
    this.actions = [];
    this.decorations = [];
    this.frame = 1;
    this.factor = 1;
    this.generation = 0;
    this.cameraId = null;
    this.selectedId = null;
    this.interaction = {editable: true, helpers: true};
    this.scene = new THREE.Scene();
    this.content = new THREE.Group();
    this.helpers = new THREE.Group();
    this.scene.add(this.content, this.helpers);
    this.inspectionMarkers = new THREE.Group();
    this.scene.add(this.inspectionMarkers);
    this.measurementLabel = document.createElement('output');
    this.measurementLabel.className = 'measurement-label';
    this.measurementLabel.hidden = true;
    this.measurementLabel.setAttribute('aria-live', 'polite');
    container.appendChild(this.measurementLabel);
    this.createInspectionOverlay();
    this.surfaceCursor = document.createElement('span');
    this.surfaceCursor.className = 'surface-cursor'; this.surfaceCursor.hidden = true;
    this.surfaceCursor.setAttribute('aria-hidden', 'true'); container.appendChild(this.surfaceCursor);
    this.renderer = new THREE.WebGLRenderer({antialias: true, alpha: false, powerPreference: 'high-performance'});
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;
    this.renderer.domElement.className = 'viewport-canvas';
    this.renderer.domElement.style.cssText = 'display:block;width:100%;height:100%;touch-action:none';
    this.renderer.domElement.tabIndex = 0;
    container.appendChild(this.renderer.domElement);
    this.message = document.createElement('div');
    this.message.className = 'viewport-system-message';
    this.message.setAttribute('role', 'status');
    container.appendChild(this.message);
    this.freeCamera = new THREE.PerspectiveCamera(40, 1, 0.001, 10000);
    this.freeCamera.up.copy(Z_UP);
    this.freeCamera.position.set(5, -7, 4.5);
    this.orbit = new OrbitControls(this.freeCamera, this.renderer.domElement);
    this.orbit.target.set(0, 0, 0.7);
    this.orbit.enableDamping = true;
    this.orbit.dampingFactor = 0.12;
    this.orbit.update();
    this.transform = new TransformControls(this.freeCamera, this.renderer.domElement);
    this.transform.setSpace('local');
    this.transform.setSize(0.8);
    this.transformHelper = this.transform.getHelper();
    this.scene.add(this.transformHelper);
    this.transform.addEventListener('dragging-changed', event => {this.orbit.enabled = !event.value && !this.cameraId;});
    this.transform.addEventListener('mouseDown', () => {this.dragged = true;});
    this.transform.addEventListener('mouseUp', event => {
      const id = this.selectedId;
      const result = this.getTransform(id);
      const property = {translate: 'location', rotate: 'rotation_deg', scale: 'scale'}[event.mode];
      // Commit only the edited channel. Sending all channels would also replace
      // unrelated native animation curves and create unwanted procedural keys.
      if (result && property) this.onTransform(id, {[property]: result[property]});
    });
    this.grid = new THREE.GridHelper(20, 40, 0x9daebc, 0xc3cdd5);
    this.grid.rotation.x = Math.PI / 2;
    this.grid.position.z = 0.0001;
    this.grid.material.transparent = true;
    this.grid.material.opacity = 0.35;
    this.scene.add(this.grid);
    this.gridEnabled = true;
    this.selection = new THREE.Box3Helper(new THREE.Box3(), 0x32a3f8);
    this.selection.material.depthTest = false;
    this.selection.material.transparent = true;
    this.selection.renderOrder = 20;
    this.selection.visible = false;
    this.scene.add(this.selection);
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.pointerDown = event => {
      this.surfaceCursor.hidden = true;
      this.pointerStart = [event.clientX, event.clientY];
      // TransformControls receives pointerdown before this handler.
      this.dragged = !!this.transform.dragging;
    };
    this.pointerUp = event => {
      if (event.button !== 0 || this.dragged || !this.pointerStart) return;
      if (Math.hypot(event.clientX - this.pointerStart[0], event.clientY - this.pointerStart[1]) > 4) return;
      this.pick(event);
    };
    this.renderer.domElement.addEventListener('pointerdown', this.pointerDown);
    this.renderer.domElement.addEventListener('pointerup', this.pointerUp);
    this.inspectionPointerMove = event => {
      if (this.inspectionMode) this.inspectionHoverPointer = {clientX: event.clientX, clientY: event.clientY};
    };
    this.inspectionPointerLeave = () => {this.inspectionHoverPointer = null; this.clearInspectionHover();};
    this.renderer.domElement.addEventListener('pointermove', this.inspectionPointerMove);
    this.renderer.domElement.addEventListener('pointerleave', this.inspectionPointerLeave);
    this.inspectionKey = event => {
      if (!this.inspectionMode || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Enter', ' '].includes(event.key)) return;
      event.preventDefault();
      const uv = this.keyboardPickUV ?? [0.5, 0.5], step = event.shiftKey ? 0.1 : 0.025;
      if (event.key === 'ArrowLeft') uv[0] -= step; if (event.key === 'ArrowRight') uv[0] += step;
      if (event.key === 'ArrowUp') uv[1] -= step; if (event.key === 'ArrowDown') uv[1] += step;
      this.keyboardPickUV = uv.map(value => Math.max(0, Math.min(1, value)));
      const x = this.rect.x + this.keyboardPickUV[0] * this.rect.width, y = this.rect.y + this.keyboardPickUV[1] * this.rect.height;
      this.surfaceCursor.hidden = false; this.surfaceCursor.style.left = `${x}px`; this.surfaceCursor.style.top = `${y}px`;
      const bounds = this.renderer.domElement.getBoundingClientRect();
      this.inspectionHoverPointer = {clientX: bounds.left + x, clientY: bounds.top + y};
      if (event.key === 'Enter' || event.key === ' ') {
        this.pick(this.inspectionHoverPointer);
      }
    };
    this.renderer.domElement.addEventListener('keydown', this.inspectionKey);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    RectAreaLightUniformsLib.init();
    this.unsubscribeLocale = onLocaleChange(() => this.refreshLocale());
    this.unsubscribeTheme = onThemeChange(() => this.applyUiTheme());
    this.refreshLocale();
    this.applyUiTheme();
    this.resize();
    this.renderer.setAnimationLoop(() => this.draw());
  }

  setMessage(key = null) {
    this.messageKey = key;
    this.message.textContent = key ? t(key) : '';
  }

  refreshLocale() {
    const canvas = this.renderer.domElement;
    // Review supplies its own read-only keyboard instructions. Refresh our
    // generic label only while we still own it, regardless of listener order.
    const currentLabel = canvas.getAttribute('aria-label');
    if (!currentLabel || currentLabel === this.defaultCanvasLabel) {
      this.defaultCanvasLabel = t('viewport.canvas');
      canvas.setAttribute('aria-label', this.defaultCanvasLabel);
    }
    this.message.textContent = this.messageKey ? t(this.messageKey) : '';
    this.refreshMeasurementLabel();
  }

  refreshMeasurementLabel() {
    const measurement = this.inspectionMeasurement();
    if (!measurement) return;
    const units = measurement.display_units === 'preview_world_units' ? null : measurement.display_units;
    // Locale affects presentation only; preserve the original five significant
    // digits and declared unit conversion, including uncalibrated preview units.
    const value = formatNumber(Number(measurement.display_distance.toPrecision(5)), {maximumSignificantDigits: 5, useGrouping: false});
    this.measurementLabel.textContent = t('viewport.distance', {value, unit: units || t('viewport.previewUnits')});
    this.measurementLabel.title = t(units ? 'viewport.modelMeasurement' : 'viewport.previewMeasurement');
  }

  /** Read-only display data, shared by the viewport label and review guidance. */
  inspectionMeasurement() {
    if (this.inspectionPoints.length !== 2) return null;
    const vertices = this.inspectionPoints.map(point => new THREE.Vector3(...point.world));
    const distance = vertices[0].distanceTo(vertices[1]);
    const units = this.project?.scene && !this.project.source ? (this.project.units ?? 'm') : null;
    const displayDistance = units ? distance / unitScale(units) : distance;
    return {distance, display_distance: displayDistance, display_units: units || 'preview_world_units', calibrated: false};
  }

  createInspectionOverlay() {
    // SVG strokes stay a reliable screen width on every WebGL backend. The
    // contrast underlay keeps actual sampled endpoints legible on light or dark
    // geometry, including when the view rotates them behind a surface.
    this.inspectionOverlay = svgElement('svg', {class: 'inspection-overlay', 'aria-hidden': 'true', focusable: 'false'});
    this.inspectionOverlay.style.cssText = 'position:absolute;pointer-events:none;overflow:hidden';
    this.inspectionOverlay.setAttribute('hidden', '');
    this.inspectionLineOutline = svgElement('line', {class: 'inspection-line-outline', stroke: '#161719', 'stroke-width': 6, 'stroke-linecap': 'round'});
    this.inspectionLine = svgElement('line', {class: 'inspection-line', stroke: '#f6f6f0', 'stroke-width': 2, 'stroke-linecap': 'round'});
    this.inspectionOverlay.append(this.inspectionLineOutline, this.inspectionLine);
    this.inspectionSnapPreview = svgElement('g', {class: 'inspection-snap-preview', visibility: 'hidden'});
    this.snapEdgeOutline = svgElement('line', {class: 'inspection-snap-edge-outline', stroke: '#161719', 'stroke-width': 6, 'stroke-linecap': 'round'});
    this.snapEdgeLine = svgElement('line', {class: 'inspection-snap-edge-line', stroke: '#b8d2e7', 'stroke-width': 2.5, 'stroke-linecap': 'round'});
    this.snapVertexOutline = svgElement('circle', {class: 'inspection-snap-vertex-outline', r: 7, fill: '#161719', stroke: '#b8d2e7', 'stroke-width': 1.5});
    this.snapVertexCore = svgElement('circle', {class: 'inspection-snap-vertex-core', r: 3, fill: '#b8d2e7'});
    this.inspectionSnapPreview.append(this.snapEdgeOutline, this.snapEdgeLine, this.snapVertexOutline, this.snapVertexCore);
    this.inspectionOverlay.append(this.inspectionSnapPreview);
    this.inspectionPointOverlays = ['A', 'B'].map(letter => {
      const marker = svgElement('g');
      const outline = svgElement('circle', {class: 'inspection-point-outline', r: 7, fill: '#161719', stroke: '#f6f6f0', 'stroke-width': 1.5});
      const core = svgElement('circle', {class: 'inspection-point-core', r: 3.5, fill: '#f6f6f0'});
      marker.append(outline, core);
      this.inspectionOverlay.append(marker);
      const label = document.createElement('span');
      label.className = 'inspection-point-label';
      label.textContent = letter;
      label.hidden = true;
      label.setAttribute('aria-hidden', 'true');
      this.container.appendChild(label);
      return {marker, label};
    });
    this.container.appendChild(this.inspectionOverlay);
  }

  updateInspectionOverlay(camera = this.activeCamera) {
    if (!this.inspectionOverlay) return;
    const points = this.inspectionPoints;
    const snap = this.inspectionHoverCandidate;
    this.inspectionOverlay.toggleAttribute('hidden', !points.length && !snap);
    for (const {marker, label} of this.inspectionPointOverlays) {
      marker.setAttribute('visibility', 'hidden');
      label.hidden = true;
    }
    this.inspectionLineOutline.setAttribute('visibility', 'hidden');
    this.inspectionLine.setAttribute('visibility', 'hidden');
    this.measurementLabel.hidden = true;
    this.inspectionSnapPreview?.setAttribute('visibility', 'hidden');
    if (!points.length && !snap) return;
    camera.updateMatrixWorld(true);
    const r = this.rect;
    Object.assign(this.inspectionOverlay.style, {left: `${r.x}px`, top: `${r.y}px`, width: `${r.width}px`, height: `${r.height}px`});
    this.inspectionOverlay.setAttribute('viewBox', `0 0 ${r.width} ${r.height}`);
    if (snap && this.inspectionSnapPreview) {
      const preview = projectFeature(new THREE.Vector3(...snap.surface.world), camera, r);
      if (preview) {
        this.inspectionSnapPreview.setAttribute('visibility', 'visible');
        for (const circle of [this.snapVertexOutline, this.snapVertexCore]) {
          circle.setAttribute('cx', preview.x); circle.setAttribute('cy', preview.y);
        }
        const edge = snap.edgeWorld?.map(point => projectFeature(point, camera, r));
        for (const line of [this.snapEdgeOutline, this.snapEdgeLine]) {
          line.setAttribute('visibility', edge?.every(Boolean) ? 'visible' : 'hidden');
          if (edge?.every(Boolean)) for (const [key, value] of Object.entries({x1: edge[0].x, y1: edge[0].y, x2: edge[1].x, y2: edge[1].y})) line.setAttribute(key, value);
        }
      }
    }
    const projected = points.map(point => {
      const ndc = new THREE.Vector3(...point.world).project(camera);
      return {x: (ndc.x + 1) * r.width / 2, y: (1 - ndc.y) * r.height / 2,
        inDepth: Number.isFinite(ndc.x) && Number.isFinite(ndc.y) && ndc.z >= -1 && ndc.z <= 1};
    });
    const clamp = (value, low, high) => Math.min(Math.max(value, low), Math.max(low, high));
    for (const [index, point] of projected.entries()) {
      if (!point.inDepth || point.x < 0 || point.y < 0 || point.x > r.width || point.y > r.height) continue;
      const {marker, label} = this.inspectionPointOverlays[index];
      marker.setAttribute('visibility', 'visible');
      marker.setAttribute('transform', `translate(${point.x} ${point.y})`);
      label.hidden = false;
      const halfWidth = Math.max(10, (label.offsetWidth || 20) / 2);
      const halfHeight = Math.max(10, (label.offsetHeight || 20) / 2);
      label.style.left = `${r.x + clamp(point.x + (index === 0 ? -17 : 17), halfWidth + 3, r.width - halfWidth - 3)}px`;
      label.style.top = `${r.y + clamp(point.y - 17, halfHeight + 3, r.height - halfHeight - 3)}px`;
    }
    if (projected.length !== 2 || projected.some(point => !point.inDepth)) return;
    const [a, b] = projected;
    for (const line of [this.inspectionLineOutline, this.inspectionLine]) {
      line.setAttribute('visibility', 'visible');
      for (const [key, value] of Object.entries({x1: a.x, y1: a.y, x2: b.x, y2: b.y})) line.setAttribute(key, value);
    }
    // A projected segment may cross the view with both endpoints outside it.
    // Clip analytically before placing its label; SVG clips the line itself.
    const delta = {x: b.x - a.x, y: b.y - a.y};
    let from = 0, to = 1;
    for (const [p, q] of [[-delta.x, a.x], [delta.x, r.width - a.x], [-delta.y, a.y], [delta.y, r.height - a.y]]) {
      if (p === 0) {if (q < 0) return; continue;}
      const ratio = q / p;
      if (p < 0) from = Math.max(from, ratio); else to = Math.min(to, ratio);
      if (from > to) return;
    }
    const midpoint = {x: a.x + delta.x * (from + to) / 2, y: a.y + delta.y * (from + to) / 2};
    const length = Math.hypot(delta.x, delta.y);
    const normal = length > 1 ? {x: -delta.y / length, y: delta.x / length} : {x: 0, y: -1};
    if (normal.y > 0) {normal.x *= -1; normal.y *= -1;}
    this.measurementLabel.hidden = false;
    const halfWidth = (this.measurementLabel.offsetWidth || 120) / 2;
    const height = this.measurementLabel.offsetHeight || 34;
    const offset = 28 + Math.abs(normal.x) * halfWidth + Math.abs(normal.y) * height / 2;
    this.measurementLabel.style.left = `${r.x + clamp(midpoint.x + normal.x * offset, halfWidth + 8, r.width - halfWidth - 8)}px`;
    this.measurementLabel.style.top = `${r.y + clamp(midpoint.y + normal.y * offset + height / 2, height + 8, r.height - 8)}px`;
  }

  applyUiTheme() {
    this.viewTheme = VIEWPORT_THEMES[getTheme()] ?? VIEWPORT_THEMES.dark;
    const positions = this.grid.geometry.getAttribute('position');
    const colors = this.grid.geometry.getAttribute('color');
    const center = new THREE.Color(this.viewTheme.gridCenter), line = new THREE.Color(this.viewTheme.grid);
    for (let index = 0; index < positions.count; index += 2) {
      const isCenter = (positions.getX(index) === 0 && positions.getX(index + 1) === 0)
        || (positions.getZ(index) === 0 && positions.getZ(index + 1) === 0);
      const tint = isCenter ? center : line;
      colors.setXYZ(index, tint.r, tint.g, tint.b);
      colors.setXYZ(index + 1, tint.r, tint.g, tint.b);
    }
    colors.needsUpdate = true;
    this.selection.material.color.setHex(this.viewTheme.selection);
    this.inspectionMarkers.traverse(object => {
      for (const material of materialsOf(object)) material.color?.setHex(this.viewTheme.selection);
    });
    for (const {mesh, kind} of this.decorations) mesh.material.color.setHex(this.viewTheme[kind]);
    this.updateViewingBackground();
  }

  updateViewingBackground() {
    // A project camera keeps its authored background (or the legacy fallback).
    // Free orbit and camera letterboxing use the interface theme. This is
    // presentation state; project.scene.background is never changed.
    this.scene.background = this.cameraId
      ? (this.authoredBackground ?? color([0.91, 0.93, 0.96]))
      : new THREE.Color(this.viewTheme?.background ?? VIEWPORT_THEMES.dark.background);
  }

  async setProject(project, {nativePreview = null, preserveView = true} = {}) {
    this.restoreInspectionEffects();
    const generation = ++this.generation;
    const firstProject = !this.project;
    const previousProjectId = this.project?.id;
    this.project = project;
    this.factor = project.source ? 1 : unitScale(project.units);
    this.authoredBackground = color(project.scene?.background ?? [0.91, 0.93, 0.96]);
    this.setMessage();
    if (!preserveView || previousProjectId !== project.id) this.frame = project.shots?.[0]?.source_range?.[0] ?? 1;
    if (project.source && nativePreview?.url && nativePreview.url === this.nativeUrl && this.nativeRoot) {
      this.manifest = nativePreview.manifest;
      this.applyNativeOverrides();
    } else {
      this.clearContent();
      if (project.source) {
        this.manifest = nativePreview?.manifest ?? null;
        if (nativePreview?.url) {
          this.setMessage('viewport.loading');
          let gltf;
          try {gltf = await new GLTFLoader().loadAsync(nativePreview.url);}
          catch (error) {
            if (generation === this.generation) this.setMessage('viewport.loadFailed');
            throw error;
          }
          if (generation !== this.generation || this.disposed) {disposeTree(gltf.scene); return;}
          this.nativeUrl = nativePreview.url;
          this.nativeRoot = gltf.scene;
          this.content.add(gltf.scene);
          this.registerNative(gltf, nativePreview.manifest);
          this.setMessage();
        } else {
          this.setMessage('viewport.generatePreview');
        }
      } else {
        this.buildProcedural(project.scene);
      }
    }
    if (generation !== this.generation || this.disposed) return;
    this.updateViewingBackground();
    this.addStudioLight(project.scene?.world_strength ?? 0.5);
    this.setFrame(this.frame);
    if (firstProject || !preserveView || previousProjectId !== project.id) {
      this.cameraId = null;
      this.frameAll();
    }
    this.setCamera(this.cameras.has(this.cameraId) ? this.cameraId : null);
    this.select(this.objects.has(this.selectedId) ? this.selectedId : null);
    this.applyInspectionEffects();
    this.resize();
  }

  clearContent() {
    this.restoreInspectionEffects();
    this.setInspectionPoints([]);
    this.transform.detach();
    if (this.mixer) {
      this.mixer.stopAllAction();
      this.mixer.uncacheRoot(this.nativeRoot);
    }
    this.mixer = null;
    this.actions = [];
    this.nativeRoot = null;
    this.nativeUrl = null;
    disposeTree(this.content);
    disposeTree(this.helpers);
    this.content.clear();
    this.content.userData.unusedMaterials = [];
    this.helpers.clear();
    this.objects.clear();
    this.cameras.clear();
    this.nativeBases.clear();
    this.nativeMaterials.clear();
    this.decorations = [];
  }

  buildProcedural(config) {
    const materials = new Map((config.materials ?? []).map(spec => [spec.id, new THREE.MeshStandardMaterial({
      name: spec.id, color: color(spec.color), roughness: spec.roughness ?? 0.4,
      metalness: spec.metallic ?? 0, opacity: spec.color[3] ?? 1,
      transparent: (spec.color[3] ?? 1) < 1, side: THREE.DoubleSide,
    })]));
    const fallback = new THREE.MeshStandardMaterial({color: 0xa6b4c1, roughness: 0.55});
    for (const spec of config.objects ?? []) {
      const object = spec.type === 'empty' ? new THREE.Group() : new THREE.Mesh(geometryFor(spec, this.factor), materials.get(spec.material) ?? fallback);
      object.name = spec.id;
      object.userData.editorId = spec.id;
      object.userData.spec = spec;
      applyTransform(object, spec, this.factor);
      this.objects.set(spec.id, object);
      this.content.add(object);
      if (spec.type === 'empty') this.addMarker(object, 0x557c9d, 'empty');
    }
    for (const spec of config.cameras ?? []) {
      const camera = spec.type === 'ORTHO' ? new THREE.OrthographicCamera() : new THREE.PerspectiveCamera();
      camera.name = spec.id;
      camera.up.copy(Z_UP);
      camera.userData.editorId = spec.id;
      camera.userData.spec = spec;
      camera.position.copy(vector(spec.location, this.factor));
      camera.lookAt(vector(spec.target, this.factor));
      camera.userData.rotationReference = blenderEuler(camera.quaternion.toArray());
      camera.near = Math.max(0.00001, this.factor * 0.001);
      camera.far = 10000;
      this.content.add(camera);
      this.objects.set(spec.id, camera);
      this.cameras.set(spec.id, camera);
      this.updateCameraProjection(camera);
      this.addMarker(camera, 0x7080aa, 'camera');
    }
    for (const spec of config.lights ?? []) {
      let light;
      if (spec.type === 'SUN') light = new THREE.DirectionalLight(0xffffff, spec.energy ?? 1);
      else if (spec.type === 'POINT') light = new THREE.PointLight(0xffffff, (spec.energy ?? 600) / (4 * Math.PI));
      else if (spec.type === 'SPOT') light = new THREE.SpotLight(0xffffff, (spec.energy ?? 600) / Math.PI, 0, Math.PI / 4, 0.35);
      else {
        const size = (spec.size ?? 5) * this.factor;
        light = new THREE.RectAreaLight(0xffffff, (spec.energy ?? 600) / (Math.PI * Math.max(size * size, 0.001)), size, size);
      }
      light.position.copy(vector(spec.location, this.factor));
      light.up.copy(Z_UP);
      const target = vector(spec.target ?? [0, 0, 0], this.factor);
      if (light.target) {light.target.position.copy(target); this.content.add(light.target);}
      if (spec.type !== 'POINT') light.lookAt(target);
      light.name = spec.id;
      light.userData.editorId = spec.id;
      light.userData.spec = spec;
      this.objects.set(spec.id, light);
      this.content.add(light);
      this.addMarker(light, 0xbb9d55, 'light');
    }
    // Parent after all nodes exist. This intentionally keeps local transforms unchanged.
    for (const spec of config.objects ?? []) {
      if (spec.parent && this.objects.has(spec.parent)) this.objects.get(spec.parent).add(this.objects.get(spec.id));
    }
    // Materials with no mesh must still be disposed when replacing a project.
    this.content.userData.unusedMaterials = [...materials.values(), fallback];
  }

  addStudioLight(strength) {
    if (this.studio) this.scene.remove(this.studio);
    this.studio = new THREE.Group();
    this.studio.add(new THREE.AmbientLight(0xffffff, Math.max(0.05, strength) * 1.2));
    // A low, neutral fill makes native previews readable when source lights are unsupported.
    const light = new THREE.DirectionalLight(0xffffff, this.project.source ? 1.7 : 0.55);
    light.position.set(3, -4, 6);
    this.studio.add(light);
    this.scene.add(this.studio);
  }

  addMarker(object, tint, kind) {
    const geometry = kind === 'camera' ? new THREE.ConeGeometry(0.5, 0.7, 4) : new THREE.OctahedronGeometry(0.5);
    const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({color: this.viewTheme?.[kind] ?? tint, wireframe: true, depthTest: false, transparent: true, opacity: 0.75}));
    mesh.userData.editorId = object.userData.editorId;
    mesh.renderOrder = 10;
    this.helpers.add(mesh);
    this.decorations.push({object, mesh, kind});
  }

  registerNative(gltf, manifest) {
    const nodes = new Map();
    gltf.scene.traverse(object => {
      if (object.name) nodes.set(object.name, object);
      if (object.userData?.object_animation_id) nodes.set(object.userData.object_animation_id, object);
      for (const material of materialsOf(object)) {
        if (!this.nativeMaterials.has(material)) this.nativeMaterials.set(material, {
          color: material.color?.clone(), roughness: material.roughness, metalness: material.metalness,
          opacity: material.opacity, transparent: material.transparent,
        });
      }
    });
    for (const spec of manifest?.objects ?? []) {
      const object = nodes.get(spec.id) ?? nodes.get(spec.gltf_node ?? spec.node_name ?? spec.id);
      if (!object) continue;
      object.userData.editorId = spec.id;
      object.userData.spec = spec;
      object.userData.rotationReference = spec.rotation_deg ?? [0, 0, 0];
      this.objects.set(spec.id, object);
      this.nativeBases.set(spec.id, {position: object.position.clone(), quaternion: object.quaternion.clone(), scale: object.scale.clone()});
      if (spec.type === 'EMPTY' || spec.type === 'empty') this.addMarker(object, 0x557c9d, 'empty');
    }
    for (const spec of manifest?.cameras ?? []) {
      const node = this.objects.get(spec.id) ?? nodes.get(spec.gltf_node ?? spec.id);
      let camera = node?.isCamera ? node : null;
      if (!camera) node?.traverse(child => {if (child.isCamera && !camera) camera = child;});
      if (camera) {
        camera.userData.cameraSpec = spec;
        this.cameras.set(spec.id, camera);
        this.addMarker(node ?? camera, 0x7080aa, 'camera');
      }
    }
    if (gltf.animations.length) {
      this.mixer = new THREE.AnimationMixer(gltf.scene);
      for (const clip of gltf.animations) {
        const action = this.mixer.clipAction(clip);
        action.setLoop(THREE.LoopOnce, 1);
        action.clampWhenFinished = true;
        action.play();
        this.actions.push(action);
      }
    }
    this.applyNativeOverrides();
  }

  applyNativeOverrides() {
    const overrides = this.project?.source?.overrides ?? {};
    for (const spec of overrides.objects ?? []) {
      const object = this.objects.get(spec.id);
      if (!object || object.userData.spec?.editable_transform === false) continue;
      if (spec.location) object.position.fromArray(spec.location);
      if (spec.rotation_deg) {object.quaternion.fromArray(blenderQuaternion(spec.rotation_deg)); object.userData.rotationReference = spec.rotation_deg;}
      if (spec.scale) object.scale.fromArray(spec.scale);
    }
    for (const [material, baseline] of this.nativeMaterials) {
      if (baseline.color) material.color.copy(baseline.color);
      material.roughness = baseline.roughness;
      material.metalness = baseline.metalness;
      material.opacity = baseline.opacity;
      material.transparent = baseline.transparent;
      const spec = (overrides.materials ?? []).find(value => value.id === material.name);
      if (!spec) continue;
      if (spec.color) {material.color.copy(color(spec.color)); material.opacity = spec.color[3]; material.transparent = spec.color[3] < 1;}
      if (spec.roughness !== undefined) material.roughness = spec.roughness;
      if (spec.metallic !== undefined) material.metalness = spec.metallic;
      material.needsUpdate = true;
    }
    this.content.updateMatrixWorld(true);
    for (const camera of this.cameras.values()) this.updateCameraProjection(camera, camera.userData.cameraSpec);
    for (const spec of overrides.cameras ?? []) {
      const camera = this.cameras.get(spec.id);
      if (!camera) continue;
      if (spec.location) {
        const position = vector(spec.location);
        if (camera.parent) camera.parent.worldToLocal(position);
        camera.position.copy(position);
      }
      if (spec.target) {camera.up.copy(Z_UP); camera.lookAt(vector(spec.target));}
      this.updateCameraProjection(camera, {...camera.userData.cameraSpec, ...spec});
    }
  }

  setFrame(nativeFrame) {
    const nextFrame = Number.isFinite(Number(nativeFrame)) ? Number(nativeFrame) : 1;
    if (nextFrame !== this.frame) this.setInspectionPoints([]);
    this.frame = nextFrame;
    if (this.transform.dragging) return;
    if (this.project?.source) {
      // Restore mixer bindings before resetting baselines. Otherwise Three's cached
      // unchanged values can skip writes after an override or during a held pose.
      this.mixer?.stopAllAction();
      for (const [id, baseline] of this.nativeBases) {
        const object = this.objects.get(id);
        object.position.copy(baseline.position);
        object.quaternion.copy(baseline.quaternion);
        object.scale.copy(baseline.scale);
      }
      if (this.mixer && this.manifest) {
        // Restart the same actions; this also supports backwards scrubbing after end.
        for (const action of this.actions) action.reset().play();
        this.mixer.setTime(nativeFrameSeconds(this.frame, this.manifest.frame_start ?? 1,
          this.manifest.frame_end ?? this.frame, this.manifest.fps ?? this.project.render.fps));
      }
      this.applyNativeOverrides();
    } else {
      for (const track of this.project?.scene?.animation ?? []) {
        const object = this.objects.get(track.target);
        const value = sampleTrack(track, this.frame);
        if (!object || !value) continue;
        if (track.property === 'location') object.position.copy(vector(value, this.factor));
        else if (track.property === 'scale') object.scale.fromArray(value);
        else if (track.property === 'rotation_deg') {
          object.quaternion.fromArray(blenderQuaternion(value));
          object.userData.rotationReference = value;
        }
      }
    }
    this.content.updateMatrixWorld(true);
  }

  getTransform(id) {
    const object = this.objects.get(id);
    if (!object) return null;
    const clean = values => values.map(value => Math.abs(value) < 1e-10 ? 0 : Math.round(value * 1e6) / 1e6);
    return {location: clean(object.position.toArray().map(value => value / this.factor)),
      rotation_deg: clean(blenderEuler(object.quaternion.toArray(), object.userData.rotationReference)), scale: clean(object.scale.toArray())};
  }

  select(id) {
    this.selectedId = this.objects.has(id) ? id : null;
    const object = this.objects.get(this.selectedId);
    this.transform.detach();
    const poseOnly = object && (object.isCamera || object.isLight || this.cameras.has(this.selectedId)
      || ['CAMERA', 'LIGHT'].includes(object.userData.spec?.type));
    // Cameras edit location/target together in their inspector; lights are inspected
    // there too. Their pose contracts do not accept object rotation/scale channels.
    if (this.interaction.editable && object && !poseOnly && object.userData.spec?.editable_transform !== false && !this.cameraId) this.transform.attach(object);
    this.selection.visible = !!object && (!this.cameraId || !this.interaction.editable)
      && !this.inspectionMode && !this.inspectionPoints.length;
  }

  setInteraction({editable = true, helpers = true} = {}) {
    this.interaction = {editable: !!editable, helpers: !!helpers};
    this.transform.enabled = !!editable;
    this.helpers.visible = !!helpers && !this.cameraId;
    this.select(this.selectedId);
  }

  setMode(mode) {
    if (['translate', 'rotate', 'scale'].includes(mode)) this.transform.setMode(mode);
  }

  /** Inspection is viewing state. A missing contract preserves legacy selection. */
  configureInspection(spec = null) {
    this.inspection = spec ? {tools: new Set(spec.tools ?? []), objectIds: new Set(spec.object_ids ?? [])} : null;
    if (!this.inspection?.tools.has(this.inspectionMode)) this.inspectionMode = null;
    if (!this.inspection?.tools.has('isolate')) this.isolationIds = null;
    if (!this.inspection?.tools.has('xray')) this.xrayEnabled = false;
    this.setInspectionPoints(this.inspectionPoints.filter(point => this.inspection?.objectIds.has(point.object_id)));
    this.applyInspectionEffects();
  }

  setInspectionMode(mode) {
    this.inspectionMode = this.inspection?.tools.has(mode) && ['point', 'measure'].includes(mode) ? mode : null;
    this.inspectionHoverPointer = null;
    this.clearInspectionHover();
    this.renderer.domElement.style.cursor = this.inspectionMode ? 'crosshair' : '';
    if (!this.inspectionMode) this.surfaceCursor.hidden = true;
  }

  setInspectionSnap(enabled) {
    this.inspectionSnapEnabled = !!enabled;
    this.clearInspectionHover();
    this.lastInspectionHoverAt = -Infinity;
  }

  clearInspectionHover() {
    this.inspectionHoverCandidate = null;
    this.inspectionHoverKey = null;
    this.inspectionSnapPreview?.setAttribute('visibility', 'hidden');
    if (this.surfaceCursor?.dataset) delete this.surfaceCursor.dataset.snap;
    this.onInspectionHover?.(null);
  }

  showInspectionHover(result) {
    const candidate = result?.candidate;
    this.inspectionHoverCandidate = candidate ?? null;
    const info = candidate ? {kind: candidate.kind} : result?.hover ?? (result?.surface ? {kind: 'surface'} : null);
    const key = info ? `${info.kind}:${info.reason ?? ''}:${candidate?.key ?? ''}` : null;
    if (key !== this.inspectionHoverKey) {
      this.inspectionHoverKey = key;
      this.onInspectionHover?.(info);
    }
    if (this.surfaceCursor?.dataset) this.surfaceCursor.dataset.snap = info?.kind ?? 'none';
  }

  inspectionSample(event) {
    const bounds = this.renderer.domElement.getBoundingClientRect(), r = this.rect;
    const screen = {x: event.clientX - bounds.left - r.x, y: event.clientY - bounds.top - r.y};
    if (screen.x < 0 || screen.y < 0 || screen.x > r.width || screen.y > r.height) return {reason: 'outside-view'};
    const camera = this.activeCamera;
    this.content.updateMatrixWorld(true); camera.updateMatrixWorld(true);
    this.content.traverse(mesh => {
      if (!mesh.isMesh) return;
      // Raycaster's acceleration bounds can otherwise outlive edited vertices
      // or an animated skeleton, even though its final triangle test is current.
      const position = mesh.geometry.getAttribute('position');
      const morph = mesh.geometry.morphAttributes.position ?? [];
      const signature = morph.map(attribute => `${attribute.id ?? ''}:${attribute.version}:${attribute.count}`).join('|');
      const cached = featureBoundsCache.get(mesh.geometry);
      if (!cached || cached.position !== position || cached.version !== position?.version || cached.morph !== signature
        || morph.some((attribute, index) => cached.morphAttributes?.[index] !== attribute)) {
        mesh.geometry.computeBoundingBox(); mesh.geometry.computeBoundingSphere();
        featureBoundsCache.set(mesh.geometry, {position, version: position?.version, morph: signature, morphAttributes: [...morph]});
      }
      if (mesh.isSkinnedMesh || mesh.isInstancedMesh) {
        mesh.computeBoundingSphere();
        if (mesh.boundingBox) mesh.computeBoundingBox();
      }
    });
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(new THREE.Vector2(screen.x / r.width * 2 - 1, 1 - screen.y / r.height * 2), camera);
    const hit = raycaster.intersectObject(this.content, true).find(isVisibleHit);
    const owner = hit ? this.sourceOwner(hit.object) : null;
    const eligible = owner && (!this.inspection || this.inspection.objectIds.has(owner.userData.editorId));
    const surface = eligible && hit.object.isMesh ? {object_id: owner.userData.editorId,
      local: owner.worldToLocal(hit.point.clone()).toArray(), world: hit.point.toArray()} : null;
    const result = {surface, reason: surface ? null : owner && !eligible ? 'out-of-scope' : 'no-surface'};
    if (this.inspectionSnapEnabled === false) return result;
    const unsupported = mesh => mesh.isSkinnedMesh || mesh.morphTargetInfluences?.some(value => Math.abs(value) > 1e-8)
      ? 'deformed' : mesh.isInstancedMesh ? 'instanced' : null;
    if (surface && unsupported(hit.object)) return {...result, hover: {kind: 'unavailable', reason: unsupported(hit.object)}};
    const candidates = [];
    let unavailable = null;
    const cameraPosition = camera.getWorldPosition(new THREE.Vector3());
    const orthoTowardCamera = camera.getWorldDirection(new THREE.Vector3()).negate();
    const rawDepth = hit ? projectFeature(hit.point, camera, r)?.depth : null;
    this.content.traverse(mesh => {
      if (!mesh.isMesh) return;
      for (let node = mesh; node; node = node.parent) if (!node.visible) return;
      const source = this.sourceOwner(mesh);
      if (!source || this.inspection && !this.inspection.objectIds.has(source.userData.editorId)) return;
      if (materialsOf(mesh).every(material => material.visible === false)) return;
      const position = mesh.geometry.getAttribute('position'), cachedBounds = featureBoundsCache.get(mesh.geometry);
      if (!mesh.geometry.boundingBox || cachedBounds?.position !== position || cachedBounds?.version !== position?.version) {
        mesh.geometry.computeBoundingBox(); mesh.geometry.computeBoundingSphere();
        featureBoundsCache.set(mesh.geometry, {position, version: position?.version});
      }
      const box = mesh.geometry.boundingBox;
      if (!box || box.isEmpty()) return;
      const projectedBounds = [];
      for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
        const point = projectFeature(new THREE.Vector3(x, y, z).applyMatrix4(mesh.matrixWorld), camera, r);
        if (point) projectedBounds.push(point);
      }
      if (projectedBounds.length === 8 && (screen.x < Math.min(...projectedBounds.map(point => point.x)) - SNAP_EDGE_PX
        || screen.x > Math.max(...projectedBounds.map(point => point.x)) + SNAP_EDGE_PX
        || screen.y < Math.min(...projectedBounds.map(point => point.y)) - SNAP_EDGE_PX
        || screen.y > Math.max(...projectedBounds.map(point => point.y)) + SNAP_EDGE_PX)) return;
      const reason = unsupported(mesh);
      if (reason) {unavailable ??= reason; return;}
      const topology = featureTopology(mesh.geometry);
      if (!topology || topology.unavailable) {unavailable ??= topology?.unavailable; return;}
      const normalMatrix = new THREE.Matrix3().getNormalMatrix(mesh.matrixWorld);
      const faceData = topology.faces.map(face => {
        const material = Array.isArray(mesh.material) ? mesh.material[face.materialIndex] : mesh.material;
        if (!material || material.visible === false) return null;
        const normal = face.normal.clone().applyMatrix3(normalMatrix).normalize();
        const center = face.center.clone().applyMatrix4(mesh.matrixWorld);
        const toward = camera.isOrthographicCamera ? orthoTowardCamera : cameraPosition.clone().sub(center).normalize();
        return {normal, facing: normal.dot(toward)};
      });
      const worldVertices = new Map(), screenVertices = new Map(), addedVertices = new Set();
      const vertex = index => {
        if (!worldVertices.has(index)) worldVertices.set(index, topology.vertices[index].clone().applyMatrix4(mesh.matrixWorld));
        if (!screenVertices.has(index)) screenVertices.set(index, projectFeature(worldVertices.get(index), camera, r));
        return {world: worldVertices.get(index), screen: screenVertices.get(index)};
      };
      const addCandidate = (world, projected, distance, kind, key, edgeWorld = null) => {
        // A background floor does not suppress silhouette snapping. A closer
        // foreground object under the pointer does; candidate-ray checks below
        // independently prohibit hidden/back-side candidates on the same mesh.
        if (hit && owner !== source && rawDepth != null && rawDepth < projected.depth - Math.max(projected.depth * 1e-6, 1e-8)) return;
        candidates.push({kind, key: `${mesh.uuid}:${key}`, mesh, source, world, projected, distance, edgeWorld,
          surface: {object_id: source.userData.editorId, local: source.worldToLocal(world.clone()).toArray(), world: world.toArray()}});
      };
      for (const [edgeIndex, edge] of topology.edges.entries()) {
        const faces = edge.faces.map(index => faceData[index]).filter(Boolean);
        if (!faces.length) continue;
        let feature = faces.length !== 2;
        if (faces.length === 2) {
          const cosine = faces[0].normal.dot(faces[1].normal);
          const silhouette = cosine < 1 - 1e-6 && faces[0].facing * faces[1].facing <= 0
            && Math.max(Math.abs(faces[0].facing), Math.abs(faces[1].facing)) > 1e-8;
          feature = cosine <= Math.cos(Math.PI / 6) || silhouette;
        }
        if (!feature) continue;
        const a = vertex(edge.a), b = vertex(edge.b);
        // Conservatively exclude near-plane crossings rather than manufacture a
        // point from an edge behind the camera.
        if (!a.screen || !b.screen) continue;
        for (const [index, point] of [[edge.a, a], [edge.b, b]]) {
          if (addedVertices.has(index)) continue;
          addedVertices.add(index);
          const distance = Math.hypot(point.screen.x - screen.x, point.screen.y - screen.y);
          if (distance <= SNAP_VERTEX_PX) addCandidate(point.world, point.screen, distance, 'vertex', `v${index}`);
        }
        const dx = b.screen.x - a.screen.x, dy = b.screen.y - a.screen.y;
        const lengthSquared = dx * dx + dy * dy;
        if (lengthSquared < 1e-8) continue;
        const s = Math.max(0, Math.min(1, ((screen.x - a.screen.x) * dx + (screen.y - a.screen.y) * dy) / lengthSquared));
        const distance = Math.hypot(a.screen.x + dx * s - screen.x, a.screen.y + dy * s - screen.y);
        if (distance > SNAP_EDGE_PX) continue;
        // A projected linear fraction is not a world-space fraction in perspective.
        const fraction = s * a.screen.w / ((1 - s) * b.screen.w + s * a.screen.w);
        const world = a.world.clone().lerp(b.world, fraction), projected = projectFeature(world, camera, r);
        if (projected) addCandidate(world, projected, distance, 'edge', `e${edgeIndex}`, [a.world, b.world]);
      }
    });
    candidates.sort((a, b) => (a.kind === 'vertex' ? 0 : 1) - (b.kind === 'vertex' ? 0 : 1) || a.distance - b.distance);
    for (const candidate of candidates) if (this.inspectionCandidateVisible(candidate, camera)) return {surface: candidate.surface, candidate};
    return unavailable ? {...result, hover: {kind: 'unavailable', reason: unavailable}} : result;
  }

  inspectionCandidateVisible(candidate, camera) {
    const r = this.rect, point = candidate.projected;
    if (point.x < 0 || point.x > r.width || point.y < 0 || point.y > r.height) return false;
    const raycaster = new THREE.Raycaster();
    const cast = (dx = 0, dy = 0) => {
      raycaster.setFromCamera(new THREE.Vector2((point.x + dx) / r.width * 2 - 1, 1 - (point.y + dy) / r.height * 2), camera);
      return raycaster.intersectObject(this.content, true).find(isVisibleHit);
    };
    const hit = cast();
    const size = new THREE.Box3().setFromObject(candidate.mesh).getSize(new THREE.Vector3()).length();
    const tolerance = Math.max(size * 1e-6, point.depth * 1e-7, 1e-9);
    if (hit) return this.sourceOwner(hit.object) === candidate.source && hit.point.distanceTo(candidate.world) <= tolerance;
    // Exact silhouette rays can miss because the projected edge falls between
    // floating-point triangles. A subpixel probe may confirm the same surface,
    // but never overrides a nearer hit on the exact candidate ray.
    const unitsPerPixel = camera.isOrthographicCamera ? (camera.top - camera.bottom) / camera.zoom / r.height
      : 2 * point.depth * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) / r.height;
    for (const [dx, dy] of [[.15, 0], [-.15, 0], [0, .15], [0, -.15]]) {
      const probe = cast(dx, dy);
      if (probe && this.sourceOwner(probe.object) === candidate.source && probe.point.distanceTo(candidate.world) <= Math.max(tolerance, unitsPerPixel * .4)) return true;
    }
    return false;
  }

  sourceOwner(object) {
    for (let node = object; node; node = node.parent) if (node.userData.editorId) return node;
    return null;
  }

  setInspectionPoints(points = []) {
    this.inspectionHoverPointer = null;
    this.clearInspectionHover();
    this.inspectionPoints = points.slice(0, 2).map(point => ({object_id: point.object_id, local: [...point.local], world: [...point.world]}));
    disposeTree(this.inspectionMarkers);
    this.inspectionMarkers.clear();
    const material = new THREE.MeshBasicMaterial({color: this.viewTheme?.selection ?? VIEWPORT_THEMES.dark.selection, depthTest: false, depthWrite: false});
    for (const point of this.inspectionPoints) {
      const marker = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12), material);
      marker.position.fromArray(point.world); marker.renderOrder = 50;
      this.inspectionMarkers.add(marker);
    }
    if (!this.inspectionPoints.length) material.dispose();
    if (this.inspectionPoints.length === 2) {
      const vertices = this.inspectionPoints.map(point => new THREE.Vector3(...point.world));
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(vertices), new THREE.LineBasicMaterial({color: this.viewTheme?.selection ?? VIEWPORT_THEMES.dark.selection, depthTest: false, depthWrite: false}));
      line.renderOrder = 49; this.inspectionMarkers.add(line);
      this.refreshMeasurementLabel();
    }
    this.measurementLabel.hidden = this.inspectionPoints.length !== 2;
    if (this.inspectionOverlay && !this.inspectionPoints.length) {
      this.inspectionOverlay.setAttribute('hidden', '');
      for (const {label} of this.inspectionPointOverlays) label.hidden = true;
    }
  }

  setIsolation(ids = null) {
    this.isolationIds = this.inspection?.tools.has('isolate') && ids?.length ? new Set(ids.filter(id => this.inspection.objectIds.has(id))) : null;
    if (!this.isolationIds?.size) this.isolationIds = null;
    this.applyInspectionEffects();
  }

  setXray(enabled) {
    this.xrayEnabled = !!enabled && !!this.inspection?.tools.has('xray');
    this.applyInspectionEffects();
  }

  restoreInspectionEffects() {
    for (const [object, visible] of this.visibilityBaseline) object.visible = visible;
    this.visibilityBaseline.clear();
    for (const [object, entry] of this.xrayMaterials) {
      object.material = entry.original;
      for (const material of entry.clones) material.dispose();
    }
    this.xrayMaterials.clear();
  }

  applyInspectionEffects() {
    this.restoreInspectionEffects();
    this.content.traverse(object => {
      if (!object.isMesh) return;
      const owner = this.sourceOwner(object);
      if (this.isolationIds) {
        let included = false;
        for (let node = object; node; node = node.parent) if (this.isolationIds.has(node.userData.editorId)) included = true;
        this.visibilityBaseline.set(object, object.visible);
        object.visible = object.visible && included;
      }
      if (this.xrayEnabled && owner && this.inspection.objectIds.has(owner.userData.editorId)) {
        const original = object.material, clones = materialsOf(object).map(material => {
          const copy = material.clone(); copy.transparent = true; copy.opacity = Math.min(material.opacity ?? 1, 0.24);
          copy.depthWrite = false; copy.side = THREE.DoubleSide; copy.needsUpdate = true; return copy;
        });
        this.xrayMaterials.set(object, {original, clones});
        object.material = Array.isArray(original) ? clones : clones[0];
      }
    });
  }

  setCamera(id) {
    this.cameraId = this.cameras.has(id) ? id : null;
    this.updateViewingBackground();
    this.orbit.enabled = !this.cameraId;
    this.transform.camera = this.activeCamera;
    this.helpers.visible = this.interaction.helpers && !this.cameraId;
    this.grid.visible = this.gridEnabled && !this.cameraId;
    this.select(this.selectedId);
    this.resize();
  }

  get activeCamera() {return this.cameras.get(this.cameraId) ?? this.freeCamera;}

  updateCameraProjection(camera, spec = camera.userData.spec) {
    if (!spec) return;
    const resolution = this.project?.render?.resolution ?? [16, 9];
    const aspect = resolution[0] / resolution[1];
    const projection = cameraProjection(spec, aspect, this.factor);
    if (camera.isOrthographicCamera) {
      camera.left = -projection.width / 2; camera.right = projection.width / 2;
      camera.top = projection.height / 2; camera.bottom = -projection.height / 2;
    } else {camera.aspect = aspect; camera.fov = projection.fov;}
    camera.updateProjectionMatrix();
  }

  frameAll() {
    if (!this.project) return;
    this.setCamera(null);
    this.content.updateMatrixWorld(true);
    const boxes = [];
    this.content.traverse(object => {
      if (!object.isMesh || !object.visible) return;
      const box = new THREE.Box3().setFromObject(object);
      const size = box.getSize(new THREE.Vector3());
      // Exclude studio backdrops from fitting, including the bundled 200 m floor.
      const dimensions = [size.x, size.y, size.z].sort((a, b) => a - b);
      if (dimensions[2] > 20 * Math.max(dimensions[0], 0.000001) && dimensions[1] > dimensions[0] * 20) return;
      if (!box.isEmpty()) boxes.push(box);
    });
    const bounds = new THREE.Box3();
    for (const box of boxes) bounds.union(box);
    if (bounds.isEmpty()) bounds.setFromCenterAndSize(new THREE.Vector3(0, 0, this.factor / 2), new THREE.Vector3(this.factor, this.factor, this.factor));
    const sphere = bounds.getBoundingSphere(new THREE.Sphere());
    const radius = Math.max(0.001, sphere.radius);
    const verticalFov = THREE.MathUtils.degToRad(this.freeCamera.fov);
    const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * this.freeCamera.aspect);
    const distance = radius * 1.22 / Math.sin(Math.min(verticalFov, horizontalFov) / 2);
    this.orbit.target.copy(sphere.center);
    this.freeCamera.position.copy(sphere.center).addScaledVector(new THREE.Vector3(1, -1.5, 1).normalize(), distance);
    this.freeCamera.near = Math.max(0.000001, radius / 1000);
    this.freeCamera.far = Math.max(1000, distance * 1000);
    this.orbit.minDistance = radius * 0.03;
    this.orbit.maxDistance = distance * 100;
    this.freeCamera.updateProjectionMatrix();
    this.orbit.update();
    this.grid.scale.setScalar(radius / 3);
    this.markerSize = radius * 0.05;
  }

  setGrid(visible) {this.gridEnabled = !!visible; this.grid.visible = this.gridEnabled && !this.cameraId;}

  getView() {
    if (!this.cameraId) return {location: this.freeCamera.position.toArray().map(value => value / this.factor),
      target: this.orbit.target.toArray().map(value => value / this.factor)};
    const camera = this.activeCamera;
    const position = camera.getWorldPosition(new THREE.Vector3());
    const direction = camera.getWorldDirection(new THREE.Vector3());
    const target = position.clone().addScaledVector(direction, Math.max(1, position.distanceTo(this.orbit.target)));
    return {location: position.toArray().map(value => value / this.factor), target: target.toArray().map(value => value / this.factor)};
  }

  resize() {
    const width = Math.max(1, this.container.clientWidth), height = Math.max(1, this.container.clientHeight);
    this.renderer.setSize(width, height, false);
    this.width = width; this.height = height;
    this.freeCamera.aspect = width / height;
    this.freeCamera.updateProjectionMatrix();
    for (const camera of this.cameras.values()) {
      if (!this.project?.source) this.updateCameraProjection(camera);
    }
    const aspect = (this.project?.render?.resolution?.[0] ?? 16) / (this.project?.render?.resolution?.[1] ?? 9);
    let renderWidth = width, renderHeight = height;
    if (this.cameraId) {
      if (width / height > aspect) renderWidth = height * aspect;
      else renderHeight = width / aspect;
    }
    this.rect = {x: (width - renderWidth) / 2, y: (height - renderHeight) / 2, width: renderWidth, height: renderHeight};
  }

  pick(event) {
    if (this.inspectionMode) {
      const result = this.inspectionSample(event);
      if (!result.surface) {
        this.clearInspectionHover();
        this.onInspectionMiss?.(result.reason ?? 'no-surface');
        return;
      }
      this.showInspectionHover(result);
      this.select(result.surface.object_id);
      // Snap metadata is presentation-only. Persist the original point contract.
      this.onSurfacePick(result.surface);
      return;
    }
    const bounds = this.renderer.domElement.getBoundingClientRect();
    const x = event.clientX - bounds.left - this.rect.x, y = event.clientY - bounds.top - this.rect.y;
    if (x < 0 || y < 0 || x > this.rect.width || y > this.rect.height) {
      if (this.inspectionMode) this.onInspectionMiss?.('outside-view');
      return;
    }
    this.pointer.set(x / this.rect.width * 2 - 1, 1 - y / this.rect.height * 2);
    this.raycaster.setFromCamera(this.pointer, this.activeCamera);
    const candidates = this.helpers.visible ? [this.content, this.helpers] : [this.content];
    const hits = this.raycaster.intersectObjects(candidates, true);
    let id = null, surface = null;
    for (const hit of hits) {
      let node = hit.object;
      let visible = true;
      for (let ancestor = node; ancestor; ancestor = ancestor.parent) if (!ancestor.visible) visible = false;
      if (!visible) continue;
      node = this.sourceOwner(node);
      if (!node && this.inspectionMode) {
        // An unmapped foreground surface still blocks a mapped object behind it.
        this.onInspectionMiss?.('no-surface');
        return;
      }
      if (node) {
        id = node.userData.editorId;
        // A visible out-of-scope surface cannot select or annotate a hidden part behind it.
        if (this.inspection && !this.inspection.objectIds.has(id)) {
          if (this.inspectionMode) this.onInspectionMiss?.('out-of-scope');
          return;
        }
        if (hit.object.isMesh) surface = {object_id: id, local: node.worldToLocal(hit.point.clone()).toArray(), world: hit.point.toArray()};
        break;
      }
    }
    if (this.inspectionMode && !surface) {
      this.onInspectionMiss?.('no-surface');
      return;
    }
    this.select(id);
    if (this.inspectionMode && surface) this.onSurfacePick(surface);
    else this.onSelect(id);
  }

  draw() {
    if (this.disposed) return;
    this.orbit.update();
    this.content.updateMatrixWorld(true);
    const camera = this.activeCamera;
    const now = globalThis.performance?.now() ?? Date.now();
    if (this.inspectionMode && this.inspectionHoverPointer && now - (this.lastInspectionHoverAt ?? -Infinity) > 55) {
      this.lastInspectionHoverAt = now;
      this.showInspectionHover(this.inspectionSample(this.inspectionHoverPointer));
    }
    for (const marker of this.inspectionMarkers.children) if (marker.isMesh) {
      const distance = camera.getWorldPosition(new THREE.Vector3()).distanceTo(marker.position);
      const span = camera.isOrthographicCamera ? (camera.top - camera.bottom) / camera.zoom : 2 * distance * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
      marker.scale.setScalar(span * 4 / Math.max(1, this.rect.height));
    }
    this.updateInspectionOverlay(camera);
    for (const {object, mesh} of this.decorations) {
      object.getWorldPosition(mesh.position);
      mesh.scale.setScalar(this.markerSize ?? 0.12);
    }
    const selected = this.objects.get(this.selectedId);
    if (selected && (!this.cameraId || !this.interaction.editable) && !this.inspectionMode && !this.inspectionPoints.length) {
      this.selection.box.setFromObject(selected);
      if (this.selection.box.isEmpty()) this.selection.box.setFromCenterAndSize(selected.getWorldPosition(new THREE.Vector3()), new THREE.Vector3().setScalar(this.markerSize ?? 0.12));
      this.selection.visible = true;
    } else this.selection.visible = false;
    this.renderer.setScissorTest(false);
    this.renderer.setViewport(0, 0, this.width, this.height);
    this.renderer.setClearColor(this.viewTheme.background);
    this.renderer.clear();
    const r = this.rect;
    this.renderer.setScissor(r.x, r.y, r.width, r.height);
    this.renderer.setViewport(r.x, r.y, r.width, r.height);
    this.renderer.setScissorTest(true);
    this.renderer.render(this.scene, this.activeCamera);
  }

  dispose() {
    this.disposed = true;
    this.generation++;
    this.unsubscribeLocale();
    this.unsubscribeTheme();
    this.renderer.setAnimationLoop(null);
    this.resizeObserver.disconnect();
    this.renderer.domElement.removeEventListener('pointerdown', this.pointerDown);
    this.renderer.domElement.removeEventListener('pointerup', this.pointerUp);
    this.renderer.domElement.removeEventListener('keydown', this.inspectionKey);
    this.renderer.domElement.removeEventListener('pointermove', this.inspectionPointerMove);
    this.renderer.domElement.removeEventListener('pointerleave', this.inspectionPointerLeave);
    this.clearContent();
    this.orbit.dispose();
    this.transform.dispose();
    this.grid.geometry.dispose();
    this.grid.material.dispose();
    this.selection.geometry.dispose();
    this.selection.material.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.message.remove();
    this.measurementLabel.remove();
    this.inspectionOverlay.remove();
    for (const {label} of this.inspectionPointOverlays) label.remove();
    this.surfaceCursor.remove();
  }
}
