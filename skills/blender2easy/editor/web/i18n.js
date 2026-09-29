import '/preferences-init.js';
import {messages as errors, sourceErrors} from '/locales/errors.js';

const preferences = globalThis.ObjectAnimationPreferences;
const dictionaries = Object.fromEntries(preferences.locales.map(item => [item.id, {}]));
const localeListeners = new Set(), themeListeners = new Set();
let initialized = false;
let previousLocale = preferences.locale(), previousTheme = preferences.theme();

export const supportedLocales = preferences.locales;
export const getLocale = () => preferences.locale();
export const getLanguage = () => preferences.state.language;
export const getTheme = () => preferences.theme();
export const getThemePreference = () => preferences.state.theme;

export function registerMessages(messages) {
  for (const [locale, entries] of Object.entries(messages)) {
    if (!dictionaries[locale]) dictionaries[locale] = {};
    for (const [key, value] of Object.entries(entries)) {
      if (typeof value !== 'string') throw new TypeError(`Message ${locale}:${key} must be a string`);
      dictionaries[locale][key] = value;
    }
  }
}

export function t(key, params = {}) {
  const template = dictionaries[getLocale()]?.[key] ?? dictionaries.en[key] ?? key;
  return template.replace(/\{([A-Za-z][\w]*)\}/g, (match, name) =>
    Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match);
}

export function formatNumber(value, options = {}) {
  if (!Number.isFinite(Number(value))) return String(value);
  return new Intl.NumberFormat(getLocale(), options).format(Number(value));
}

export function localizeError(value) {
  const raw = typeof value === 'string' ? value : value?.error || value?.message || String(value ?? '');
  const key = sourceErrors[raw];
  if (key) return t(key);
  if (/^(Failed to fetch|NetworkError when attempting to fetch resource\.?|Load failed)$/.test(raw)) return t('errors.connection');
  // Unknown diagnostics, paths and authored content are kept verbatim.
  return raw;
}

const attributes = ['title', 'aria-label', 'placeholder', 'alt'];
export function translatePage(root = document) {
  for (const node of root.querySelectorAll('[data-i18n]')) {
    node.textContent = t(node.dataset.i18n);
  }
  for (const attribute of attributes) {
    for (const node of root.querySelectorAll(`[data-i18n-${attribute}]`)) {
      node.setAttribute(attribute, t(node.getAttribute(`data-i18n-${attribute}`)));
    }
  }
}

export function onLocaleChange(callback) {localeListeners.add(callback); return () => localeListeners.delete(callback);}
export function onThemeChange(callback) {themeListeners.add(callback); return () => themeListeners.delete(callback);}

function update() {
  preferences.apply();
  if (typeof document !== 'undefined') {
    translatePage();
    const language = document.getElementById('ui-language'), theme = document.getElementById('ui-theme');
    if (language) language.value = getLanguage();
    if (theme) theme.value = getThemePreference();
  }
  const nextLocale = getLocale(), nextTheme = getTheme();
  if (nextLocale !== previousLocale) {
    previousLocale = nextLocale;
    for (const callback of localeListeners) callback(nextLocale);
  }
  if (nextTheme !== previousTheme) {
    previousTheme = nextTheme;
    for (const callback of themeListeners) callback(nextTheme);
  }
}

export function setLanguage(language) {
  const value = language === 'auto' ? 'auto' : preferences.resolveLocale(language);
  if (!value) throw new RangeError('Unsupported interface language');
  preferences.state.language = value;
  preferences.write(preferences.keys.language, value);
  update();
}

export function setTheme(theme) {
  if (!['dark', 'light', 'system'].includes(theme)) throw new RangeError('Unsupported interface theme');
  preferences.state.theme = theme;
  preferences.write(preferences.keys.theme, theme);
  update();
}

function translated(tag, key) {
  const node = document.createElement(tag);
  node.dataset.i18n = key;
  node.textContent = t(key);
  return node;
}

