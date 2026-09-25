// Отчёт о переводе: какие ключи из ru.js ещё не переведены на язык.
//   node mobile/tools/i18n-report.mjs sah        — список ключей
//   node mobile/tools/i18n-report.mjs sah --json — заготовка для переводчика (ключ → русский текст)
import { missingKeys } from "../www/js/core/i18n/i18n.js";
import en from "../www/js/i18n/locales/en.js";
import ru from "../www/js/i18n/locales/ru.js";
import sah from "../www/js/i18n/locales/sah.js";

const locales = { ru, sah, en };
const code = process.argv[2] || "sah";
const keys = missingKeys(locales, code);
const get = (obj, key) => key.split(".").reduce((v, k) => v?.[k], obj);
if (process.argv.includes("--json")) {
  console.log(JSON.stringify(Object.fromEntries(keys.map((k) => [k, get(ru, k)])), null, 2));
} else {
  console.log(`${code}: не переведено ${keys.length} ключей`);
  for (const k of keys) console.log(`  ${k}`);
}
