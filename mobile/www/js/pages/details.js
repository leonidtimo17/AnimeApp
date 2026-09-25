// Страница тайтла: описание, рейтинги, списки, серии всех озвучек, предстоящие серии, сезоны, «Похожее».
import * as api from "../core/api/anilibria.js";
import * as store from "../core/state/store.js";
import { renderCards } from "../components/AnimeCard.js";
import { episodeTile } from "../components/EpisodeTile.js";
import { I, fa } from "../components/Icons.js";
import { lazyImg } from "../components/LazyImage.js";
import { sheet } from "../components/Sheet.js";
import { showError } from "../components/StateView.js";
import { menuGroups } from "../domain/dubs.js";
import { dubGroup, EPISODES_PAGE, progressFraction, shownEpisodes, unionEpisodes } from "../domain/episodes.js";
import { qualityName } from "../domain/quality.js";
import { title } from "../domain/titles.js";
import { upcoming } from "../domain/upcoming.js";
import { esc } from "../utils/dom.js";
import { openAnime } from "../app/items.js";
import { play } from "../features/player/launch.js";
import { formatDate as fmtDate, t } from "../i18n/index.js";
import * as src from "../services/sources.js";

const GROUP_NAMES = { anilibria: "AniLibria", animevost: "AnimeVost", kodik: "Kodik" };   // названия источников не переводятся

function heroHtml(rel, poster, e) {
  const rating = [["shikimori", "Shikimori"], ["mal", "MyAnimeList"]].filter(([k]) => rel[k]?.rating)
    .map(([k, n]) => `<span><i class="fa star">${I.star}</i> <b>${(+rel[k].rating).toFixed(2)}</b> <span class="muted">${n}</span></span>`).join(" &nbsp; ");
  const meta = [["anime.type", rel.type?.description], ["anime.year", rel.year], ["anime.episodes_total", rel.episodes_total],
    ["anime.age", rel.age_rating?.label], ["anime.status", t(rel.is_ongoing ? "anime.ongoing" : "anime.finished")]].filter(([, v]) => v);
  return `
    <div class="hero"><div class="poster">${lazyImg(poster, true)}</div>
      <div class="info"><h1>${esc(title(rel))}</h1><div class="muted">${esc([rel.name?.english, rel.name?.alternative].filter(Boolean).join(" / "))}</div>
        <div class="ratings">${rating}</div>
        <div class="meta">${meta.map(([k, v]) => `<span class="muted">${t(k)}</span><span>${esc(v)}</span>`).join("")}</div>
        <div class="chips">${(rel.genres || []).map((g) => `<span class="chip">${esc(g.name)}</span>`).join("")}</div>
        <div class="actions">
          <button class="btn primary" id="play">${fa("play")} ${t("anime.watch")}</button>
          <button class="btn" id="status">${e.status ? fa("check") + " " + t(`status.${e.status}`) : fa("plus") + " " + t("anime.add_to_list")}</button>
          <button class="btn${e.favorite ? " on" : ""}" id="fav">${e.favorite ? fa("heart") + " " + t("library.in_favorites") : fa("heart", "far") + " " + t("library.add_favorite")}</button>
        </div></div></div>
    <p class="desc">${esc(rel.description || "")}</p>
    <div class="row-head"><h2 id="epT">${t("anime.episodes")}</h2><span class="sp"></span><span class="muted" id="qnote"></span>
      <button class="btn small" id="dub">${fa("mic")} ${t("anime.dub_searching")}</button></div>
    <div class="ranges" id="ranges"></div><div class="eps" id="eps"><p class="muted">${t("anime.episodes_searching")}</p></div>
    <div id="soon"></div>
    <div id="seasons"></div>
    <div id="similar"></div>`;
}