function createPreferences(mount) {
  const details = document.createElement('details');
  details.className = 'ui-preferences';
  const summary = document.createElement('summary');
  summary.className = 'preferences-toggle';
  summary.dataset.i18nTitle = 'prefs.label';
  summary.setAttribute('data-i18n-aria-label', 'prefs.label');
  summary.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c-5 5-5 13 0 18M12 3c5 5 5 13 0 18"/></svg>';
  summary.append(translated('span', 'prefs.label'));
  const popover = document.createElement('div');
  popover.className = 'preferences-popover';
  const label = document.createElement('label');
  label.className = 'preference-row';
  label.append(translated('span', 'prefs.language'));
  const languages = document.createElement('select');
  languages.id = 'ui-language';
  languages.setAttribute('data-i18n-aria-label', 'prefs.language');
  const automatic = translated('option', 'prefs.autoLanguage'); automatic.value = 'auto'; languages.append(automatic);
  for (const locale of supportedLocales) {
    const option = document.createElement('option'); option.value = locale.id; option.textContent = locale.label; option.lang = locale.id; languages.append(option);
  }
  languages.value = getLanguage();
  languages.addEventListener('change', () => setLanguage(languages.value));
  label.append(languages); popover.append(label);
  const themeLabel = document.createElement('label'); themeLabel.className = 'preference-row'; themeLabel.append(translated('span', 'prefs.theme'));
  const themes = document.createElement('select'); themes.id = 'ui-theme'; themes.setAttribute('data-i18n-aria-label', 'prefs.theme');
  for (const value of ['dark', 'light', 'system']) {const option = translated('option', 'prefs.' + value); option.value = value; themes.append(option);}
  themes.value = getThemePreference(); themes.addEventListener('change', () => setTheme(themes.value));
  themeLabel.append(themes); popover.append(themeLabel);
  details.append(summary, popover); mount.replaceChildren(details);
  document.addEventListener('click', event => {if (details.open && !details.contains(event.target)) details.open = false;});
  details.addEventListener('keydown', event => {if (event.key === 'Escape') {event.preventDefault();event.stopPropagation();details.open = false; summary.focus();}});
}

export function initPreferences() {
  if (!initialized) {
    initialized = true;
    for (const mount of document.querySelectorAll('[data-ui-preferences]')) createPreferences(mount);
    globalThis.addEventListener?.('storage', event => {
      if (event.key !== null && !Object.values(preferences.keys).includes(event.key)) return;
      if (event.key === null || event.key === preferences.keys.language) {
        const language = preferences.read(preferences.keys.language);
        preferences.state.language = language === 'auto' ? 'auto' : preferences.resolveLocale(language) || 'auto';
      }
      if (event.key === null || event.key === preferences.keys.theme) {
        const theme = preferences.read(preferences.keys.theme);
        preferences.state.theme = ['dark', 'light', 'system'].includes(theme) ? theme : 'dark';
      }
      update();
    });
    globalThis.addEventListener?.('languagechange', () => {if (getLanguage() === 'auto') update();});
    const system = globalThis.matchMedia?.('(prefers-color-scheme: dark)');
    const change = () => {if (getThemePreference() === 'system') update();};
    if (system?.addEventListener) system.addEventListener('change', change);
    else system?.addListener?.(change);
  }
  update();
}

registerMessages({
  en: {'prefs.label': 'Display settings', 'prefs.language': 'Language', 'prefs.theme': 'Theme', 'prefs.autoLanguage': 'Automatic', 'prefs.dark': 'Dark', 'prefs.light': 'Light', 'prefs.system': 'System', 'errors.connection': 'The local service is unavailable. Reconnect or restart the preview.'},
  'zh-Hans': {'prefs.label': '显示设置', 'prefs.language': '语言', 'prefs.theme': '主题', 'prefs.autoLanguage': '自动选择', 'prefs.dark': '深色', 'prefs.light': '浅色', 'prefs.system': '跟随系统', 'errors.connection': '本地服务暂时不可用，请重新连接或启动预览。'},
  'zh-Hant': {'prefs.label': '顯示設定', 'prefs.language': '語言', 'prefs.theme': '主題', 'prefs.autoLanguage': '自動選擇', 'prefs.dark': '深色', 'prefs.light': '淺色', 'prefs.system': '跟隨系統', 'errors.connection': '本機服務暫時無法使用，請重新連線或啟動預覽。'},
});
registerMessages(errors);
