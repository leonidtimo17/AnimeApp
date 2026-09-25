// «Для вас»: разбор вкуса, рекомендации с процентом совпадения, подборки «Потому что вам понравилось…», ИИ-разбор.
import * as store from "../core/state/store.js";
import { renderCards } from "../components/AnimeCard.js";
import { fa } from "../components/Icons.js";
import { showError, skeletonCards } from "../components/StateView.js";
import { esc } from "../utils/dom.js";
import { becauseOf, profile, score, summary } from "../domain/taste.js";
import { itemFromRelease, openAnime } from "../app/items.js";
import { ai, candidates } from "../features/recommendations/recommendations.js";
import { i18n, t } from "../i18n/index.js";

/** Разбор вкуса простыми словами. */
function describe(p) {
  const s = summary(p);
  if (!s) return "";
  const parts = [];
  if (s.top.length >= 2) parts.push(t(s.top[2] ? "recs.describe_genres3" : "recs.describe_genres2",
    { a: s.top[0].toLowerCase(), b: s.top[1].toLowerCase(), c: (s.top[2] || "").toLowerCase() }));
  if (s.year) parts.push(t("recs.describe_year", { year: s.year }));
  if (s.type) parts.push(t("recs.describe_type", { type: s.type.toLowerCase(), n: s.typeShare }));
  return parts.join(" ");
}

/** Почему рекомендуем: «жанры: …· похоже на «…»» или «популярное». */
function reasonText(r) {
  const parts = [];
  if (r.genres.length) parts.push(t("recs.reason_genres", { list: r.genres.join(", ") }));
  if (r.similar) parts.push(t("recs.reason_similar", { title: r.similar }));
  return parts.join(" · ") || t("recs.reason_popular");
}

function tasteHtml(p) {
  const s = store.stats();
  return `<div class="panel"><h2 class="panel-title">${t("recs.your_taste")}</h2>
    <div class="stats"><div class="stat"><b>${s.inLists}</b><span class="muted">${t("recs.in_lists")}</span></div>
    <div class="stat"><b>${s.episodes}</b><span class="muted">${t("recs.episodes_watched")}</span></div>
    <div class="stat"><b>${t("recs.hours", { n: Math.round(s.hours) })}</b><span class="muted">${t("recs.time_watching")}</span></div>
    <div class="stat"><b>${esc(Object.keys(p.types)[0] || "—")}</b><span class="muted">${t("recs.favorite_format")}</span></div></div>
    <p class="desc">${esc(describe(p))}</p>
    ${Object.entries(p.genres).slice(0, 8).map(([g, v]) => `<div class="gbar"><span class="right">${esc(g)}</span>
      <div class="track"><i style="width:${Math.round(v * 100)}%"></i></div><span class="muted">${Math.round(v * 100)}%</span></div>`).join("")}</div>`;
}

export default async function recs(view, _arg, nav) {
  view.innerHTML = `<div class="row-head"><h1>${t("recs.title")}</h1><button class="btn small primary" id="ai">${fa("magic")} ${t("recs.ai_button")}</button></div>
    <p class="muted" id="st">${t("recs.analyzing")}</p><div id="taste"></div><div id="aiBox"></div>
    <h2>${t("recs.recommended")}</h2><div class="strip" id="main">${skeletonCards(6)}</div><div id="because"></div>`;
  const $ = (s) => view.querySelector(s);
  const open = (item) => openAnime(nav, item);
  const p = profile(store.raw());
  if (!p.empty) $("#taste").innerHTML = tasteHtml(p);
  let scored = [];
  try {
    scored = score(p, await candidates(p, nav.signal));
  } catch (e) {
    if (nav.active()) showError($("#main"), e, () => nav.replace());
    return;
  }
  if (!nav.active()) return;
  $("#st").textContent = p.empty ? t("recs.too_little") : t("recs.analyzed", { n: p.titles.length });
  renderCards($("#main"), scored.slice(0, 30).map((x) => ({ ...itemFromRelease(x.rel),
    subtitle: p.empty ? itemFromRelease(x.rel).subtitle : `${Math.round(x.score * 100)}% · ${reasonText(x.reason)}` })),
  { onOpen: open, empty: t("recs.nothing") });
  const rows = becauseOf(p, scored);
  $("#because").innerHTML = rows.map(([liked], i) =>
    `<h2>${esc(t("recs.because", { title: liked.title }))}</h2><div class="strip" id="bc${i}"></div>`).join("");
  rows.forEach(([, picks], i) => renderCards($(`#bc${i}`), picks.map((x) => itemFromRelease(x.rel)), { onOpen: open }));
  $("#ai").onclick = async () => {
    const box = $("#aiBox");
    box.innerHTML = `<div class="panel"><h2 class="panel-title">${t("recs.ai_title")}</h2><p class="muted" role="status">${t("recs.ai_thinking")}</p></div>`;
    try {
      const r = await ai(p, scored, i18n.locale);
      if (!nav.active()) return;
      box.innerHTML = `<div class="panel"><h2 class="panel-title">${t("recs.ai_title")}</h2><p class="desc">${esc(r.analysis)}</p>
        <h2>${t("recs.ai_picks")}</h2><div class="strip" id="aiS"></div></div>`;
      renderCards(box.querySelector("#aiS"), r.picks.map(([rel, why]) => ({ ...itemFromRelease(rel), subtitle: why })), { onOpen: open });
    } catch (e) {
      if (nav.active()) box.innerHTML = `<div class="panel"><p class="muted">${esc(t(`recs.ai_errors.${e.message}`))} ${t("recs.ai_fallback")}</p></div>`;
    }
  };
}
