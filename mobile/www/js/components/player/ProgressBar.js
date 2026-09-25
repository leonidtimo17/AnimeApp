// Полоса перемотки: касание или мышь, перетаскивание, подгруженная часть, отметки заставки и титров.
// Одна на оба плеера (встроенный и Kodik). Обработчики висят на самом элементе и уходят вместе с ним.
import { t } from "../../i18n/index.js";
import { fmtTime } from "../../utils/format.js";

/**
 * @param {HTMLElement} el
 * @param {{onSeek: (sec: number) => void, onScrub?: (sec: number) => void}} o
 */
export function createProgressBar(el, { onSeek, onScrub }) {
  el.classList.add("seek");
  el.setAttribute("role", "slider");
  el.setAttribute("aria-label", t("player.progress"));
  el.innerHTML = `<div class="tr"></div><div class="buf"></div><div class="marks"></div><div class="pl"></div><div class="kn"></div>`;
  const $ = (s) => el.querySelector(s);
  let dur = 0, dragging = false;
  const frac = (x) => { const r = el.getBoundingClientRect(); return Math.min(1, Math.max(0, (x - r.left) / r.width)); };
  const paint = (f) => { $(".pl").style.width = `${f * 100}%`; $(".kn").style.left = `${f * 100}%`; };

  el.addEventListener("pointerdown", (e) => {
    if (!dur) return;
    dragging = true;
    el.setPointerCapture(e.pointerId);
    paint(frac(e.clientX));
    onScrub?.(frac(e.clientX) * dur);
  });
  el.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    paint(frac(e.clientX));
    onScrub?.(frac(e.clientX) * dur);
  });
  const end = (e) => {
    if (!dragging) return;
    dragging = false;
    onSeek(frac(e.clientX) * dur);
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", () => { dragging = false; });

  return {
    get dragging() { return dragging; },
    /** Позиция, длительность и конец подгруженного куска (секунды). */
    set(pos, duration, buffered = 0) {
      dur = duration || 0;
      if (!dragging && dur) paint(Math.min(1, pos / dur));
      if (dur && buffered) $(".buf").style.width = `${Math.min(1, buffered / dur) * 100}%`;
      el.setAttribute("aria-valuetext", `${fmtTime(pos)} / ${fmtTime(dur)}`);
    },
    /** Отметки [{start, stop}] (заставка, титры). */
    marks(list) {
      $(".marks").innerHTML = !dur ? "" : list.filter((m) => m?.stop && m.start != null)
        .map((m) => `<div class="mk" style="left:${(m.start / dur) * 100}%;width:${((m.stop - m.start) / dur) * 100}%"></div>`).join("");
    },
  };
}
