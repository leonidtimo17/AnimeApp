// Каталог: фильтры (жанры, тип, статус, сезон, годы) и сортировка. Фильтры запоминаются.
import * as api from "../core/api/anilibria.js";
import * as store from "../core/state/store.js";
import { renderCards } from "../components/AnimeCard.js";
import { fa } from "../components/Icons.js";
import { showError, skeletonCards } from "../components/StateView.js";
import { esc } from "../utils/dom.js";
import { itemFromRelease, openAnime } from "../app/items.js";
import { t } from "../i18n/index.js";

const TYPES = ["TV", "ONA", "WEB", "OVA", "MOVIE", "SPECIAL"];                  // подписи — catalog.types.*
const SORTS = ["RATING_DESC", "FRESH_AT_DESC", "YEAR_DESC", "YEAR_ASC"];       // catalog.sorts.*
const SEASONS = ["winter", "spring", "summer", "autumn"];                       // catalog.seasons.*
const DEFAULTS = { sorting: "RATING_DESC", types: [], genres: [], ongoing: null, season: null, yearFrom: null, yearTo: null };

const chip = (on, text, attrs) => `<button class="chip${on ? " on" : ""}" ${attrs}>${esc(text)}</button>`;

export default function catalog(view, _arg, nav) {
  const f = { ...DEFAULTS, ...store.setting("catalogFilters", {}) };
  view.innerHTML = `<div class="row-head"><h1>${t("catalog.title")}</h1><button class="btn small" id="tog" aria-expanded="false">${fa("filter")} ${t("catalog.filters")}</button></div>
    <div class="filters" id="fl" hidden></div><p class="muted" id="cnt"></p><div class="grid" id="res"></div>
    <div class="more-row"><button class="btn" id="more" hidden>${t("common.show_more")}</button></div>`;
  const $ = (s) => view.querySelector(s);
  const fl = $("#fl"), res = $("#res"), cnt = $("#cnt"), more = $("#more");
  $("#tog").onclick = (e) => { fl.hidden = !fl.hidden; e.currentTarget.setAttribute("aria-expanded", String(!fl.hidden)); };
  let page = 0, pages = 1, genres = [], ctrl = null;

  function renderFilters() {
    fl.innerHTML = `
      <div class="label">${t("catalog.sorting")}</div><select class="select" id="sort" aria-label="${t("catalog.sorting")}">${SORTS.map((v) => `<option value="${v}" ${f.sorting === v ? "selected" : ""}>${t(`catalog.sorts.${v}`)}</option>`).join("")}</select>
      <div class="label">${t("catalog.status")}</div><div class="chips">${[[null, "all"], [true, "ongoing"], [false, "finished"]].map(([v, n]) => chip(f.ongoing === v, t(`catalog.statuses.${n}`), `data-st="${v}"`)).join("")}</div>
      <div class="label">${t("catalog.type")}</div><div class="chips">${TYPES.map((v) => chip(f.types.includes(v), t(`catalog.types.${v}`), `data-ty="${v}"`)).join("")}</div>
      <div class="label">${t("catalog.season")}</div><div class="chips">${[null, ...SEASONS].map((v) => chip(f.season === v, t(`catalog.seasons.${v || "any"}`), `data-se="${v}"`)).join("")}</div>
      <div class="label">${t("catalog.years")}</div><div class="chips"><input class="select year" id="yf" type="number" inputmode="numeric" placeholder="${t("catalog.year_from")}" aria-label="${t("catalog.year_from")}" value="${f.yearFrom || ""}">
        <input class="select year" id="yt" type="number" inputmode="numeric" placeholder="${t("catalog.year_to")}" aria-label="${t("catalog.year_to")}" value="${f.yearTo || ""}"></div>
      <div class="label">${t("catalog.genres")} ${f.genres.length > 1 ? t("catalog.genres_all") : ""}</div><div class="chips">${genres.map((g) => chip(f.genres.includes(g.id), g.name, `data-ge="${g.id}"`)).join("")}</div>
      <div class="filters-foot"><button class="btn small" id="reset">${t("common.reset")}</button></div>`;
  }
  function changed() { store.setSetting("catalogFilters", f); renderFilters(); reload(); }
  fl.onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.id === "reset") { Object.assign(f, { ...DEFAULTS, sorting: f.sorting }); return changed(); }
    if ("st" in b.dataset) f.ongoing = b.dataset.st === "null" ? null : b.dataset.st === "true";
    if ("se" in b.dataset) f.season = b.dataset.se === "null" ? null : b.dataset.se;
    if ("ty" in b.dataset) f.types = f.types.includes(b.dataset.ty) ? f.types.filter((x) => x !== b.dataset.ty) : [...f.types, b.dataset.ty];
    if ("ge" in b.dataset) { const g = +b.dataset.ge; f.genres = f.genres.includes(g) ? f.genres.filter((x) => x !== g) : [...f.genres, g]; }
    changed();
  };
  fl.onchange = (e) => {
    if (e.target.id === "sort") f.sorting = e.target.value;
    if (e.target.id === "yf") f.yearFrom = +e.target.value || null;
    if (e.target.id === "yt") f.yearTo = +e.target.value || null;
    changed();
  };

  async function load() {
    const signal = ctrl.signal;
    more.hidden = true;
    try {
      const d = await api.catalog({ ...f, page: page + 1 }, signal);
      if (signal.aborted) return;
      page = d.meta.pagination.current_page; pages = d.meta.pagination.total_pages;
      cnt.textContent = t("search.found", { n: d.meta.pagination.total });
      renderCards(res, d.data.map(itemFromRelease), { onOpen: (it) => openAnime(nav, it), append: page > 1,
        empty: t("catalog.nothing") });
      more.hidden = page >= pages;
    } catch (e) { if (!signal.aborted) showError(page ? cnt : res, e, load); }
  }
  function reload() {
    ctrl?.abort();                                     // ответы по старым фильтрам не нужны
    ctrl = new AbortController();
    nav.signal.addEventListener("abort", () => ctrl.abort(), { once: true });
    page = 0;
    res.innerHTML = skeletonCards(12);
    load();
  }
  more.onclick = load;
  api.genres().then((g) => { genres = g.sort((a, b) => a.name.localeCompare(b.name)); if (nav.active()) renderFilters(); })
    .catch(() => nav.active() && renderFilters());
  reload();
}
