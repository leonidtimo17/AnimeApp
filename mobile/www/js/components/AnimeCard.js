// Карточка тайтла — одна на всё приложение: главная, каталог, поиск, расписание, «Моё», рекомендации, «Похожее».
//
// Список карточек рисуется одной вставкой разметки, а нажатия ловит один обработчик на контейнер
// (раньше — по обработчику на каждую карточку). Быстрые действия перерисовывают только свою карточку.
import * as store from "../core/state/store.js";
import { esc } from "../utils/dom.js";
import { I, fa } from "./Icons.js";
import { lazyImg } from "./LazyImage.js";
import { toast } from "./Toast.js";
import { t } from "../i18n/index.js";

/**
 * @typedef {{id:number, title:string, subtitle?:string, poster?:string|null, badge?:string|null,
 *   progress?:number|null, release?:object}} CardItem
 */

/** @param {CardItem} item */
export function cardHtml(item) {
  const e = store.entry(item.id);
  const badges = [];
  if (item.badge) badges.push(`<span class="badge">${esc(item.badge)}</span>`);
  if (e.status) badges.push(`<span class="badge green">${esc(t(`status.${e.status}`))}</span>`);
  if (e.favorite) badges.push(`<span class="badge red">${fa("heart")}</span>`);
  return `<div class="card" data-id="${item.id}">
    <div class="poster">${lazyImg(item.poster)}
      <div class="badges">${badges.join("")}</div>
      <div class="quick">
        <button data-q="fav" aria-label="${t(e.favorite ? "library.remove_favorite" : "library.add_favorite")}">${e.favorite ? `<i class="fa fav-on">${I.heart}</i>` : fa("heart", "far")}</button>
        <button data-q="plan" aria-label="${t("status.planned")}">${e.status === "planned" ? `<i class="fa plan-on">${I.bookmark}</i>` : fa("bookmark", "far")}</button>
      </div>
    </div>
    ${item.progress != null ? `<div class="bar"><i style="width:${Math.round(item.progress * 100)}%"></i></div>` : ""}
    <div class="t">${esc(item.title)}</div><div class="s">${esc(item.subtitle || "")}</div></div>`;
}

const lists = new WeakMap();   // контейнер → {items: Map(id → карточка), onOpen}

function bind(container) {
  if (lists.has(container)) return lists.get(container);
  const state = { items: new Map(), onOpen: () => {} };
  lists.set(container, state);
  container.addEventListener("click", (ev) => {
    const el = ev.target.closest(".card[data-id]");
    const item = el && state.items.get(el.dataset.id);
    if (!item) return;
    const q = ev.target.closest("[data-q]");
    if (!q) return state.onOpen(item);
    ev.stopPropagation();
    quickAction(item, q.dataset.q);
    el.outerHTML = cardHtml(item);
  });
  return state;
}

function quickAction(item, action) {
  const e = store.entry(item.id);
  if (item.release) store.remember(item.release, { poster: item.poster, subtitle: item.subtitle });
  if (action === "fav") {
    store.setFavorite(item.id, !e.favorite);
    toast(t(e.favorite ? "library.fav_removed" : "library.fav_added"));
  } else {
    store.setStatus(item.id, e.status === "planned" ? null : "planned");
    toast(t(e.status === "planned" ? "library.plan_removed" : "library.plan_added"));
  }
}

/**
 * Нарисовать карточки в контейнере (ленту .strip или сетку .grid).
 * @param {HTMLElement} container
 * @param {CardItem[]} items
 * @param {{onOpen: (item: CardItem) => void, empty?: string, append?: boolean}} opts
 */
export function renderCards(container, items, { onOpen, empty = "", append = false }) {
  if (!container) return;
  const state = bind(container);
  state.onOpen = onOpen;
  if (!append) state.items.clear();
  for (const it of items) state.items.set(String(it.id), it);
  const html = items.map(cardHtml).join("");
  if (append) container.insertAdjacentHTML("beforeend", html);
  else container.innerHTML = html || (empty ? `<div class="state muted">${esc(empty)}</div>` : "");
}

/** Сколько карточек сейчас в контейнере. */
export const cardCount = (container) => lists.get(container)?.items.size || 0;
