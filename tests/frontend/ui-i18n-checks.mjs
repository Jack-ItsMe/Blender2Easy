import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '../../skills/blender2easy/editor/web');
const boot = await readFile(path.join(root, 'preferences-init.js'), 'utf8');
function context({languages = ['en-US'], saved = {}, denyStorage = false, systemDark = false, search = ''} = {}) {
  const listeners = new Map(), storage = new Map(Object.entries(saved));
  const element = {dataset: {}, style: {}};
  const result = vm.createContext({console, URLSearchParams, Intl, navigator: {languages}, location: {search},
    document: {documentElement: element, getElementById: () => null, querySelectorAll: () => []},
    localStorage: {getItem: key => {if (denyStorage) throw new Error('blocked'); return storage.get(key) ?? null;},
      setItem: (key, value) => {if (denyStorage) throw new Error('blocked'); storage.set(key, value);}},
    addEventListener: (name, callback) => listeners.set(name, callback),
    matchMedia: () => ({matches: systemDark, addEventListener: (name, callback) => listeners.set('media:' + name, callback)}),
  });
  vm.runInContext(boot, result);
  return {context: result, element, storage, listeners};
}
for (const [languages, expected] of [
  [['zh-TW'], 'zh-Hant'], [['zh-HK'], 'zh-Hant'], [['zh-CN'], 'zh-Hans'],
  [['zh-Hans-HK'], 'zh-Hans'], [['en-GB'], 'en'], [['fr-FR', 'zh-TW'], 'zh-Hant'], [['fr-FR'], 'en'],
]) {
  const env = context({languages});
  assert.equal(env.element.lang, expected);
  assert.equal(env.element.dataset.theme, 'dark', 'First paint defaults dark regardless of OS');
}
assert.equal(context({languages: ['en'], saved: {'object-animation.language': 'zh-Hant'}}).element.lang, 'zh-Hant');
assert.equal(context({saved: {'object-animation.theme': 'light'}}).element.dataset.theme, 'light');
assert.equal(context({denyStorage: true}).element.dataset.theme, 'dark');
assert.equal(context({saved: {'object-animation.theme': 'invalid'}}).element.dataset.theme, 'dark');
assert.equal(context({saved: {'object-animation.theme': 'system'}, systemDark: true}).element.dataset.theme, 'dark');
assert.equal(context({languages:['en-US'],search:'?context_lang=zh-Hans'}).element.lang,'zh-Hans','Conversation language wins over browser default');
assert.equal(context({languages:['en-US'],search:'?context_lang=zh-Hant'}).element.lang,'zh-Hant');
assert.equal(context({search:'?context_lang=zh-Hans',saved:{'object-animation.language':'en'}}).element.lang,'en','Manual choice wins over conversation default');
assert.equal(context({search:'?context_lang=zh-Hans',saved:{'object-animation.language':'auto'}}).element.lang,'zh-Hans');

const env = context({languages: ['en-US']});
const modules = new Map();
async function load(filename) {
  filename = path.resolve(filename);
  if (!modules.has(filename)) modules.set(filename, new vm.SourceTextModule(await readFile(filename, 'utf8'), {context: env.context, identifier: filename}));
  return modules.get(filename);
}
async function evaluate(filename) {
  const module = await load(filename);
  if (module.status === 'unlinked') await module.link((specifier, from) => load(specifier.startsWith('/') ? path.join(root, specifier.slice(1)) : path.resolve(path.dirname(from.identifier), specifier)));
  if (module.status === 'linked') await module.evaluate();
  return module.namespace;
}
const i18n = await evaluate(path.join(root, 'i18n.js'));
i18n.initPreferences();
const changes = [];
const unsubscribe = i18n.onLocaleChange(locale => changes.push(locale));
i18n.setLanguage('zh-Hant');
assert.equal(i18n.t('prefs.language'), '語言');
assert.equal(env.element.lang, 'zh-Hant');
assert.equal(env.storage.get('object-animation.language'), 'zh-Hant');
i18n.setLanguage('en');
assert.equal(i18n.localizeError('请先打开项目'), 'Open a project first.');
assert.equal(i18n.localizeError('Artist-owned 项目文字 / custom error'), 'Artist-owned 项目文字 / custom error');
i18n.registerMessages({en: {'test.fallback': 'Frame {frame}: {label}'}, 'zh-Hans': {}, 'zh-Hant': {}});
i18n.setLanguage('zh-Hans');
assert.equal(i18n.t('test.fallback', {frame: 24, label: '$& <script>'}), 'Frame 24: $& <script>');
assert.equal(i18n.formatNumber(1.25, {minimumFractionDigits: 2}), '1.25');
unsubscribe();
i18n.setLanguage('en');
assert.deepEqual(changes, ['zh-Hant', 'en', 'zh-Hans']);
let themes = [];
i18n.onThemeChange(theme => themes.push(theme));
i18n.setTheme('light'); i18n.setTheme('dark');
assert.deepEqual(themes, ['light', 'dark']);
assert.equal(env.element.dataset.theme, 'dark');
assert.equal(env.element.dir, 'ltr');
assert.throws(() => i18n.setTheme('contrast-mode-not-installed'), /Unsupported interface theme/);

const counts = {};
for (const file of ['errors', 'review', 'authoring', 'viewport']) {
  const {messages} = await evaluate(path.join(root, `locales/${file}.js`));
  const keys = Object.keys(messages.en).sort();
  for (const locale of ['zh-Hans', 'zh-Hant']) {
    assert.deepEqual(Object.keys(messages[locale]).sort(), keys, `${file}: ${locale} key coverage`);
    for (const key of keys) {
      const fields = text => [...text.matchAll(/\{([A-Za-z][\w]*)\}/g)].map(match => match[1]).sort();
      assert.deepEqual(fields(messages[locale][key]), fields(messages.en[key]), `${file}:${locale}:${key} parameters`);
      assert.ok(messages[locale][key].length > 0, `${file}:${locale}:${key} empty`);
    }
  }
  i18n.registerMessages(messages);
  counts[file] = keys.length;
}
const all = new Set();
for (const file of ['errors', 'review', 'authoring', 'viewport']) {
  const {messages} = await evaluate(path.join(root, `locales/${file}.js`));
  for (const key of Object.keys(messages.en)) all.add(key);
}
for (const file of ['review.js', 'app.js', 'viewport.js', 'index.html', 'authoring.html']) {
  const source = await readFile(path.join(root, file), 'utf8');
  const keys = [...source.matchAll(/\bt\(['"]((?:review|authoring|viewport)\.[^'"]+)['"]\s*[,)]/g),
    ...source.matchAll(/data-i18n(?:-[\w-]+)?=['"]([^'"]+)['"]/g)].map(match => match[1]);
  for (const key of keys) assert.ok(all.has(key), `${file}: missing translation ${key}`);
}
console.log(JSON.stringify({status: 'PASS', checks: 'first paint, locale negotiation, storage failure, persistence, locale/theme callbacks, fallback, message/placeholder coverage', messagesPerLanguage: counts}, null, 2));
