// node --experimental-vm-modules theme-viewport-checks.mjs
// Uses the actual bundled Three modules and shared i18n. No browser or rendering.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';

const work = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(work, '../../skills/blender2easy/editor/web');
const context = vm.createContext({console, Intl, URL, URLSearchParams, setTimeout, clearTimeout,
  navigator: {languages: ['en']}, document: {documentElement: {dataset: {}, style: {}},
    querySelectorAll: () => [], getElementById: () => null}});
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
const {Viewport} = module.namespace;
const THREE = (await load(path.join(root, 'vendor/three/build/three.module.js'))).namespace;
const i18n = (await load(path.join(root, 'i18n.js'))).namespace;
const checks = [];
const view = Object.create(Viewport.prototype);
const attributes = new Map();
Object.assign(view, {scene: new THREE.Scene(), grid: new THREE.GridHelper(20, 40),
  selection: new THREE.Box3Helper(new THREE.Box3()), inspectionMarkers: new THREE.Group(), decorations: [],
  cameraId: null, authoredBackground: new THREE.Color(0xaabbcc), inspectionPoints: [], measurementLabel: {}, message: {},
  renderer: {domElement: {getAttribute: key => attributes.get(key), setAttribute: (key, value) => attributes.set(key, value)}}});
const project = {units: 'cm', scene: {background: [.7, .8, .9], materials: [{id: 'unaltered', color: [.5, .6, .7, 1]}], lights: [{energy: 600}]}};
view.project = project;
const projectBefore = JSON.stringify(project);
const material = new THREE.MeshStandardMaterial({color: 0x236cb2, roughness: .3});
const mesh = new THREE.Mesh(new THREE.BoxGeometry(), material);
const light = new THREE.DirectionalLight(0xffddaa, 2.3);
view.scene.add(mesh, light);
const materialBefore = JSON.stringify(material.toJSON());
const lightBefore = JSON.stringify(light.toJSON());
i18n.setTheme('dark'); view.applyUiTheme();
assert.equal(view.scene.background.getHex(), 0x1b1d20);
view.cameraId = 'hero'; view.updateViewingBackground();
assert.equal(view.scene.background.getHex(), 0xaabbcc);
i18n.setTheme('light'); view.applyUiTheme();
assert.equal(view.scene.background.getHex(), 0xaabbcc);
view.cameraId = null; view.updateViewingBackground();
assert.equal(view.scene.background.getHex(), 0xf1f1ef);
checks.push('Neutral free-view backgrounds; authored camera background preserved through theme changes');
view.setInspectionPoints([{object_id: 'lid', local: [0, 0, 0], world: [0, 0, 0]},
  {object_id: 'lid', local: [.025, 0, 0], world: [.025, 0, 0]}]);
assert.equal(view.measurementLabel.textContent, '2.5 cm');
assert.equal(view.inspectionMarkers.children[0].material.color.getHex(), 0x4f6b84);
i18n.setTheme('dark'); view.applyUiTheme();
assert.equal(view.inspectionMarkers.children[0].material.color.getHex(), 0x9cb6cc);
checks.push('Existing measurement markers recolor without replacing sampled points or model materials');
view.setMessage('viewport.loading');
for (const locale of ['en', 'zh-Hans', 'zh-Hant']) {
  i18n.setLanguage(locale); view.refreshLocale();
  assert.equal(view.measurementLabel.textContent, '2.5 cm');
  assert.equal(view.message.textContent, i18n.t('viewport.loading'));
  assert.equal(attributes.get('aria-label'), i18n.t('viewport.canvas'));
}
attributes.set('aria-label', 'Specialized review keyboard instructions');
i18n.setLanguage('en'); view.refreshLocale();
assert.equal(attributes.get('aria-label'), 'Specialized review keyboard instructions');
view.project = {source: {path: 'local.blend'}};
for (const locale of ['en', 'zh-Hans', 'zh-Hant']) {
  i18n.setLanguage(locale); view.refreshLocale();
  assert.equal(view.measurementLabel.textContent, `0.025 ${i18n.t('viewport.previewUnits')}`);
}
assert.equal(JSON.stringify(project), projectBefore);
assert.equal(JSON.stringify(material.toJSON()), materialBefore);
assert.equal(JSON.stringify(light.toJSON()), lightBefore);
checks.push('Three languages, declared centimeter conversion, uncalibrated preview units and specialized aria-label ownership');
checks.push('Project, authored material and light JSON unchanged');

const css = await readFile(path.join(root, 'theme.css'), 'utf8');
assert.equal(css.split('{').length, css.split('}').length);
assert.ok(!css.includes('.topbar') && !css.includes('.app-header') && !css.includes('.header-actions'), 'Pages own header layout');
assert.match(css, /inline-size: 248px/);
assert.match(css, /\.preferences-toggle > span\s*\{[^}]*clip-path: inset\(50%\)/s);
const contrast = {};
function luminance(hex) {
  const channels = [1, 3, 5].map(index => parseInt(hex.slice(index, index + 2), 16) / 255)
    .map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
  return channels.reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
}
for (const theme of ['dark', 'light']) {
  const block = css.match(new RegExp(`html\\[data-theme="${theme}"\\] \\{([\\s\\S]*?)\\n\\}`))[1];
  const tokens = Object.fromEntries([...block.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map(match => [match[1], match[2]]));
  function token(name, ancestors = []) {
    assert.ok(!ancestors.includes(name), `No cyclic token: ${[...ancestors, name].join(' -> ')}`);
    const value = tokens[name]; assert.ok(value, `Defined ${name}`);
    const alias = value.match(/^var\((--[\w-]+)\)$/);
    return alias ? token(alias[1], [...ancestors, name]) : value;
  }
  for (const name of Object.keys(tokens)) token(name);
  for (const name of ['--canvas', '--surface', '--surface-raised']) {
    const channels = token(name).slice(1).match(/../g).map(value => parseInt(value, 16));
    // v0.10 uses cool graphite surfaces instead of v0.9's near-achromatic grays.
    assert.ok(Math.max(...channels) - Math.min(...channels) <= 12, `${theme} ${name} stays restrained`);
  }
  contrast[theme] = {};
  for (const [foreground, background] of [['ink', 'surface'], ['muted', 'surface-raised'], ['on-primary', 'primary'], ['danger', 'danger-surface'], ['warning', 'warning-surface']]) {
    const levels = [luminance(token('--' + foreground)), luminance(token('--' + background))].sort((a, b) => a - b);
    const ratio = (levels[1] + .05) / (levels[0] + .05);
    assert.ok(ratio >= 4.5, `${theme} ${foreground}/${background} contrast ${ratio}`);
    contrast[theme][`${foreground}/${background}`] = Number(ratio.toFixed(2));
  }
}
checks.push('Restrained graphite shell tokens, acyclic aliases, 248px icon-only preferences, no shared header overrides, text contrast ≥4.5');
console.log(JSON.stringify({status: 'PASS', checks, contrast}, null, 2));
