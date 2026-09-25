import "./setup.mjs";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { createI18n, detectLocale, missingKeys } from "../www/js/core/i18n/i18n.js";
import en from "../www/js/i18n/locales/en.js";
import ru from "../www/js/i18n/locales/ru.js";
import sah from "../www/js/i18n/locales/sah.js";

const LOCALES = { ru, sah, en };
const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "www");

const demo = {
  ru: { meta: { name: "Русский" }, player: { play: "Смотреть", only_ru: "Только по-русски" },
    dates: { minutes_ago: { one: "{n} минуту назад", few: "{n} минуты назад", many: "{n} минут назад", other: "{n} минуты" } } },
  sah: { meta: { name: "Саха тыла" }, player: { play: "Көр" } },
  en: { meta: { name: "English" }, player: { play: "Play" }, dates: { minutes_ago: { one: "{n} minute ago", other: "{n} minutes ago" } } },
};

test("перевод по ключу на трёх языках и смена языка без перезапуска", () => {
  let saved = null;
  const i18n = createI18n({ locales: demo, locale: "ru", storage: { get: () => saved, set: (v) => { saved = v; } }, onMissing: () => {} });
  const seen = [];
  i18n.subscribe((code) => seen.push(code));
  assert.equal(i18n.t("player.play"), "Смотреть");
  i18n.setLocale("sah");
  assert.equal(i18n.t("player.play"), "Көр");
  i18n.setLocale("en");
  assert.equal(i18n.t("player.play"), "Play");
  assert.deepEqual(seen, ["sah", "en"], "интерфейс получает событие смены языка");
  assert.equal(saved, "en", "выбор сохраняется");
  // «перезапуск»: новый сервис читает сохранённый язык
  const again = createI18n({ locales: demo, storage: { get: () => saved, set: () => {} } });
  assert.equal(again.locale, "en");
  assert.deepEqual(again.available.map((l) => l.name), ["Русский", "Саха тыла", "English"]);
});

test("запасной язык и понятный текст вместо undefined; пропуски пишутся в журнал один раз", () => {
  const missing = [];
  const i18n = createI18n({ locales: demo, locale: "sah", onMissing: (k, c) => missing.push(`${c}:${k}`) });
  assert.equal(i18n.t("player.only_ru"), "Только по-русски", "нет перевода — русский");
  const nowhere = i18n.t("player.no_such_key");
  assert.ok(nowhere && nowhere !== "undefined" && nowhere !== "null");
  assert.equal(nowhere, "no such key");
  i18n.t("player.only_ru");
  assert.deepEqual(missing, ["sah:player.only_ru", "sah:player.no_such_key", "ru:player.no_such_key"]);
  i18n.setLocale("xx");
  assert.equal(i18n.locale, "ru", "неизвестный язык → русский");
});

test("язык с незавершённым переводом не шумит в журнале", () => {
  const missing = [];
  const i18n = createI18n({ locales: LOCALES, locale: "sah", onMissing: (k) => missing.push(k) });
  assert.equal(i18n.t("common.retry"), "Повторить");
  assert.equal(i18n.t("navigation.home"), "Сүрүн сирэй");
  assert.deepEqual(missing, []);
});

test("параметры и множественное число", () => {
  const i18n = createI18n({ locales: demo, locale: "ru" });
  assert.equal(i18n.t("dates.minutes_ago", { n: 1 }), "1 минуту назад");
  assert.equal(i18n.t("dates.minutes_ago", { n: 3 }), "3 минуты назад");
  assert.equal(i18n.t("dates.minutes_ago", { n: 5 }), "5 минут назад");
  i18n.setLocale("en");
  assert.equal(i18n.t("dates.minutes_ago", { n: 1 }), "1 minute ago");
  assert.equal(i18n.t("dates.minutes_ago", { n: 7 }), "7 minutes ago");
});

