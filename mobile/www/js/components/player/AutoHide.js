// Автоскрытие панелей плеера: видны delay мс после последнего касания/движения, пока canHide() разрешает.

export function createAutoHide(root, { canHide, delay = 5000 }) {
  let timer = null;
  const hideLater = () => { clearTimeout(timer); timer = setTimeout(tryHide, delay); };
  function tryHide() {
    if (!canHide()) return hideLater();
    root.classList.add("pl-hidden");
  }
  return {
    /** Показать панели и спрятать их позже. */
    poke() { root.classList.remove("pl-hidden"); hideLater(); },
    hideNow() { clearTimeout(timer); root.classList.add("pl-hidden"); },
    get hidden() { return root.classList.contains("pl-hidden"); },
    destroy() { clearTimeout(timer); },
  };
}