export default async function details(view, id, nav) {
  view.innerHTML = `<button class="btn flat" id="bk">${fa("back")} ${t("common.back")}</button><div id="dt"><p class="muted" role="status">${t("common.loading")}</p></div>`;
  view.querySelector("#bk").onclick = () => nav.back();
  let rel;
  try { rel = await src.loadRelease(id, false, nav.signal); } catch (e) {
    return showError(view.querySelector("#dt"), e, () => nav.replace(id));
  }
  if (!nav.active()) return;
  const poster = api.posterUrl(rel);
  store.remember(rel, { poster, subtitle: [rel.year, rel.type?.description].filter(Boolean).join(" · ") });
  const e = store.entry(id);
  view.querySelector("#dt").innerHTML = heroHtml(rel, poster, e);
  const $ = (s) => view.querySelector(s);
  const open = (item) => openAnime(nav, item);

  // Похожие тайтлы по версии Shikimori
  if (rel.shikimori?.id) {
    src.similar(rel.shikimori.id, nav.signal).then((items) => {
      if (!nav.active() || !items.length) return;
      $("#similar").innerHTML = `<h2>${t("anime.similar")}</h2><div class="grid"></div>`;
      renderCards($("#similar .grid"), items.slice(0, 18), { onOpen: open });
    }).catch((err) => { if (err?.name !== "AbortError") console.warn("[AnimeApp] «Похожее»", err); });
  }
  $("#status").onclick = () => sheet([{ title: t("anime.list"), items: [...Object.keys(store.STATUSES).map((k) => ({ label: t(`status.${k}`), on: e.status === k,
    action: () => { store.setStatus(id, k); nav.replace(id); } })), ...(e.status ? [{ label: t("anime.remove_from_lists"), action: () => { store.setStatus(id, null); nav.replace(id); } }] : [])] }]);
  $("#fav").onclick = () => { store.setFavorite(id, !e.favorite); nav.replace(id); };

  // сезоны и фильмы
  src.franchise(rel).then((entries) => {
    if (!entries.length || !nav.active()) return;
    $("#seasons").innerHTML = `<h2>${t("anime.seasons")}</h2><div class="strip">${entries.map((x, i) => `<div class="season${x.current ? " cur" : ""}" data-i="${i}">
      <div class="poster">${lazyImg(x.poster)}</div>
      <div class="l">${esc(x.label)} · ${x.year || t("anime.announce")}</div><div class="nm">${esc(x.name)}</div></div>`).join("")}</div>`;
    $("#seasons .strip").onclick = (ev) => { const s = ev.target.closest("[data-i]"); const x = s && entries[+s.dataset.i]; if (x && !x.current) nav.show("details", x.releaseId); };
    // Прокручиваем только ленту (scrollIntoView дёргал бы и всю страницу)
    const cur = $("#seasons .cur"), strip = $("#seasons .strip");
    if (cur) strip.scrollLeft = cur.offsetLeft - strip.clientWidth / 2 + cur.clientWidth / 2;
  });

  // озвучки и серии
  const { dubs } = await src.findDubs(rel);
  if (!nav.active()) return;
  let dub = src.chooseDub(rel, dubs, store);
  // Серии всех источников (по одной озвучке на группу — у всех Kodik один список)
  const reps = dubs.filter((d, i, a) => a.findIndex((x) => dubGroup(x) === dubGroup(d)) === i);
  const union = unionEpisodes(await Promise.all(reps.map(async (d) => [dubGroup(d), await src.episodes(rel, d).catch(() => [])])));
  if (!nav.active()) return;
  let range = null;

  async function renderEps() {
    $("#dub").innerHTML = dub ? `${fa("mic")} ${esc(dub.name)}` : t("anime.no_dubs");
    const own = dub ? await src.episodes(rel, dub) : [];
    if (!nav.active()) return;
    const ownKeys = new Set(own.map((x) => x.key));
    const top = Math.max(0, ...own.flatMap((x) => Object.keys(x.streams || {}).filter((q) => x.streams[q]).map(Number)));
    $("#qnote").textContent = top ? t("anime.quality_up_to", { h: top, name: qualityName(top) }) : (dub && !dub.native ? t("anime.kodik_player") : "");
    const all = shownEpisodes(own, union);
    const prog = store.progress(id), last = store.lastProgress(id);
    $("#epT").textContent = all.length ? t("anime.episodes_n", { n: all.length }) : t("anime.episodes");
    if (!all.length) { $("#eps").innerHTML = `<p class="muted">${t("anime.no_episodes_hint")}</p>`; return; }
    const pages = Math.ceil(all.length / EPISODES_PAGE);
    if (range == null) { const [ri] = store.resumeTarget(id, own); range = Math.floor(Math.max(0, all.findIndex((x) => x.key === own[ri]?.key)) / EPISODES_PAGE); }
    $("#ranges").innerHTML = pages > 1 ? [...Array(pages)].map((_, i) => `<button class="chip${i === range ? " on" : ""}" data-r="${i}">${all[i * EPISODES_PAGE].key}–${all[Math.min(all.length, (i + 1) * EPISODES_PAGE) - 1].key}</button>`).join("") : "";
    $("#eps").innerHTML = all.slice(range * EPISODES_PAGE, (range + 1) * EPISODES_PAGE).map((x) => {
      const missing = !ownKeys.has(x.key);
      const note = missing ? t("anime.available_in", { list: [...(union.get(x.key)?.groups || [])].map((g) => GROUP_NAMES[g] || g).join(", ") }) : (x.name || "");
      return episodeTile({ key: x.key, name: x.name, note, missing, current: last?.key === x.key,
        preview: x.preview || union.get(x.key)?.preview, poster,
        watched: !!prog[x.key]?.watched, progress: progressFraction(prog[x.key]) });
    }).join("");
    $("#play").innerHTML = `${fa("play")} ${t(last ? "anime.continue" : "anime.watch")}`;
  }
  $("#ranges").onclick = (ev) => { const b = ev.target.closest("[data-r]"); if (b) { range = +b.dataset.r; renderEps(); } };
  $("#eps").onclick = (ev) => {
    const t = ev.target.closest("[data-k]"); if (!t) return;
    const slot = union.get(t.dataset.k);
    const inOwn = dub && slot?.groups.has(dubGroup(dub));
    if (!inOwn && slot) {
      const alt = dubs.find((d) => d.native && slot.groups.has(d.id)) || (slot.groups.has("kodik") ? src.chooseDub(rel, dubs.filter((d) => !d.native), store) : null);
      if (alt) { dub = alt; store.setSetting(`dub:${id}`, alt.id); }
    }
    play(id, t.dataset.k, { rel, dub });
  };
  $("#dub").onclick = () => dubs.length && sheet(menuGroups(dubs).map(([groupTitle, items]) => ({ title: t(groupTitle),
    items: items.map((d) => ({ label: d.name, on: d.id === dub?.id,
      action: () => { dub = d; store.setSetting(`dub:${id}`, d.id); store.setSetting("preferredDub", d.name); renderEps(); } })) })));
  $("#play").onclick = () => play(id, "", { rel, dub });
  await renderEps();

  // предстоящие серии
  const info = rel.shikimori?.id ? await src.shikiInfo(rel.shikimori.id, nav.signal) : null;
  const own = dub ? await src.episodes(rel, dub) : [];
  if (!nav.active()) return;
  const dubbing = rel.is_ongoing || (rel.episodes_total && dub?.id === "anilibria" && own.length && own.length < rel.episodes_total);
  const keys = dub?.id === "anilibria" && dubbing ? own.map((x) => x.key) : [...union.keys()];
  const soon = upcoming(rel, info, keys, dubbing ? rel.publish_day?.value : null);
  if (soon.length) {
    $("#soon").innerHTML = `<h2>${t("anime.upcoming")}${info?.episodes ? ` · ${t("anime.total_n", { n: info.episodes })}` : ""}</h2><div class="eps">${soon.map((s) => `
      <div class="ep soon"><div class="n"><span>${t("player.episode_n", { n: s.n })}</span><i class="fa ${s.state === "upcoming" ? "muted" : "accent"}">${s.state === "upcoming" ? I.calendar : I.mic}</i></div>
      <div class="nm">${s.state === "dub" ? t("anime.dub_expected", { date: fmtDate(s.date) }) : s.state === "no_dub" ? t("anime.aired_waiting_dub") : fmtDate(s.date)}</div></div>`).join("")}</div>`;
  }
}
