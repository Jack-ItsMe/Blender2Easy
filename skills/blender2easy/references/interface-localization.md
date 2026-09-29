# Interface theme and localization

`editor/web/preferences-init.js` is the single source for locale metadata, browser negotiation, preference storage and initial theme. It runs before styles to avoid a bright first paint. `i18n.js` shares translation, safe parameter substitution, number formatting, error lookup and preference listeners across both pages and the viewport. All resources are served locally.

Current language IDs are `en`, `zh-Hans` and `zh-Hant`. Agents provide the dominant language of the current user conversation in review `ui_language`; generated URLs carry it as `context_lang`. With Automatic selected, that context takes priority over the browser language list. A saved manual choice takes priority over the automatic context. Browser lists are matched in preference order; `zh-TW`, `zh-HK` and `zh-MO` map to Traditional Chinese, other Chinese regional tags to Simplified Chinese, and explicit script tags take precedence. Unsupported languages fall back to English. The separate `lang` URL parameter is an explicit per-page override; the settings menu persists deliberate selections. Local storage keys remain `object-animation.language` and `object-animation.theme` for compatibility with earlier releases; storage failures are tolerated. Agent-authored questions and display labels must use the conversation language as well; changing an interface dictionary does not translate authored content.

## Adding a locale or message

1. Add the locale ID, native display name and text direction to the metadata in `preferences-init.js`. Extend tag negotiation if the language has distinct scripts or regional variants. RTL locales also require visual layout verification; declaring direction alone is insufficient.
2. Add that locale's shared preference messages in `i18n.js` and entries in `locales/review.js`, `locales/authoring.js`, `locales/viewport.js` and `locales/errors.js`. Keep identical keys and named placeholders across languages. Missing messages fall back to English.
3. Use `t(key, params)` for product text and `formatNumber` for human-readable numbers. Keep number input values machine-readable. Use `textContent` or escaped markup for inserted text; parameters may contain arbitrary user-authored strings.
4. Mark static leaf nodes and their attributes with `data-i18n`, `data-i18n-title`, `data-i18n-aria-label`, `data-i18n-placeholder` or `data-i18n-alt`. Dynamic labels belong to the page's locale refresh routine, without static attributes that could overwrite their current state.
5. Refresh interface text in place. Never reload a project, reset a request, recreate editable form controls, alter an enum/ID, or translate authored content to switch languages. Preserve selection, notes, unsaved fields, playback position and annotations. Dispose viewport subscriptions together with the viewport.

Known server messages use an exact lookup in `locales/errors.js`; unknown technical errors retain their original content. This preserves useful paths and diagnostics without changing the server's error contract.

## Theme contract and verification

Use semantic CSS variables from `theme.css` rather than new fixed light colors. Theme changes must not alter project materials, lights, saved JSON or render settings. Free-orbit viewing can use the theme backdrop; a project camera preserves the authored scene background and uses the theme only outside its frame.

For each language, verify key/placeholder parity, static and dynamic labels, dialogs, error states and accessible names. Exercise both pages while edits are unsaved, including the timeline and surface marks. Check persistence after reload, automatic language fallback, blocked storage, all theme choices and narrow layouts. Retain geometry/raycast, review-state and backend/MCP regression coverage when updating the shared viewport or runtime.
