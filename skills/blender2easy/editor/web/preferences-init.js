/* Synchronous first-paint preferences; no requests and no project mutations. */
(function (root) {
  'use strict';
  if (root.ObjectAnimationPreferences) return;
  const locales = [
    {id: 'en', label: 'English', dir: 'ltr'},
    {id: 'zh-Hans', label: '简体中文', dir: 'ltr'},
    {id: 'zh-Hant', label: '繁體中文', dir: 'ltr'},
  ];
  const keys = {language: 'object-animation.language', theme: 'object-animation.theme'};
  function read(key) {try {return root.localStorage?.getItem(key);} catch {return null;}}
  function write(key, value) {try {root.localStorage?.setItem(key, value);} catch {}}
  function resolveLocale(value) {
    const tag = String(value || '').replace(/_/g, '-').toLowerCase();
    const exact = locales.find(item => item.id.toLowerCase() === tag);
    if (exact) return exact.id;
    if (/^zh(?:-|$)/.test(tag)) {
      if (/(?:^|-)hant(?:-|$)/.test(tag)) return 'zh-Hant';
      if (/(?:^|-)hans(?:-|$)/.test(tag)) return 'zh-Hans';
      return /(?:^|-)(tw|hk|mo)(?:-|$)/.test(tag) ? 'zh-Hant' : 'zh-Hans';
    }
    return locales.find(item => item.id.toLowerCase() === tag.split('-')[0])?.id || null;
  }
  let contextLanguage = null;
  try {contextLanguage = resolveLocale(new URLSearchParams(root.location?.search || '').get('context_lang'));} catch {}
  function preferredLocale() {
    if (contextLanguage) return contextLanguage;
    const languages = root.navigator?.languages?.length ? root.navigator.languages : [root.navigator?.language];
    return languages.map(resolveLocale).find(Boolean) || 'en';
  }
  const storedLanguage = read(keys.language), storedTheme = read(keys.theme);
  let requestedLanguage;
  try {requestedLanguage = new URLSearchParams(root.location?.search || '').get('lang');} catch {}
  const explicit = resolveLocale(requestedLanguage);
  const state = {
    language: explicit || (storedLanguage === 'auto' ? 'auto' : resolveLocale(storedLanguage)) || 'auto',
    theme: ['dark', 'light', 'system'].includes(storedTheme) ? storedTheme : 'dark',
  };
  function locale() {return state.language === 'auto' ? preferredLocale() : state.language;}
  function theme() {return state.theme === 'system' ? (root.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : state.theme;}
  function apply() {
    const element = root.document?.documentElement;
    if (element) {
      element.dataset.theme = theme();
      element.lang = locale();
      element.dir = locales.find(item => item.id === locale())?.dir || 'ltr';
      element.style.colorScheme = theme();
    }
    return {language: state.language, locale: locale(), theme: theme(), themePreference: state.theme};
  }
  root.ObjectAnimationPreferences = {locales, keys, state, resolveLocale, preferredLocale, locale, theme, apply, read, write};
  apply();
})(globalThis);
