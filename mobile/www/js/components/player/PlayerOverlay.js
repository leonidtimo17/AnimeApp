// Состояние видео поверх плеера: загрузка, подгрузка, ошибка с кнопкой «Повторить».
// Пользователь видит понятный текст по виду ошибки; техническая причина — только в журнале разработчика.
import { t } from "../../i18n/index.js";

/**
 * @param {HTMLElement} el
 * @param {{onRetry: () => void, onOtherDub?: () => void}} o
 */
export function createPlayerOverlay(el, { onRetry, onOtherDub }) {
  el.classList.add("pl-overlay");
  el.addEventListener("click", (e) => {
    if (e.target.closest("[data-retry]")) { e.stopPropagation(); onRetry(); }
    else if (e.target.closest("[data-other-dub]")) { e.stopPropagation(); onOtherDub?.(); }
  });
  let shown = null;

  return {
    /** state — из player-state.js: {status, error}. */
    render(state) {
      const key = state.status === "error" ? `error:${state.error?.kind}` : state.status;
      if (key === shown) return;
      shown = key;
      if (state.status === "loading" || state.status === "buffering") {
        el.hidden = false;
        el.innerHTML = `<div class="spinner" aria-hidden="true"></div>
          <div class="pl-ov-text" role="status">${t(state.status === "loading" ? "player.loading" : "player.buffering")}</div>`;
      } else if (state.status === "error") {
        const kind = state.error?.kind || "playback";
        el.hidden = false;
        el.innerHTML = `<div class="pl-error" role="alert"><b>${t(`player.errors.${kind}`)}</b>
          <div class="pl-error-actions"><button class="btn primary" data-retry>${t("common.retry")}</button>
          ${kind === "no_source" && onOtherDub ? `<button class="btn" data-other-dub>${t("player.other_translation")}</button>` : ""}</div></div>`;
      } else {
        el.hidden = true;
        el.innerHTML = "";
      }
    },
  };
}
