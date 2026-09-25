// Короткая подсказка по центру видео («+10 с», «Заставка пропущена»).

export function createOsd(el) {
  let timer = null;
  el.setAttribute("role", "status");
  return {
    show(text, ms = 1200) {
      el.textContent = text;
      el.hidden = false;
      clearTimeout(timer);
      timer = setTimeout(() => (el.hidden = true), ms);
    },
    hide() { clearTimeout(timer); el.hidden = true; },
    destroy() { clearTimeout(timer); },
  };
}
