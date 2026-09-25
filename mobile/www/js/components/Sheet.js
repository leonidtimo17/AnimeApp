// Нижнее меню (как в мобильных приложениях). groups: [{title, items: [{label, on, action, hint}]}]
import { esc } from "../utils/dom.js";
import { fa } from "./Icons.js";

export function sheet(groups) {
  const el = document.getElementById("sheet");
  const actions = [];
  const html = groups.map((g) => (g.title ? `<div class="ttl">${esc(g.title)}</div>` : "") + g.items.map((it) => {
    actions.push(it.action);
    return `<div class="it${it.on ? " on" : ""}" data-i="${actions.length - 1}"><span>${esc(it.label)}</span>
      <span class="muted">${it.on ? fa("check") : esc(it.hint || "")}</span></div>`;
  }).join("")).join("");
  el.innerHTML = `<div class="box">${html}</div>`;
  el.hidden = false;
  el.onclick = (e) => {
    const it = e.target.closest(".it");
    el.hidden = true;
    if (it) actions[+it.dataset.i]?.();
  };
}

/** Закрыть меню; true — если оно было открыто. */
export function closeSheet() {
  const el = document.getElementById("sheet");
  if (el.hidden) return false;
  el.hidden = true;
  return true;
}

export const sheetOpen = () => !document.getElementById("sheet").hidden;
