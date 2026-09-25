// Мелкие помощники для DOM: экранирование, сборка разметки пачкой, отложенный вызов.

/** Экранирование текста для вставки в HTML. */
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** Разметка → узлы одним фрагментом (одна вставка в документ вместо десятков). */
export function fragment(html) {
  const t = document.createElement("template");
  t.innerHTML = html;
  return t.content;
}

/** Функция, которая срабатывает через ms после последнего вызова (поиск, пока печатают). */
export function debounce(fn, ms) {
  let timer = null;
  const wrapped = (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
  wrapped.cancel = () => clearTimeout(timer);
  return wrapped;
}

/**
 * Подписка на событие, которую можно снять: listen(el, "click", fn) → off().
 * Все обработчики страницы собираются в один список и снимаются при уходе с неё.
 */
export function listen(target, type, fn, opts) {
  target.addEventListener(type, fn, opts);
  return () => target.removeEventListener(type, fn, opts);
}
