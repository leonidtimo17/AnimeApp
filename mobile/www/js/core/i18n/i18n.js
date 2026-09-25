// Локализация: один сервис на всё приложение.
//
// t("player.play") → текст на выбранном языке. Ключи сгруппированы по разделам (common.*, player.*, …).
// Нет ключа в выбранном языке → русский (основной) → последняя часть ключа; пользователь никогда не видит
// undefined, null или пустую строку. Пропущенные ключи пишутся в консоль (один раз на ключ).
// Параметры: t("anime.episodes_n", {n: 12}) — {n} в тексте; множественное число — объект {one, few, many, other}.
import { createEmitter } from "../events.js";

export const FALLBACK = "ru";

/** Значение по пути "a.b.c". */
function lookup(dict, key) {
  let v = dict;
  for (const part of key.split(".")) {
    if (v == null || typeof v !== "object") return undefined;
    v = v[part];
  }
  return v;
}

function interpolate(text, params) {
  return text.replace(/\{(\w+)\}/g, (m, name) => (params && params[name] != null ? String(params[name]) : m));
}

/**
 * @param {{locales: Record<string, object>, locale?: string, storage?: {get(): string|null, set(v: string): void},
 *   onMissing?: (key: string, locale: string) => void}} o
 */
export function createI18n({ locales, locale = null, storage = null, onMissing = null }) {
  const changes = createEmitter();
  const reported = new Set();
  const plurals = new Map();
  let current = pick(locale ?? storage?.get());

  function pick(code) { return code && locales[code] ? code : FALLBACK; }

  function plural(forms, n, code) {
    if (!plurals.has(code)) {
      try { plurals.set(code, new Intl.PluralRules(code)); } catch { plurals.set(code, new Intl.PluralRules(FALLBACK)); }
    }
    return forms[plurals.get(code).select(n)] ?? forms.other ?? forms.many ?? Object.values(forms)[0];
  }

  function resolve(key, code) {
    const v = lookup(locales[code] || {}, key);
    if (typeof v === "string" && v) return v;
    if (v && typeof v === "object" && !Array.isArray(v) && ("other" in v || "one" in v)) return v;
    return undefined;
  }

  function missing(key, code) {
    const id = `${code}:${key}`;
    if (reported.has(id)) return;
    reported.add(id);
    (onMissing || ((k, c) => console.warn(`[i18n] нет перевода «${k}» для ${c}`)))(key, code);
  }

  /** Текст по ключу. */
  function t(key, params) {
    let v = resolve(key, current);
    let code = current;
    if (v === undefined) {
      // У языка с незавершённым переводом (meta.pending) недостающие ключи известны — не шумим в журнале
      if (current !== FALLBACK && !locales[current]?.meta?.pending) missing(key, current);
      v = resolve(key, FALLBACK);
      code = FALLBACK;
      if (v === undefined) {
        missing(key, FALLBACK);
        return key.split(".").pop().replace(/_/g, " ");      // понятный запасной вариант вместо undefined
      }
    }
    if (typeof v === "object") v = plural(v, Number(params?.n ?? 0), code);
    return interpolate(v, params);
  }

  return {
    t,
    get locale() { return current; },
    /** Список языков для настроек: [{code, name}]. */
    get available() { return Object.keys(locales).map((code) => ({ code, name: locales[code].meta?.name || code })); },
    /** Сменить язык: сохраняется и сразу применяется (подписчики перерисовывают интерфейс). */
    setLocale(code) {
      const next = pick(code);
      if (next === current) return;
      current = next;
      storage?.set(next);
      changes.emit(next);
    },
    has: (key, code = current) => resolve(key, code) !== undefined,
    subscribe: changes.subscribe,
  };
}

/** Ключи, которые есть в основном языке, но нет в code (для отчёта о переводе). */
export function missingKeys(locales, code) {
  const out = [];
  const walk = (node, prefix) => {
    for (const [k, v] of Object.entries(node)) {
      const key = prefix ? `${prefix}.${k}` : k;
      if (key === "meta") continue;
      if (v && typeof v === "object" && !("other" in v || "one" in v)) walk(v, key);
      else if (lookup(locales[code] || {}, key) === undefined) out.push(key);
    }
  };
  walk(locales[FALLBACK], "");
  return out;
}

/** Язык устройства → поддерживаемый язык приложения. */
export function detectLocale(languages, supported) {
  for (const lang of languages || []) {
    const base = String(lang).toLowerCase().split(/[-_]/)[0];
    if (supported.includes(base)) return base;
  }
  return FALLBACK;
}
