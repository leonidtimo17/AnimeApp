// Жесты плеера: свайп вниз — закрыть, два пальца — масштаб «весь кадр / заполнить экран».
import * as store from "../../core/state/store.js";

/**
 * Масштаб картинки: «вписать» (видно весь кадр) или «заполнить экран» (края обрезаются). Возвращает apply(fill).
 */
export function zoomer(root, target, isFrame) {
  return (fill) => {
    store.setSetting("zoomFill", fill);
    root.classList.toggle("zoom-fill", fill);
    if (!isFrame) { target.style.objectFit = fill ? "cover" : "contain"; return; }
    // Kodik — внутрь iframe не залезть, поэтому увеличиваем сам iframe так, чтобы кадр 16:9 закрыл экран
    const w = root.clientWidth, h = root.clientHeight;
    const vw = Math.min(w, (h * 16) / 9), vh = (vw * 9) / 16;
    target.style.transform = fill && vw && vh ? `scale(${Math.max(w / vw, h / vh).toFixed(3)})` : "";
  };
}

/** Жест двумя пальцами: развести — заполнить экран, свести — вписать. */
export function pinch(el, onZoom) {
  let d0 = 0;
  const dist = (t) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
  el.addEventListener("touchstart", (e) => { if (e.touches.length === 2) d0 = dist(e.touches); }, { passive: true });
  el.addEventListener("touchmove", (e) => {
    if (!d0 || e.touches.length !== 2) return;
    const r = dist(e.touches) / d0;
    if (r > 1.15 || r < 0.87) { onZoom(r > 1); d0 = 0; }
  }, { passive: true });
  el.addEventListener("touchend", () => (d0 = 0));
}

/**
 * Закрытие плеера свайпом сверху вниз (как в YouTube). handle — за что тянуть; close() — закрыть.
 * Возвращает функцию, которая говорит, был ли только что свайп (чтобы не срабатывал тап).
 */
export function swipeToClose(root, handle, close) {
  let start = null, dy = 0, lastSwipe = 0;
  const reset = (animate) => {
    root.style.transition = animate ? "transform .2s, opacity .2s" : "";
    root.style.transform = "";
    root.style.opacity = "";
  };
  handle.addEventListener("touchstart", (e) => {
    if (e.touches.length !== 1) return;
    start = { x: e.touches[0].clientX, y: e.touches[0].clientY };
    dy = 0;
    root.style.transition = "";
  }, { passive: true });
  handle.addEventListener("touchmove", (e) => {
    if (!start) return;
    if (e.touches.length > 1) { start = null; reset(true); return; }
    const dx = e.touches[0].clientX - start.x;
    dy = e.touches[0].clientY - start.y;
    if (dy <= 10 || Math.abs(dx) > dy) { if (dy <= 0) root.style.transform = ""; return; }
    root.style.transform = `translateY(${dy}px)`;
    root.style.opacity = String(Math.max(0.35, 1 - dy / (root.clientHeight * 1.2)));
  }, { passive: true });
  handle.addEventListener("touchend", () => {
    if (!start) return;
    start = null;
    if (dy > 12) lastSwipe = Date.now();
    if (dy > Math.min(180, root.clientHeight * 0.25) && root.classList.contains("fs")) {
      reset(true);
      close();
    } else if (dy > Math.min(180, root.clientHeight * 0.25)) {
      root.style.transition = "transform .2s, opacity .2s";
      root.style.transform = "translateY(100%)";
      root.style.opacity = "0";
      setTimeout(() => { reset(false); close(); }, 200);
    } else {
      reset(true);
    }
  });
  handle.addEventListener("touchcancel", () => { start = null; reset(true); });
  return () => Date.now() - lastSwipe < 400;
}
