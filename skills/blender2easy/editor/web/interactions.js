// Small shell interactions. No project data, viewport state or locale ownership.
const instances = new WeakMap();
const rangeSelector = 'input[type="range"]';
const controlSelector = 'button, summary';
const titles = new WeakMap();
let tooltipSequence = 0;

function controlsWithin(root, selector) {
  if (!root) return [];
  return [...(root.matches?.(selector) ? [root] : []), ...(root.querySelectorAll?.(selector) ?? [])];
}

/** Call after assigning range.value in code; user input is handled automatically. */
export function refreshRanges(root = globalThis.document) {
  for (const range of controlsWithin(root, rangeSelector)) {
    const min = Number(range.min === '' ? 0 : range.min);
    const max = Number(range.max === '' ? 100 : range.max);
    const value = Number(range.value);
    const fraction = Number.isFinite(min) && Number.isFinite(max) && Number.isFinite(value) && max > min
      ? Math.min(1, Math.max(0, (value - min) / (max - min))) : 0;
    const progress = `${Number((fraction * 100).toFixed(4))}%`;
    if (range.style?.getPropertyValue('--range-progress') !== progress) range.style?.setProperty('--range-progress', progress);
  }
}

/** Idempotent, with explicit cleanup for hosts that replace the workspace. */
export function initWorkspaceInteractions(doc = globalThis.document) {
  if (!doc?.body || typeof doc.createElement !== 'function' || typeof doc.addEventListener !== 'function') return null;
  if (instances.has(doc)) return instances.get(doc);
  const win = doc.defaultView ?? globalThis;
  const managed = new Set();
  const ownedLabels = new WeakMap();
  const tooltip = doc.createElement('div');
  let id;
  do {id = `workspace-tooltip-${++tooltipSequence}`;} while (doc.getElementById?.(id));
  tooltip.id = id;
  tooltip.className = 'workspace-tooltip';
  tooltip.setAttribute('role', 'tooltip');
  tooltip.hidden = true;
  doc.body.appendChild(tooltip);
  let target = null, timer = null, disposed = false;
  const listen = (node, type, listener, options) => {
    node?.addEventListener?.(type, listener, options);
    return () => node?.removeEventListener?.(type, listener, options);
  };
  const later = (callback, delay) => (win.setTimeout ?? globalThis.setTimeout).call(win, callback, delay);
  const cancel = handle => (win.clearTimeout ?? globalThis.clearTimeout).call(win, handle);

  function disconnectDescription(control) {
    if (!control) return;
    const existing = (control.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(value => value && value !== id);
    if (existing.length) control.setAttribute('aria-describedby', existing.join(' '));
    else control.removeAttribute('aria-describedby');
  }

  function hide() {
    if (timer !== null) cancel(timer);
    timer = null;
    disconnectDescription(target);
    target = null;
    tooltip.hidden = true;
    tooltip.textContent = '';
  }

  function canShow(control) {
    return !!control && control.isConnected && !control.closest('[hidden], [inert], [aria-hidden="true"]')
      && (typeof control.getClientRects !== 'function' || control.getClientRects().length > 0) && !!titles.get(control);
  }

  function releaseLabel(control) {
    const previous = ownedLabels.get(control);
    if (previous != null && control.getAttribute('aria-label') === previous) control.removeAttribute('aria-label');
    ownedLabels.delete(control);
  }

  function preserveName(control, text) {
    const previous = ownedLabels.get(control), current = control.getAttribute('aria-label');
    if (previous != null && current !== previous) ownedLabels.delete(control);
    if (!text.trim() || control.hasAttribute('aria-labelledby')) {releaseLabel(control); return;}
    if (!ownedLabels.has(control) && control.hasAttribute('aria-label')) return;
    // CSS can hide a button's text while textContent still contains its label.
    // An empty innerText is meaningful; only hosts without it use textContent.
    const renderedText = control.innerText;
    const visibleText = typeof renderedText === 'string' ? renderedText : (control.textContent ?? '');
    if (ownedLabels.has(control) || !visibleText.trim()) {
      if (current !== text) control.setAttribute('aria-label', text);
      ownedLabels.set(control, text);
    }
  }

  function refreshNames() {
    for (const control of managed) if (control.isConnected) preserveName(control, titles.get(control) ?? '');
  }

  function position() {
    if (!target || tooltip.hidden) return;
    const viewport = win.visualViewport;
    const left = viewport?.offsetLeft ?? 0, top = viewport?.offsetTop ?? 0;
    const width = viewport?.width ?? win.innerWidth ?? doc.documentElement.clientWidth;
    const height = viewport?.height ?? win.innerHeight ?? doc.documentElement.clientHeight;
    const margin = 10, gap = 8;
    tooltip.style.maxWidth = `${Math.max(40, Math.min(280, width - margin * 2))}px`;
    tooltip.style.maxHeight = `${Math.max(20, height - margin * 2)}px`;
    const anchor = target.getBoundingClientRect(), box = tooltip.getBoundingClientRect();
    const x = Math.min(Math.max(anchor.left + (anchor.width - box.width) / 2, left + margin), Math.max(left + margin, left + width - box.width - margin));
    const above = anchor.top - box.height - gap;
    const useAbove = above >= top + margin;
    const y = useAbove ? above : anchor.bottom + gap;
    tooltip.dataset.placement = useAbove ? 'top' : 'bottom';
    tooltip.style.left = `${Math.round(x)}px`;
    tooltip.style.top = `${Math.round(Math.min(Math.max(y, top + margin), Math.max(top + margin, top + height - box.height - margin)))}px`;
  }

  function captureTitle(control) {
    if (!control?.matches?.(controlSelector) || !control.hasAttribute('title')) return;
    const text = control.getAttribute('title') ?? '';
    // Only the title attribute is transferred. Authored text/HTML is never read
    // as markup or rewritten, and data-i18n-title stays owned by the page.
    preserveName(control, text);
    if (text.trim()) {titles.set(control, text); managed.add(control);}
    else {titles.delete(control); managed.delete(control);}
    control.removeAttribute('title');
    if (target === control) {
      if (!text.trim()) hide();
      else if (!tooltip.hidden) {tooltip.textContent = text; position();}
    }
  }

  function initialize(root) {
    for (const control of controlsWithin(root, 'button[title], summary[title]')) captureTitle(control);
    refreshRanges(root);
  }

  function schedule(control) {
    if (!control) return;
    captureTitle(control);
    if (titles.has(control)) preserveName(control, titles.get(control));
    if (target === control) return;
    hide();
    if (!canShow(control)) return;
    target = control;
    // A tooltip for a modal control must live in that dialog's top layer.
    const host = control.closest('dialog[open]') ?? doc.body;
    if (tooltip.parentNode !== host) host.appendChild(tooltip);
    timer = later(() => {
      timer = null;
      if (disposed || !canShow(target)) {hide(); return;}
      tooltip.textContent = titles.get(target);
      tooltip.hidden = false;
      position();
      const descriptions = new Set((target.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean));
      descriptions.add(id);
      target.setAttribute('aria-describedby', [...descriptions].join(' '));
    }, 300);
  }

  function controlAt(event) {return event.target?.closest?.(controlSelector) ?? null;}
  const onOver = event => {
    if (event.pointerType === 'touch') return;
    const control = controlAt(event);
    if (control && !control.contains(event.relatedTarget)) schedule(control);
  };
  const onOut = event => {
    const control = controlAt(event);
    if (control === target && !control.contains(event.relatedTarget)) hide();
  };
  const onFocus = event => schedule(controlAt(event));
  const onBlur = event => {if (controlAt(event) === target) hide();};
  const onKey = event => {if (event.key === 'Escape') hide();};
  const onRange = event => {if (event.target?.matches?.(rangeSelector)) refreshRanges(event.target);};
  const onResize = () => {hide(); refreshNames();};
  const onPageShow = () => {hide(); initialize(doc); refreshNames();};
  const cleanups = [
    listen(doc, 'pointerover', onOver), listen(doc, 'pointerout', onOut),
    listen(doc, 'focusin', onFocus), listen(doc, 'focusout', onBlur),
    listen(doc, 'keydown', onKey, true), listen(doc, 'pointerdown', hide, true), listen(doc, 'click', hide, true),
    listen(doc, 'input', onRange), listen(doc, 'change', onRange),
    listen(doc, 'close', hide, true),
    listen(doc, 'scroll', hide, true), listen(win, 'resize', onResize), listen(win, 'pageshow', onPageShow),
    listen(win.visualViewport, 'resize', onResize), listen(win.visualViewport, 'scroll', hide),
  ];
  const Observer = win.MutationObserver ?? globalThis.MutationObserver;
  const observer = typeof Observer === 'function' ? new Observer(records => {
    for (const record of records) {
      if (record.type === 'attributes') {
        if (record.attributeName === 'title') captureTitle(record.target);
        else if (record.target.matches?.(rangeSelector)) refreshRanges(record.target);
      } else {
        for (const node of record.addedNodes) if (node.nodeType === 1 && node !== tooltip) initialize(node);
        for (const node of record.removedNodes) {
          for (const control of controlsWithin(node, controlSelector)) {
            if (control.isConnected || !managed.has(control)) continue;
            // Restore detached controls so a later reinsertion still initializes.
            if (!control.hasAttribute('title')) control.setAttribute('title', titles.get(control));
            releaseLabel(control);
            titles.delete(control); managed.delete(control);
          }
        }
      }
    }
    if (target && !canShow(target)) hide();
  }) : null;
  // Deliberately exclude style/ARIA/class: our own progress and tooltip updates
  // cannot feed an observer loop. Programmatic .value uses refreshRanges().
  observer?.observe(doc.body, {subtree: true, childList: true, attributes: true, attributeFilter: ['title', 'min', 'max', 'value', 'type', 'hidden', 'disabled']});
  initialize(doc);
  const controller = {
    refreshRanges,
    destroy() {
      if (disposed) return;
      disposed = true;
      observer?.disconnect();
      hide();
      for (const cleanup of cleanups) cleanup();
      for (const control of managed) {
        if (!control.hasAttribute('title')) control.setAttribute('title', titles.get(control));
        releaseLabel(control);
        titles.delete(control);
      }
      managed.clear();
      tooltip.remove();
      instances.delete(doc);
    },
  };
  instances.set(doc, controller);
  return controller;
}

// Pages can update programmatic ranges without importing a browser module into
// their business logic. The API is intentionally immutable, with no project state.
Object.defineProperty(globalThis, 'ObjectAnimationInteractions', {
  value: Object.freeze({refreshRanges, initWorkspaceInteractions}), writable: false, configurable: true,
});

// Independent HTML module entry point. Limited VM documents used by business
// tests can import refreshRanges without starting browser-only behavior.
if (typeof globalThis.document?.createElement === 'function' && typeof globalThis.document?.addEventListener === 'function') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => initWorkspaceInteractions(), {once: true});
  else initWorkspaceInteractions();
}
