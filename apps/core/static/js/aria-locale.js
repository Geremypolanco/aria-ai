/* ─────────────────────────────────────────────────────────────────────────
 * ARIA locale — automatic language detection with manual override.
 *
 * Resolution order (highest priority first):
 *   1. Saved manual preference (localStorage `aria_locale`)
 *   2. Browser language (`navigator.language`: any "es*" → `es`, else `en`)
 *   3. Default: `en`
 *
 * A manual choice is persisted in localStorage AND in a `locale` cookie
 * (1 year, Path=/, SameSite=Lax) so the server can honour it on later
 * requests too. The user can always switch with the always-visible
 * ES|EN toggle; the manual choice wins over detection on every visit.
 * ───────────────────────────────────────────────────────────────────────── */
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    root.AriaLocale = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var SUPPORTED = ['es', 'en'];
  var DEFAULT = 'en';
  var LS_KEY = 'aria_locale';
  var COOKIE_NAME = 'locale';
  var COOKIE_DAYS = 365;

  var current = DEFAULT;

  /* Normalize a BCP-47-ish tag to a supported locale, or null. */
  function normalizeLocale(v) {
    if (!v || typeof v !== 'string') return null;
    var lang = v.trim().toLowerCase();
    if (/^es([-_].*)?$/.test(lang)) return 'es';
    if (/^en([-_].*)?$/.test(lang)) return 'en';
    return null;
  }

  /* Browser detection: any Spanish variant → 'es', anything else → null
   * (caller falls back to DEFAULT). */
  function detectLocale(navLang) {
    var n = normalizeLocale(navLang);
    return n === 'es' ? 'es' : null;
  }

  /* Pure resolution: saved preference wins, then browser, then default. */
  function resolveLocale(savedRaw, navLang) {
    var saved = normalizeLocale(savedRaw);
    if (saved) return saved;
    return detectLocale(navLang) || DEFAULT;
  }

  function readSaved() {
    try {
      if (typeof localStorage === 'undefined') return null;
      return normalizeLocale(localStorage.getItem(LS_KEY));
    } catch (e) { return null; }
  }

  function writeSaved(locale) {
    try {
      if (typeof localStorage === 'undefined') return;
      localStorage.setItem(LS_KEY, locale);
    } catch (e) { /* private mode etc. — cookie still persists */ }
  }

  /* Build the Set-Cookie / document.cookie value for the locale cookie. */
  function cookieHeader(locale, isSecure) {
    var parts = [
      COOKIE_NAME + '=' + locale,
      'Max-Age=' + COOKIE_DAYS * 86400,
      'Path=/',
      'SameSite=Lax'
    ];
    if (isSecure) parts.push('Secure');
    return parts.join('; ');
  }

  function writeCookie(locale) {
    try {
      if (typeof document === 'undefined') return;
      var secure = typeof location !== 'undefined' && location.protocol === 'https:';
      document.cookie = cookieHeader(locale, secure);
    } catch (e) { /* ignore */ }
  }

  /* Translate a dictionary key. Falls back to English, then to the key. */
  function t(key, vars) {
    var s = key;
    try {
      var D = (typeof window !== 'undefined' && window.ARIA_I18N) || null;
      var table = D && D[current];
      if (table && table[key] != null) s = table[key];
      else if (D && D.en && D.en[key] != null) s = D.en[key];
    } catch (e) { /* dictionary unavailable — use key */ }
    if (vars) {
      s = String(s).replace(/\{(\w+)\}/g, function (m, k) {
        return vars[k] != null ? vars[k] : m;
      });
    }
    return s;
  }

  function getLocale() { return current; }

  function applyLangAttr(locale) {
    try {
      if (typeof document !== 'undefined') {
        document.documentElement.setAttribute('lang', locale);
      }
    } catch (e) { /* ignore */ }
  }

  function refreshToggle(locale) {
    try {
      if (typeof document === 'undefined') return;
      var btns = document.querySelectorAll('[data-locale-btn]');
      for (var i = 0; i < btns.length; i++) {
        var on = btns[i].getAttribute('data-locale-btn') === locale;
        btns[i].setAttribute('aria-pressed', on ? 'true' : 'false');
      }
    } catch (e) { /* ignore */ }
  }

  /* Manual override: persists (localStorage + 1-yr cookie), applies, repaints. */
  function setLocale(locale, opts) {
    locale = normalizeLocale(locale) || DEFAULT;
    current = locale;
    writeSaved(locale);
    writeCookie(locale);
    applyLangAttr(locale);
    refreshToggle(locale);
    if (opts && typeof opts.onApply === 'function') opts.onApply(locale);
    return locale;
  }

  /* Render the always-visible ES|EN toggle into a container element/id. */
  function renderToggle(target) {
    if (typeof document === 'undefined') return null;
    var el = typeof target === 'string' ? document.getElementById(target) : target;
    if (!el) return null;
    el.innerHTML =
      '<div class="locale-toggle" role="group" aria-label="Language / Idioma">' +
      '<button type="button" data-locale-btn="es">ES</button>' +
      '<button type="button" data-locale-btn="en">EN</button>' +
      '</div>';
    var btns = el.querySelectorAll('[data-locale-btn]');
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener('click', function () {
        setLocale(this.getAttribute('data-locale-btn'), { onApply: onApplyHook });
      });
    }
    refreshToggle(current);
    return el;
  }

  var onApplyHook = null;

  /* Full init: resolve → persist cookie → set <html lang> → apply → toggle. */
  function init(opts) {
    opts = opts || {};
    onApplyHook = typeof opts.onApply === 'function' ? opts.onApply : null;
    var nav = (typeof navigator !== 'undefined' && navigator.language) || null;
    var saved = (typeof opts.saved !== 'undefined') ? normalizeLocale(opts.saved) : readSaved();
    current = resolveLocale(saved, nav);
    writeCookie(current);
    applyLangAttr(current);
    if (onApplyHook) onApplyHook(current);
    if (opts.toggle) renderToggle(opts.toggle);
    return current;
  }

  /* Earliest possible pass (call from <head>): sets <html lang> from the
   * saved preference or browser language before first paint. */
  function early() {
    if (typeof document === 'undefined') return DEFAULT;
    var nav = (typeof navigator !== 'undefined' && navigator.language) || null;
    var locale = resolveLocale(readSaved(), nav);
    applyLangAttr(locale);
    return locale;
  }

  return {
    SUPPORTED: SUPPORTED,
    DEFAULT: DEFAULT,
    LS_KEY: LS_KEY,
    COOKIE_NAME: COOKIE_NAME,
    COOKIE_DAYS: COOKIE_DAYS,
    normalizeLocale: normalizeLocale,
    detectLocale: detectLocale,
    resolveLocale: resolveLocale,
    cookieHeader: cookieHeader,
    getLocale: getLocale,
    setLocale: setLocale,
    renderToggle: renderToggle,
    init: init,
    early: early,
    t: t
  };
});