test("язык устройства", () => {
  assert.equal(detectLocale(["sah-RU", "ru"], ["ru", "sah", "en"]), "sah");
  assert.equal(detectLocale(["en-US"], ["ru", "sah", "en"]), "en");
  assert.equal(detectLocale(["de-DE"], ["ru", "sah", "en"]), "ru");
});

// ------------------------------------------------------------------ настоящие словари
const placeholders = (s) => [...String(s).matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(",");
function flat(obj, prefix = "", out = {}) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (key === "meta") continue;
    if (v && typeof v === "object" && !("other" in v || "one" in v)) flat(v, key, out);
    else out[key] = typeof v === "object" ? (v.other ?? v.one) : v;
  }
  return out;
}

test("английский переведён полностью, у саха нет лишних ключей, параметры совпадают", () => {
  assert.deepEqual(missingKeys(LOCALES, "en"), []);
  const ruFlat = flat(ru);
  for (const [code, dict] of Object.entries({ en, sah })) {
    for (const [key, text] of Object.entries(flat(dict))) {
      assert.ok(key in ruFlat, `${code}: лишний ключ ${key}`);
      assert.equal(placeholders(text), placeholders(ruFlat[key]), `${code}: параметры в ${key}`);
      assert.ok(String(text).trim(), `${code}: пустой перевод ${key}`);
    }
  }
  assert.ok(sah.meta.pending, "неполный перевод саха помечен");
  assert.ok(missingKeys(LOCALES, "sah").length > 0);
});

test("все ключи из кода есть в русском словаре", () => {
  const ruFlat = flat(ru);
  const families = ["status.", "player.errors.", "catalog.sorts.", "catalog.types.", "catalog.statuses.", "catalog.seasons.",
    "anime.kinds.", "shikimori.statuses.", "recs.ai_errors."];
  const known = new Set(["common", "navigation", "errors", "dates", "status", "home", "schedule", "search", "catalog", "anime",
    "dubs", "library", "history", "player", "sleep", "comments", "recs", "shikimori", "network", "settings", "legal"]);
  const files = [];
  (function walk(d) { for (const f of fs.readdirSync(d)) { const p = path.join(d, f); if (fs.statSync(p).isDirectory()) walk(p); else if (/\.(js|html)$/.test(p) && !p.includes("locales") && !p.includes("vendor")) files.push(p); } })(ROOT);
  const missing = [];
  for (const f of files) {
    const src = fs.readFileSync(f, "utf8");
    for (const m of src.matchAll(/["'`]([a-z_]+(?:\.[a-z_0-9]+)+)["'`]/g)) {
      const key = m[1];
      if (!known.has(key.split(".")[0]) || key.endsWith(".js") || families.some((p) => key === p.slice(0, -1))) continue;
      if (!(key in ruFlat)) missing.push(`${path.relative(ROOT, f)}: ${key}`);
    }
  }
  assert.deepEqual(missing, []);
  // Динамические ключи: каждой семье — все значения
  for (const s of ["watching", "planned", "completed", "postponed", "dropped"]) assert.ok(`status.${s}` in ruFlat);
  for (const k of ["network", "offline", "source", "no_source", "playback"]) assert.ok(`player.errors.${k}` in ruFlat);
  for (const k of ["format", "unclear", "unavailable"]) assert.ok(`recs.ai_errors.${k}` in ruFlat);
});

test("настоящий сервис приложения: язык сохраняется и восстанавливается после перезапуска", async () => {
  const { i18n, t } = await import("../www/js/i18n/index.js");
  const store = await import("../www/js/core/state/store.js");
  assert.equal(i18n.locale, "ru");
  i18n.setLocale("sah");
  assert.equal(store.setting("language"), "sah");
  assert.equal(t("common.retry"), "Повторить", "непереведённое на саха — по-русски");
  i18n.setLocale("en");
  assert.equal(t("common.retry"), "Retry");
  store.flush();
  assert.equal(JSON.parse(localStorage.getItem("animeapp:v1")).settings.language, "en");
  i18n.setLocale("ru");
});
