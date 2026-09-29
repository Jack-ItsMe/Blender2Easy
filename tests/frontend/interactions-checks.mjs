// node --experimental-vm-modules interactions-checks.mjs
// Deterministic DOM/event boundary test of the real dependency-free module.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '../../skills/blender2easy/editor/web');
class Events {
  listeners = new Map();
  addEventListener(type, fn, options) {if (!this.listeners.has(type)) this.listeners.set(type, new Map()); this.listeners.get(type).set(fn, options);}
  removeEventListener(type, fn) {this.listeners.get(type)?.delete(fn);}
  fire(type, event = {}) {for (const [fn, options] of [...(this.listeners.get(type) ?? [])]) {fn(event); if (options?.once) this.removeEventListener(type, fn);}}
}
class Element extends Events {
  constructor(tag, doc) {super(); this.tagName = tag.toLowerCase(); this.ownerDocument = doc; this.nodeType = 1; this.attributes = new Map(); this.dataset = {}; this.children = []; this.parentNode = null; this.ownText = ''; this.styleWrites = 0; const values = new Map(); this.style = {setProperty: (key, value) => {values.set(key, value); this.styleWrites++;}, getPropertyValue: key => values.get(key) ?? ''}; this.rect = {left: 100, top: 100, width: 40, height: 32, right: 140, bottom: 132};}
  get isConnected() {for (let node = this; node; node = node.parentNode) if (node === this.ownerDocument) return true; return false;}
  hasAttribute(key) {return this.attributes.has(key);}
  getAttribute(key) {return this.attributes.get(key) ?? null;}
  setAttribute(key, value) {this.attributes.set(key, String(value)); this.ownerDocument.record({type: 'attributes', target: this, attributeName: key});}
  removeAttribute(key) {if (this.attributes.delete(key)) this.ownerDocument.record({type: 'attributes', target: this, attributeName: key});}
  get hidden() {return this.hasAttribute('hidden');} set hidden(value) {if (value) this.setAttribute('hidden', ''); else this.removeAttribute('hidden');}
  get title() {return this.getAttribute('title') ?? '';} set title(value) {this.setAttribute('title', value);}
  get min() {return this.getAttribute('min') ?? '';} set min(value) {this.setAttribute('min', value);}
  get max() {return this.getAttribute('max') ?? '';} set max(value) {this.setAttribute('max', value);}
  get value() {return this.currentValue ?? this.getAttribute('value') ?? '50';} set value(value) {this.currentValue = String(value);}
  get textContent() {return this.ownText + this.children.map(node => node.textContent).join('');}
  // Model the observed browser boundary: CSS-hidden child text remains in
  // textContent but is absent from a rendered parent's innerText.
  get innerText() {return this.ownText + this.children.filter(node => node.style.display !== 'none' && !node.hidden).map(node => node.innerText).join('');}
  set textContent(value) {this.ownText = String(value); const removedNodes = this.children.splice(0); for (const node of removedNodes) node.parentNode = null; this.ownerDocument.record({type: 'childList', target: this, addedNodes: [], removedNodes});}
  set innerHTML(value) {throw new Error('Interactions must not parse or replace authored HTML');}
  matches(selector) {return selector.split(',').some(part => {part = part.trim(); const match = part.match(/^(button|summary|input|dialog)?(?:\[([\w-]+)(?:="([^"]*)")?\])?$/); return !!match && (!match[1] || this.tagName === match[1]) && (!match[2] || this.hasAttribute(match[2]) && (match[3] === undefined || this.getAttribute(match[2]) === match[3]));});}
  querySelectorAll(selector) {const found = []; for (const child of this.children) {if (child.matches(selector)) found.push(child); found.push(...child.querySelectorAll(selector));} return found;}
  closest(selector) {for (let node = this; node?.nodeType === 1; node = node.parentNode) if (node.matches(selector)) return node; return null;}
  contains(node) {for (; node; node = node.parentNode) if (node === this) return true; return false;}
  appendChild(node) {node.remove(); node.parentNode = this; this.children.push(node); this.ownerDocument.record({type: 'childList', target: this, addedNodes: [node], removedNodes: []}); return node;}
  remove() {if (!this.parentNode?.children) return; const parent = this.parentNode; parent.children.splice(parent.children.indexOf(this), 1); this.parentNode = null; this.ownerDocument.record({type: 'childList', target: parent, addedNodes: [], removedNodes: [this]});}
  getClientRects() {return this.closest('[hidden]') ? [] : [this.getBoundingClientRect()];}
  getBoundingClientRect() {if (this.className !== 'workspace-tooltip') return this.rect; const width = Math.min(parseFloat(this.style.maxWidth) || 280, Math.max(60, this.textContent.length * 7 + 22)); const height = Math.ceil((this.textContent.length * 7 + 22) / width) * 18 + 16; return {left: Number.parseFloat(this.style.left) || 0, top: Number.parseFloat(this.style.top) || 0, width, height};}
}
class Document extends Events {
  constructor(win) {super(); this.defaultView = win; this.readyState = 'loading'; this.observers = []; this.documentElement = new Element('html', this); this.documentElement.parentNode = this; this.body = new Element('body', this); this.documentElement.appendChild(this.body);}
  createElement(tag) {return new Element(tag, this);}
  querySelectorAll(selector) {return this.documentElement.querySelectorAll(selector);}
  getElementById(id) {const scan = node => node.id === id ? node : node.children.map(scan).find(Boolean); return scan(this.documentElement);}
  record(record) {for (const observer of this.observers) if (observer.root?.contains(record.target) && (record.type === 'childList' || observer.options.attributeFilter.includes(record.attributeName))) observer.pending.push(record);}
  flush() {for (let count = 0; this.observers.some(observer => observer.pending.length); count++) {assert.ok(count < 12, 'No observer feedback loop'); for (const observer of this.observers) if (observer.pending.length) observer.callback(observer.pending.splice(0));}}
}
const win = new Events(); win.innerWidth = 390; win.innerHeight = 740;
let now = 0, sequence = 0; const timers = new Map();
win.setTimeout = function(callback, delay) {assert.equal(this, win); const id = ++sequence; timers.set(id, {callback, due: now + delay}); return id;};
win.clearTimeout = function(id) {assert.equal(this, win); timers.delete(id);};
function advance(milliseconds) {now += milliseconds; for (const [id, timer] of [...timers]) if (timer.due <= now) {timers.delete(id); timer.callback();}}
const doc = new Document(win);
win.MutationObserver = class {
  constructor(callback) {this.callback = callback; this.pending = []; doc.observers.push(this);}
  observe(root, options) {this.root = root; this.options = options;}
  disconnect() {this.root = null; this.pending = [];}
};
const make = (tag, attributes = {}, text = '') => {const node = doc.createElement(tag); for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value); node.textContent = text; doc.body.appendChild(node); return node;};
const button = make('button', {title: 'Inspect <script> stays text', 'aria-label': 'Inspect', 'aria-describedby': 'prior-help'}, 'Authored label');
const icon = make('button', {title: 'Original icon hint'});
const summary = make('summary', {title: 'Preferences'}, 'Preferences');
const compactButton = make('button', {title: '新建项目'});
const compactText = make('span', {}, '新建'); compactText.style.display = 'none'; compactButton.appendChild(compactText);
const responsiveButton = make('button', {title: '打开项目'});
const responsiveText = make('span', {}, '打开'); responsiveButton.appendChild(responsiveText);
const labelledButton = make('button', {title: 'Tooltip', 'aria-labelledby': 'page-label'});
const explicitEmptyButton = make('button', {title: 'Tooltip', 'aria-label': ''});
const range = make('input', {type: 'range', min: '0', max: '1'}); range.value = '.25';
const source = await readFile(path.join(root, 'interactions.js'), 'utf8');
const context = vm.createContext({document: doc, console, setTimeout, clearTimeout});
const module = new vm.SourceTextModule(source, {context}); await module.link(() => {throw new Error('No dependency imports expected');}); await module.evaluate();
assert.equal(doc.body.children.filter(node => node.className === 'workspace-tooltip').length, 0, 'Waits for DOMContentLoaded');
doc.fire('DOMContentLoaded'); doc.flush();
const api = context.ObjectAnimationInteractions, controller = api.initWorkspaceInteractions(doc);
assert.ok(Object.isFrozen(api)); assert.equal(Object.getOwnPropertyDescriptor(context, 'ObjectAnimationInteractions').writable, false);
assert.equal(controller, api.initWorkspaceInteractions(doc), 'Idempotent initialization');
const tooltip = doc.body.children.find(node => node.className === 'workspace-tooltip');
assert.equal(doc.body.children.filter(node => node.className === 'workspace-tooltip').length, 1);
assert.equal(button.title, ''); assert.equal(icon.getAttribute('aria-label'), 'Original icon hint');
assert.equal(button.textContent, 'Authored label'); assert.equal(button.getAttribute('aria-label'), 'Inspect');
assert.equal(range.style.getPropertyValue('--range-progress'), '25%');
const checks = ['Independent DOM-ready entry, immutable optional API, idempotent initialization and preserved authored/accessibility text'];

assert.equal(compactButton.textContent, '新建'); assert.equal(compactButton.innerText, '');
assert.equal(compactButton.getAttribute('aria-label'), '新建项目', 'CSS-hidden text receives a title-derived accessible name');
assert.equal(responsiveButton.hasAttribute('aria-label'), false, 'Visible label needs no fallback');
responsiveText.style.display = 'none'; win.fire('resize');
assert.equal(responsiveButton.getAttribute('aria-label'), '打开项目', 'Resize captures a newly hidden label');
responsiveButton.title = 'Open project'; doc.flush();
assert.equal(responsiveButton.getAttribute('aria-label'), 'Open project', 'Managed name follows locale title updates');
responsiveText.style.display = ''; win.fire('resize');
assert.equal(responsiveButton.getAttribute('aria-label'), 'Open project', 'Returning text can retain the title-derived name');
assert.equal(labelledButton.hasAttribute('aria-label'), false, 'Explicit aria-labelledby wins');
assert.equal(explicitEmptyButton.getAttribute('aria-label'), '', 'Even an explicit empty aria-label remains page-owned');
compactButton.setAttribute('aria-labelledby', 'page-label'); win.fire('resize');
assert.equal(compactButton.hasAttribute('aria-label'), false, 'A new page-owned labelledby releases our prior fallback');
assert.equal(compactButton.getAttribute('aria-labelledby'), 'page-label');
checks.push('CSS-hidden textContent/innerText boundary, responsive resize fallback, locale updates and explicit ARIA ownership');

doc.fire('pointerover', {target: button, relatedTarget: null, pointerType: 'mouse'});
advance(299); assert.equal(tooltip.hidden, true); advance(1);
assert.equal(tooltip.hidden, false); assert.equal(tooltip.textContent, 'Inspect <script> stays text');
assert.equal(tooltip.children.length, 0, 'Tooltip text never becomes markup');
assert.equal(button.getAttribute('aria-describedby'), `prior-help ${tooltip.id}`);
doc.fire('pointerout', {target: button, relatedTarget: null});
assert.equal(tooltip.hidden, true); assert.equal(button.getAttribute('aria-describedby'), 'prior-help');
doc.fire('focusin', {target: button}); advance(300);
button.title = '繁體：檢視模型'; doc.flush();
assert.equal(tooltip.textContent, '繁體：檢視模型'); assert.equal(button.title, '');
doc.fire('keydown', {key: 'Escape'}); assert.equal(tooltip.hidden, true);
doc.fire('focusin', {target: summary}); doc.fire('click', {target: summary}); advance(300); assert.equal(tooltip.hidden, true);
doc.fire('pointerover', {target: summary, relatedTarget: null, pointerType: 'touch'}); advance(300); assert.equal(tooltip.hidden, true);
checks.push('300ms hover/focus delay, localized live title updates, native-title suppression, preserved aria-describedby, Escape/click/leave dismissal and no touch hover');

button.rect = {left: 365, right: 389, top: 715, bottom: 739, width: 24, height: 24};
button.title = 'A longer localized hint near the bottom-right viewport boundary'; doc.flush();
doc.fire('focusin', {target: button}); advance(300);
let bounds = tooltip.getBoundingClientRect();
assert.ok(parseFloat(tooltip.style.left) >= 10 && parseFloat(tooltip.style.left) + bounds.width <= 380);
assert.ok(parseFloat(tooltip.style.top) >= 10 && parseFloat(tooltip.style.top) + bounds.height <= 730);
assert.equal(tooltip.dataset.placement, 'top');
doc.fire('scroll'); assert.equal(tooltip.hidden, true);
button.rect = {left: 0, right: 24, top: 0, bottom: 24, width: 24, height: 24};
doc.fire('focusin', {target: button}); advance(300); assert.equal(tooltip.dataset.placement, 'bottom');
win.fire('resize'); assert.equal(tooltip.hidden, true);
const dialog = make('dialog', {open: ''}); const modalButton = make('button', {title: 'Modal hint'}, 'Preview'); dialog.appendChild(modalButton); doc.flush();
doc.fire('focusin', {target: modalButton}); advance(300); assert.equal(tooltip.parentNode, dialog, 'Modal controls use the dialog top layer');
doc.fire('close', {target: dialog}); assert.equal(tooltip.hidden, true);
checks.push('Tooltips clamp at viewport edges, flip above/below, dismiss on scroll/resize, and remain visible inside modal top layers');

range.value = '.7'; doc.fire('input', {target: range}); assert.equal(range.style.getPropertyValue('--range-progress'), '70%');
const writes = range.styleWrites; api.refreshRanges(range); assert.equal(range.styleWrites, writes, 'Identical refresh does not rewrite style');
range.value = '.9'; assert.equal(range.style.getPropertyValue('--range-progress'), '70%', 'Property-only writes require the explicit page hook');
api.refreshRanges(range); assert.equal(range.style.getPropertyValue('--range-progress'), '90%');
range.min = '-1'; range.max = '1'; range.value = '0'; doc.flush(); assert.equal(range.style.getPropertyValue('--range-progress'), '50%');
range.value = '99'; doc.fire('change', {target: range}); assert.equal(range.style.getPropertyValue('--range-progress'), '100%');
range.max = '-1'; doc.flush(); assert.equal(range.style.getPropertyValue('--range-progress'), '0%');
const dynamic = make('input', {type: 'range', min: '0', max: '200'}); dynamic.value = '30'; doc.flush();
assert.equal(dynamic.style.getPropertyValue('--range-progress'), '15%');
dynamic.value = '100'; win.fire('pageshow'); assert.equal(dynamic.style.getPropertyValue('--range-progress'), '50%');
checks.push('Range event, explicit programmatic, mutation/structure and pageshow refresh; clamping, zero spans and no repeated style writes');

icon.title = '簡體提示'; doc.flush(); assert.equal(icon.getAttribute('aria-label'), '簡體提示');
icon.setAttribute('aria-label', 'Page-owned name'); icon.title = 'English hint'; doc.flush(); assert.equal(icon.getAttribute('aria-label'), 'Page-owned name');
doc.fire('focusin', {target: icon}); advance(300); icon.remove(); doc.flush();
assert.equal(tooltip.hidden, true); assert.equal(icon.title, 'English hint');
doc.body.appendChild(icon); doc.flush(); assert.equal(icon.title, '');
doc.fire('focusin', {target: icon}); advance(300); assert.equal(tooltip.textContent, 'English hint');
controller.destroy(); doc.flush();
assert.equal(tooltip.isConnected, false); assert.equal(icon.title, 'English hint'); assert.equal(icon.getAttribute('aria-label'), 'Page-owned name');
assert.equal(button.title, 'A longer localized hint near the bottom-right viewport boundary');
assert.equal(button.getAttribute('aria-describedby'), 'prior-help');
assert.equal(timers.size, 0);
checks.push('Accessible title-only controls retain names; page-owned labels win; detachment/reinsertion and destroy restore titles and remove timers/descriptions');

const limited = vm.createContext({document: {querySelectorAll: () => []}, console});
const testModule = new vm.SourceTextModule(source, {context: limited}); await testModule.link(() => {}); await testModule.evaluate();
assert.equal(testModule.namespace.initWorkspaceInteractions(), null); testModule.namespace.refreshRanges();
checks.push('Existing limited VM documents can load the module and optional range API without browser-only DOM calls');
console.log(JSON.stringify({status: 'PASS', checks}, null, 2));
