// «Моё»: списки по статусам, избранное, история, очистка кэша, правовые документы.
import * as persistent from "../core/cache/persistent.js";
import { clearMemory } from "../core/api/http.js";
import * as store from "../core/state/store.js";
import { renderCards } from "../components/AnimeCard.js";
import { fa } from "../components/Icons.js";
import { lazyImg } from "../components/LazyImage.js";
import { toast } from "../components/Toast.js";
import { esc } from "../utils/dom.js";
import { itemFromStored, openAnime } from "../app/items.js";
import { showDoc } from "../features/legal/legal.js";
import { play } from "../features/player/launch.js";
import { t } from "../i18n/index.js";

function renderHistory(lb, nav) {
  const rows = store.history();
  lb.innerHTML = (rows.length ? `<div class="right"><button class="btn small" id="clr">${fa("trash")} ${t("history.clear")}</button></div>`
    : `<p class="muted">${t("history.empty")}</p>`)
    + rows.map((r, i) => `<div class="hist" data-i="${i}"><div class="poster">${lazyImg(r.anime.poster)}</div>
        <div class="grow"><b>${esc(r.anime.title)}</b><div class="muted">${esc(t("player.episode_n", { n: r.key }))} · ${r.watched ? t("history.watched") : t("history.minutes_of", { n: Math.floor(r.pos / 60), total: Math.floor(r.dur / 60) })}</div>
        <div class="bar"><i style="width:${r.watched ? 100 : Math.round((r.pos / (r.dur || 1)) * 100)}%"></i></div></div></div>`).join("");
  lb.onclick = (e) => {
    if (e.target.closest("#clr")) { store.clearHistory(); nav.replace("history"); return; }
    const row = e.target.closest("[data-i]");
    if (row) play(rows[+row.dataset.i].anime.id, rows[+row.dataset.i].key);
  };
}

export default function library(view, tab = "watching", nav) {
  const tabsDef = [...Object.keys(store.STATUSES).map((k) => [k, t(`status.${k}`)]), ["favorite", t("library.favorite")], ["history", t("history.title")]];
  const s = store.stats();
  view.innerHTML = `<div class="row-head"><h1>${t("library.title")}</h1>
      <button class="btn small" id="settings">${fa("gear")} ${t("settings.title")}</button></div>
    <p class="muted">${t("library.stats", { n: s.episodes, h: s.hours.toFixed(1) })}</p>
    <div class="tabs2">${tabsDef.map(([k, n]) => `<button class="chip${k === tab ? " on" : ""}" data-t="${k}">${n}</button>`).join("")}</div><div id="lb"></div>`;
  view.querySelector("#settings").onclick = () => nav.show("settings");
  view.querySelector(".tabs2").onclick = (e) => { const b = e.target.closest("[data-t]"); if (b) nav.replace(b.dataset.t); };
  const lb = view.querySelector("#lb");
  if (tab === "history") return renderHistory(lb, nav);
  lb.innerHTML = `<div class="grid" id="grid"></div>
    <div class="tools"><button class="btn small" id="cc">${fa("trash")} ${t("library.clear_cache")}</button>
      <button class="btn small" id="lt">${t("legal.terms")}</button>
      <button class="btn small" id="lp">${t("legal.privacy")}</button></div>`;
  renderCards(lb.querySelector("#grid"), store.library(tab).map((a) => itemFromStored(a)),
    { onOpen: (it) => openAnime(nav, it), empty: t("library.empty") });
  lb.querySelector("#cc").onclick = async () => {
    clearMemory();
    await persistent.clear();
    toast(t("library.cache_cleared"));
  };
  lb.querySelector("#lt").onclick = () => showDoc("terms");
  lb.querySelector("#lp").onclick = () => showDoc("privacy");
}
