// Горячие клавиши для планшета с клавиатурой — как на ПК. Буквы берём по физической клавише (e.code),
// поэтому работают и в русской раскладке. Кнопочные действия нажимают те же кнопки, что и пальцем.
import { sheetOpen } from "../../components/Sheet.js";
import { t } from "../../i18n/index.js";

/**
 * extra: {seek(сек), volume(шаг), mute(), skip(), speed?(±1), percent(0..0.9), osd(text, ms), isFs()}
 * Возвращает функцию, снимающую обработчик.
 */
export function hotkeys(root, extra) {
  const click = (a) => {
    const b = root.querySelector(`[data-a="${a}"]`);
    if (b && !b.disabled && !b.hidden) b.click();
    document.activeElement?.blur?.();  // иначе пробел ещё раз «нажмёт» кнопку в фокусе
  };
  // Esc закрывает список серий, а обсуждение — только в полноэкранном режиме (на странице оно часть страницы)
  const list = () => root.querySelector(".pl-list:not([hidden])")
    || (extra.isFs() ? root.querySelector(".pl-comments:not([hidden])") : null);
  const onKey = (e) => {
    if (e.target.closest?.("input, textarea, select") || e.ctrlKey || e.altKey || e.metaKey) return;
    if (sheetOpen()) return;  // открыто меню — Esc закроет его приложение
    const k = e.key.toLowerCase(), code = e.code;
    if (k === "escape") {
      if (!list()) return;  // закрыть плеер — это «назад» приложения
      list().hidden = true;
      e.preventDefault(); e.stopPropagation();
      return;
    }
    let done = true;
    if (k === " " || code === "KeyK" || k === "mediaplaypause") click("play");
    else if (k === "arrowleft" || code === "KeyJ") extra.seek(e.shiftKey ? -30 : -10);
    else if (k === "arrowright" || code === "KeyL") extra.seek(e.shiftKey ? 30 : 10);
    else if (k === "arrowup") extra.volume(0.1);
    else if (k === "arrowdown") extra.volume(-0.1);
    else if (code === "KeyM") extra.mute();
    else if (code === "KeyN" || k === "mediatracknext") click("next");
    else if (code === "KeyP" || k === "mediatrackprevious") click("prev");
    else if (code === "KeyS") extra.skip();
    else if (code === "KeyE") click(root.querySelector("[data-a=list]") ? "list" : "eps");
    else if (code === "KeyF") click("fs");
    else if (code === "KeyZ") click("zoom");
    else if (code === "KeyT") click("sleep");
    else if (code === "KeyC") click("comments");
    else if (code === "BracketRight" && extra.speed) extra.speed(1);
    else if (code === "BracketLeft" && extra.speed) extra.speed(-1);
    else if (/^(Digit|Numpad)\d$/.test(code)) extra.percent(+code.slice(-1) / 10);
    else if (k === "?" || code === "KeyH" || k === "f1") extra.osd(t("player.hotkeys_help"), 6000);
    else done = false;
    if (done) e.preventDefault();
  };
  document.addEventListener("keydown", onKey, true);
  return () => document.removeEventListener("keydown", onKey, true);
}
