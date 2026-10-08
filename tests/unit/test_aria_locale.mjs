/* Tests for apps/core/static/js/aria-locale.js + aria-i18n.js
 *
 * Covers the permanent language rule's resolution order:
 *   saved manual preference > browser language (navigator.language) > default 'en'
 * plus cookie/localStorage persistence, the always-visible toggle, and
 * EN/ES dictionary parity.
 *
 * Run: node --test tests/unit/test_aria_locale.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const AriaLocale = require('../../apps/core/static/js/aria-locale.js');
const I18N = require('../../apps/core/static/js/aria-i18n.js');

// ── pure resolution ──────────────────────────────────────────────
test('normalizeLocale maps variants', () => {
  assert.equal(AriaLocale.normalizeLocale('es-MX'), 'es');
  assert.equal(AriaLocale.normalizeLocale('es_ES'), 'es');
  assert.equal(AriaLocale.normalizeLocale('ES'), 'es');
  assert.equal(AriaLocale.normalizeLocale('es-419'), 'es');
  assert.equal(AriaLocale.normalizeLocale('en-US'), 'en');
  assert.equal(AriaLocale.normalizeLocale('en'), 'en');
  assert.equal(AriaLocale.normalizeLocale('fr-FR'), null);
  assert.equal(AriaLocale.normalizeLocale('pt-BR'), null);
  assert.equal(AriaLocale.normalizeLocale(''), null);
  assert.equal(AriaLocale.normalizeLocale(null), null);
  assert.equal(AriaLocale.normalizeLocale(undefined), null);
});

test('detectLocale: only Spanish variants resolve', () => {
  assert.equal(AriaLocale.detectLocale('es-MX'), 'es');
  assert.equal(AriaLocale.detectLocale('es'), 'es');
  assert.equal(AriaLocale.detectLocale('en-US'), null);
  assert.equal(AriaLocale.detectLocale('fr-FR'), null);
  assert.equal(AriaLocale.detectLocale(undefined), null);
});

test('resolution order: saved > browser > default', () => {
  const r = AriaLocale.resolveLocale;
  // saved manual preference always wins
  assert.equal(r('es', 'en-US'), 'es');
  assert.equal(r('en', 'es-MX'), 'en');
  assert.equal(r('es', 'es-AR'), 'es');
  // then browser language
  assert.equal(r(null, 'es-MX'), 'es');
  assert.equal(r(undefined, 'es'), 'es');
  assert.equal(r(null, 'es-419'), 'es');
  // invalid saved value falls through to browser
  assert.equal(r('de', 'es'), 'es');
  assert.equal(r('de', 'fr'), 'en');
  assert.equal(r('', 'es-CO'), 'es');
  // default when nothing matches
  assert.equal(r(null, 'fr-FR'), 'en');
  assert.equal(r(null, 'en-US'), 'en');
  assert.equal(r(null, null), 'en');
  assert.equal(r(undefined, undefined), 'en');
});

// ── persistence: 1-year locale cookie ────────────────────────────
test('cookieHeader carries a 1-year Max-Age', () => {
  const h = AriaLocale.cookieHeader('es', false);
  assert.match(h, /locale=es/);
  assert.match(h, /Max-Age=31536000/); // 365 days
  assert.match(h, /Path=\//);
  assert.match(h, /SameSite=Lax/);
  assert.doesNotMatch(h, /Secure/);
  assert.match(AriaLocale.cookieHeader('en', true), /Secure/);
});

// ── browser wiring (mocked DOM) ──────────────────────────────────
function installFakes({ navLang = 'es-MX', saved = null } = {}) {
  const store = {};
  if (saved) store[AriaLocale.LS_KEY] = saved;
  global.localStorage = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
    _store: store,
  };
  // Node ≥21 ships a getter-only global `navigator` — override via defineProperty.
  const origNav = Object.getOwnPropertyDescriptor(global, 'navigator');
  Object.defineProperty(global, 'navigator', {
    configurable: true, writable: true, value: { language: navLang },
  });
  global.__origNavigator = origNav || null;
  const buttons = [];
  const container = {
    _html: '',
    set innerHTML(h) {
      this._html = h;
      buttons.length = 0;
      for (const loc of ['es', 'en']) {
        const btn = {
          _loc: loc, _pressed: null, _fn: null,
          getAttribute: (k) => (k === 'data-locale-btn' ? btn._loc : btn._pressed),
          setAttribute: (k, v) => { if (k === 'aria-pressed') btn._pressed = v; },
          addEventListener: (ev, fn) => { btn._fn = fn; },
          click() { btn._fn.call(btn); },
        };
        buttons.push(btn);
      }
    },
    get innerHTML() { return this._html; },
    querySelectorAll: (sel) => (sel === '[data-locale-btn]' ? buttons : []),
  };
  global.document = {
    _buttons: buttons,
    _lang: null,
    _cookie: '',
    documentElement: { setAttribute: (k, v) => { if (k === 'lang') global.document._lang = v; } },
    getElementById: (id) => (id === 'localeWrap' ? container : null),
    querySelectorAll: (sel) => (sel === '[data-locale-btn]' ? buttons : []),
  };
  Object.defineProperty(global.document, 'cookie', {
    configurable: true,
    get() { return this._cookie; },
    set(v) { this._cookie = v; },
  });
  global.window = { ARIA_I18N: I18N };
  global.location = { protocol: 'https:' };
  return { store, buttons, container };
}

function uninstallFakes() {
  delete global.localStorage;
  if (global.__origNavigator) {
    Object.defineProperty(global, 'navigator', global.__origNavigator);
  } else {
    delete global.navigator;
  }
  delete global.__origNavigator;
  delete global.document;
  delete global.window;
  delete global.location;
}

test('init: browser Spanish with no saved preference → es', () => {
  installFakes({ navLang: 'es-MX' });
  try {
    const loc = AriaLocale.init({ toggle: 'localeWrap' });
    assert.equal(loc, 'es');
    assert.equal(global.document._lang, 'es');
    // toggle rendered and reflects the resolved locale
    const [es, en] = global.document._buttons;
    assert.equal(es._pressed, 'true');
    assert.equal(en._pressed, 'false');
  } finally { uninstallFakes(); }
});

test('init: saved manual choice beats browser detection', () => {
  installFakes({ navLang: 'es-MX', saved: 'en' });
  try {
    assert.equal(AriaLocale.init({ toggle: 'localeWrap' }), 'en');
    assert.equal(global.document._lang, 'en');
  } finally { uninstallFakes(); }
});

test('init: non-Spanish browser with nothing saved → en default', () => {
  installFakes({ navLang: 'fr-FR' });
  try {
    assert.equal(AriaLocale.init({}), 'en');
  } finally { uninstallFakes(); }
});

test('early(): sets <html lang> before paint from saved/browser', () => {
  installFakes({ navLang: 'es-CO' });
  try {
    assert.equal(AriaLocale.early(), 'es');
    assert.equal(global.document._lang, 'es');
  } finally { uninstallFakes(); }
});

test('setLocale persists localStorage + 1-year cookie and repaints toggle', () => {
  const { store, buttons } = installFakes({ navLang: 'en-US' });
  try {
    AriaLocale.init({ toggle: 'localeWrap' });
    assert.equal(AriaLocale.getLocale(), 'en');
    // user flips the always-visible toggle to ES
    buttons[0].click(); // the ES button
    assert.equal(AriaLocale.getLocale(), 'es');
    assert.equal(store[AriaLocale.LS_KEY], 'es');
    assert.match(global.document._cookie, /locale=es/);
    assert.match(global.document._cookie, /Max-Age=31536000/);
    assert.equal(global.document._lang, 'es');
    assert.equal(buttons[0]._pressed, 'true');
    assert.equal(buttons[1]._pressed, 'false');
    // and back to EN
    buttons[1].click();
    assert.equal(AriaLocale.getLocale(), 'en');
    assert.equal(store[AriaLocale.LS_KEY], 'en');
    assert.equal(buttons[1]._pressed, 'true');
  } finally { uninstallFakes(); }
});

// ── dictionary ───────────────────────────────────────────────────
test('EN/ES dictionaries have full key parity and no empty values', () => {
  const enKeys = Object.keys(I18N.en);
  const esKeys = Object.keys(I18N.es);
  assert.ok(enKeys.length > 100, `expected a real dictionary, got ${enKeys.length} keys`);
  assert.deepEqual(new Set(enKeys), new Set(esKeys));
  for (const k of enKeys) {
    assert.ok(I18N.en[k] && I18N.en[k].length > 0, `empty en value for ${k}`);
    assert.ok(I18N.es[k] && I18N.es[k].length > 0, `empty es value for ${k}`);
  }
});

test('spot-check Spanish translations', () => {
  assert.equal(I18N.es['Continue'], 'Continuar');
  assert.equal(I18N.es['Send'], 'Enviar');
  assert.equal(I18N.es['Cancel'], 'Cancelar');
  assert.equal(I18N.es['Are you sure?'], '¿Estás seguro?');
  assert.equal(I18N.es['greet_morning'], 'Buenos días');
});

test('t() translates in the active locale with {var} interpolation', () => {
  installFakes({ navLang: 'es-MX' });
  try {
    AriaLocale.init({});
    assert.equal(AriaLocale.t('Continue'), 'Continuar');
    assert.equal(AriaLocale.t('Uploading {name}…', { name: 'f.png' }), 'Subiendo f.png…');
    assert.equal(AriaLocale.t('tier_plan', { plan: 'Pro' }), 'plan Pro');
    AriaLocale.setLocale('en');
    assert.equal(AriaLocale.t('Continue'), 'Continue');
    assert.equal(AriaLocale.t('tier_plan', { plan: 'Pro' }), 'Pro plan');
    // unknown key falls back to the key itself
    assert.equal(AriaLocale.t('definitely-not-a-key'), 'definitely-not-a-key');
  } finally { uninstallFakes(); }
});
