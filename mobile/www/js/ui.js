// Общие элементы интерфейса: экранирование, иконки, нижнее меню, всплывающие сообщения, карточки.
import * as store from "./store.js";

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const I = {
  play: "&#xf04b;", pause: "&#xf04c;", back: "&#xf060;", prev: "&#xf048;", next: "&#xf051;", fwd: "&#xf04e;",
  rewind: "&#xf2ea;", forward: "&#xf2f9;", list: "&#xf0ca;", expand: "&#xf065;", compress: "&#xf066;",
  heart: "&#xf004;", bookmark: "&#xf02e;", star: "&#xf005;", check: "&#xf00c;", circleCheck: "&#xf058;",
  plus: "&#x2b;", mic: "&#xf130;", layers: "&#xf5fd;", gear: "&#xf013;", calendar: "&#xf073;", magic: "&#xe2ca;",
  refresh: "&#xf2f9;", trash: "&#xf2ed;", filter: "&#xf0b0;", history: "&#xf1da;",
};
export const fa = (k, cls = "fa") => `<i class="${cls}">${I[k]}</i>`;

let toastTimer;
export function toast(text, ms = 2600) {
  const el = document.getElementById("toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), ms);
}

/** Нижнее меню. groups: [{title, items: [{label, on, action, hint}]}] */
export function sheet(groups) {
  const el = document.getElementById("sheet");
  const box = document.createElement("div");
  box.className = "box";
  const actions = [];
  box.innerHTML = groups.map((g) => (g.title ? `<div class="ttl">${esc(g.title)}</div>` : "") + g.items.map((it) => {
    actions.push(it.action);
    return `<div class="it${it.on ? " on" : ""}" data-i="${actions.length - 1}"><span>${esc(it.label)}</span>
      <span class="muted">${it.on ? fa("check") : esc(it.hint || "")}</span></div>`;
  }).join("")).join("");
  el.innerHTML = "";
  el.appendChild(box);
  el.hidden = false;
  el.onclick = (e) => {
    const it = e.target.closest(".it");
    el.hidden = true;
    if (it) actions[+it.dataset.i]?.();
  };
}
export const closeSheet = () => { const el = document.getElementById("sheet"); if (el.hidden) return false; el.hidden = true; return true; };

// ------------------------------------------------------------------ карточки
export function card(item, { onOpen }) {
  const e = store.entry(item.id);
  const div = document.createElement("div");
  div.className = "card";
  const badges = [];
  if (item.badge) badges.push(`<span class="badge">${esc(item.badge)}</span>`);
  if (e.status) badges.push(`<span class="badge green">${esc(store.STATUSES[e.status])}</span>`);
  if (e.favorite) badges.push(`<span class="badge red">${fa("heart")}</span>`);
  div.innerHTML = `
    <div class="poster" style="${item.poster ? `background-image:url('${esc(item.poster)}')` : ""}">
      <div class="badges">${badges.join("")}</div>
      <div class="quick">
        <button data-q="fav" aria-label="В избранное">${e.favorite ? `<i class="fa" style="color:#ff4d6d">${I.heart}</i>` : fa("heart", "far")}</button>
        <button data-q="plan" aria-label="Хочу посмотреть">${e.status === "planned" ? `<i class="fa" style="color:var(--accent)">${I.bookmark}</i>` : fa("bookmark", "far")}</button>
      </div>
    </div>
    ${item.progress != null ? `<div class="bar"><i style="width:${Math.round(item.progress * 100)}%"></i></div>` : ""}
    <div class="t">${esc(item.title)}</div><div class="s">${esc(item.subtitle || "")}</div>`;
  div.onclick = (ev) => {
    const q = ev.target.closest("[data-q]");
    if (!q) return onOpen(item);
    ev.stopPropagation();
    if (item.release) store.remember(item.release, { poster: item.poster, subtitle: item.subtitle });
    if (q.dataset.q === "fav") store.setFavorite(item.id, !e.favorite);
    else store.setStatus(item.id, e.status === "planned" ? null : "planned");
    toast(q.dataset.q === "fav" ? (e.favorite ? "Убрано из избранного" : "Добавлено в избранное")
      : (e.status === "planned" ? "Убрано из «Хочу посмотреть»" : "Добавлено в «Хочу посмотреть»"));
    div.replaceWith(card(item, { onOpen }));
  };
  return div;
}

export function fillCards(container, items, onOpen, empty = "") {
  container.innerHTML = "";
  if (!items.length && empty) container.innerHTML = `<div class="muted">${esc(empty)}</div>`;
  for (const it of items) container.appendChild(card(it, { onOpen }));
}

const MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const WD = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
export function fmtDate(d, time = true) {
  if (!d) return "дата пока неизвестна";
  let s = `${d.getDate()} ${MONTHS[d.getMonth()]}, ${WD[d.getDay()]}`;
  if (time && (d.getHours() || d.getMinutes())) s += ` · ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return s;
}
export const fmtTime = (s) => {
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
};
