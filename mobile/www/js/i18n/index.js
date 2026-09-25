// Язык приложения: единственный экземпляр сервиса локализации.
// t("player.play") — текст на выбранном языке; setLocale("sah") — сменить язык (сохраняется, интерфейс
// перерисовывается без перезапуска); translateDom(root) — подписать статичную разметку с атрибутами data-i18n.
import { createI18n, detectLocale } from "../core/i18n/i18n.js";
import * as store from "../core/state/store.js";
import en from "./locales/en.js";
import ru from "./locales/ru.js";
import sah from "./locales/sah.js";

const LOCALES = { ru, sah, en };
const SETTING = "language";

export const i18n = createI18n({
  locales: LOCALES,
  locale: store.setting(SETTING, null) ?? detectLocale(globalThis.navigator?.languages, Object.keys(LOCALES)),
  storage: { get: () => store.setting(SETTING, null), set: (v) => store.setSetting(SETTING, v) },
});

/** Текст по ключу (см. i18n/locales/ru.js). */
export const t = (key, params) => i18n.t(key, params);

/** Подписать элементы с data-i18n (текст), data-i18n-title, data-i18n-aria, data-i18n-placeholder. */
export function translateDom(root = globalThis.document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
  root.querySelectorAll("[data-i18n-aria]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.i18nAria)); });
  root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  if (root.documentElement) root.documentElement.lang = i18n.locale;
}

// ------------------------------------------------------------------ даты и время по языку
// Для саха в браузерах обычно нет своих названий месяцев — используем русский формат дат (запасной язык).
const DATE_LOCALE = { ru: "ru-RU", sah: "ru-RU", en: "en-GB" };
const dateLocale = () => DATE_LOCALE[i18n.locale] || "ru-RU";

/** «3 окт., пт · 18:30» (время — если есть). */
export function formatDate(d, withTime = true) {
  if (!d) return t("dates.unknown");
  let s = new Intl.DateTimeFormat(dateLocale(), { day: "numeric", month: "short", weekday: "short" }).format(d);
  if (withTime && (d.getHours() || d.getMinutes())) {
    s += ` · ${new Intl.DateTimeFormat(dateLocale(), { hour: "2-digit", minute: "2-digit" }).format(d)}`;
  }
  return s;
}

/** «3 окт.» */
export const formatDay = (d) => new Intl.DateTimeFormat(dateLocale(), { day: "numeric", month: "short" }).format(d);

/** Название дня недели (1 = понедельник). */
export function weekdayName(n) {
  const monday = new Date(2024, 0, 1);                       // 1 января 2024 — понедельник
  const name = new Intl.DateTimeFormat(dateLocale(), { weekday: "long" }).format(new Date(monday.getTime() + (n - 1) * 86400_000));
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/** «5 мин назад», «3 ч назад», «2 дн назад» или дата. */
export function formatAgo(iso, now = Date.now()) {
  const s = (now - new Date(iso)) / 1000;
  if (s < 3600) return t("dates.minutes_ago", { n: Math.max(1, Math.round(s / 60)) });
  if (s < 86400) return t("dates.hours_ago", { n: Math.round(s / 3600) });
  if (s < 86400 * 30) return t("dates.days_ago", { n: Math.round(s / 86400) });
  return new Date(iso).toLocaleDateString(dateLocale());
}
