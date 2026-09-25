// Единые состояния экрана: загрузка (скелетон), пусто, ошибка (с кнопкой «Повторить»), нет сети.
import { AuthenticationError, NetworkError, NoSourceError, isAbort } from "../core/errors.js";
import { t } from "../i18n/index.js";
import { esc } from "../utils/dom.js";
import { fa } from "./Icons.js";

/** Заглушки карточек, пока лента грузится — без скачка вёрстки, когда придут данные. */
export const skeletonCards = (n = 8) => Array.from({ length: n }, () =>
  `<div class="card skeleton"><div class="poster"></div><div class="t"></div><div class="s"></div></div>`).join("");

export const loading = (text = t("common.loading")) => `<div class="state muted" role="status">${esc(text)}</div>`;

export const empty = (text) => `<div class="state muted">${esc(text)}</div>`;

/**
 * Понятный пользователю текст ошибки по её типу. Техническая причина — только в журнале разработчика.
 * what — ключ перевода «что не получилось» (по умолчанию errors.load_failed).
 */
export function friendlyError(err, what = "errors.load_failed") {
  if (err?.message) console.warn("[AnimeApp]", t(what), err);
  if (err instanceof NetworkError) return t("errors.offline_hint");
  if (err instanceof NoSourceError) return t("player.errors.no_source");
  if (err instanceof AuthenticationError) return t("errors.auth");
  return t(what);
}

/** Ошибка: понятный текст и кнопка «Повторить» (data-retry — обработчик вешает страница). */
export function errorState(err, what) {
  const offline = err instanceof NetworkError;
  return `<div class="state error" role="alert">${offline ? fa("wifi") + " " : ""}<span>${esc(friendlyError(err, what))}</span>
    <button class="btn small" data-retry>${t("common.retry")}</button></div>`;
}

/**
 * Показать ошибку в контейнере; retry — повторить загрузку. Отменённые запросы (ушли со страницы) не показываем.
 */
export function showError(el, err, retry, what) {
  if (!el || isAbort(err)) return;
  el.innerHTML = errorState(err, what);
  el.querySelector("[data-retry]").onclick = retry;
}
