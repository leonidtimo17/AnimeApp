// Страница просмотра как на YouTube: видео, под ним название, серия, кнопки, описание и обсуждение,
// справа (в книжной ориентации — ниже) — список серий с кадрами. Полный экран — кнопкой (F).
//
// Состав: этот модуль (страница и её режимы) + native-player / kodik-player (само видео)
// + comments-panel (обсуждение) + menus / hotkeys / gestures / sleep-timer.
import * as store from "../../core/state/store.js";
import { fa } from "../../components/Icons.js";
import { sheet } from "../../components/Sheet.js";
import { toast } from "../../components/Toast.js";
import { t } from "../../i18n/index.js";
import * as platform from "../../platform/platform.js";
import { title } from "../../domain/titles.js";
import { esc } from "../../utils/dom.js";
import { fmtOrd } from "../../utils/format.js";
import { commentsPanel } from "../comments/comments-panel.js";
import { kodikPlayer } from "./kodik-player.js";
import { episodeRows, menus } from "./menus.js";
import { nativePlayer } from "./native-player.js";

let current = null;   // {destroy(notify), exitFs()} открытого плеера

/**
 * open({rel, dub, dubs, eps, key, position, seasons, poster, onDub(dub, key, pos), onSeason(entry), onClose, onStale})
 */
export function open(opts) {
  const root = document.getElementById("player");
  // Сначала закрываем предыдущий плеер (смена озвучки/сезона), иначе он спрячет новый.
  current?.destroy(false);
  root.hidden = false;
  root.style.transform = root.style.opacity = root.style.transition = "";
  root.className = "";
  root.innerHTML = `<div class="pv-main"><div class="pv-video"></div><div class="pv-info"><div class="pv-top"></div>
      <h2 class="pv-h">${fa("comments")} ${t("player.discussion")}</h2></div></div>
    <aside class="pv-side"></aside>`;
  const box = root.querySelector(".pv-video"), info = root.querySelector(".pv-info");
  const top = root.querySelector(".pv-top"), side = root.querySelector(".pv-side");
  let ctl = null, filter = "all", curIdx = 0;
  const cp = commentsPanel(info, { rel: opts.rel, ep: () => ctl.ep(), time: () => ctl.time(),
    seek: (s) => ctl.seek(s), osd: (t) => ctl.osd(t) });
  const pm = menus(opts, () => [ctl.ep().key, ctl.time()]);
  const isFs = () => root.classList.contains("fs");

  function setFs(on) {
    root.classList.toggle("fs", on);
    platform.fullscreen(on, root);
    store.setSetting("playerFs", on);
    root.querySelectorAll("[data-a=fs]").forEach((b) => {
      b.innerHTML = fa(on ? "compress" : "expand");
      b.setAttribute("aria-label", t(on ? "player.exit_fullscreen" : "player.fullscreen"));
    });
    // Обсуждение: на странице — под видео и открыто всегда, в полном экране — по кнопке поверх видео
    if (on) { cp.toggle(false); cp.mount(box); } else { cp.mount(info); cp.toggle(true); }
    window.dispatchEvent(new Event("resize"));
  }

  function renderInfo() {
    const e = opts.eps[curIdx], en = store.entry(opts.rel.id);
    top.innerHTML = `
      <h1 class="pv-title">${esc(title(opts.rel))}</h1>
      <div class="pv-sub">${esc(t("player.episode_of", { ep: fmtOrd(e.ordinal), i: curIdx + 1, n: opts.eps.length }))}${e.name ? ` · ${esc(e.name)}` : ""}</div>
      <div class="pv-actions">
        <button class="chip" data-p="dub">${fa("mic")} ${esc(opts.dub.name)}</button>
        <button class="chip${en.favorite ? " on" : ""}" data-p="fav">${fa("heart")} ${t("library.favorite")}</button>
        <button class="chip${en.status === "planned" ? " on" : ""}" data-p="plan">${fa("bookmark")} ${t("status.planned")}</button>
        <button class="chip" data-p="status">${fa("check")} ${esc(en.status ? t(`status.${en.status}`) : t("anime.status"))}</button>
        <button class="chip${en.score ? " on" : ""}" data-p="score">${fa("star")} ${en.score ? t("anime.score_n", { n: en.score }) : t("anime.rate")}</button>
        ${opts.seasons?.length ? `<button class="chip" data-p="seasons">${fa("layers")} ${t("anime.seasons")}</button>` : ""}
        <button class="chip" data-p="fs">${fa("expand")} ${t("player.fullscreen_button")}</button>
      </div>
      ${opts.rel.description ? `<div class="pv-desc" data-p="desc">${esc(opts.rel.description)}</div>` : ""}`;
  }

  function renderSide() {
    const rows = episodeRows(opts, curIdx, filter);
    side.innerHTML = `<div class="pv-chips">
        <button class="chip${filter === "all" ? " on" : ""}" data-f="all">${t("player.all_episodes", { n: opts.eps.length })}</button>
        <button class="chip${filter === "new" ? " on" : ""}" data-f="new">${t("player.unwatched")}</button>
      </div><div class="pv-list pl-list">${rows || `<p class="muted">${t("player.all_watched")}</p>`}</div>`;
    const cur = side.querySelector(".on[data-i]");
    if (cur) side.querySelector(".pv-list").scrollTop = cur.offsetTop - 120;
  }

  top.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-p]");
    if (!b) return;
    const a = b.dataset.p, id = opts.rel.id, en = store.entry(id);
    if (a === "dub") pm.dub();
    else if (a === "seasons") pm.seasons();
    else if (a === "fs") setFs(true);
    else if (a === "desc") b.classList.toggle("open");
    else if (a === "fav") { store.setFavorite(id, !en.favorite); toast(t(en.favorite ? "library.fav_removed" : "library.fav_added")); renderInfo(); }
    else if (a === "status") {
      sheet([{ title: t("anime.status"), items: [...Object.keys(store.STATUSES).map((k) => ({ label: t(`status.${k}`), on: en.status === k,
        action: () => { store.setStatus(id, k); toast(t("anime.status_set", { status: t(`status.${k}`) })); renderInfo(); } })),
        { label: t("anime.remove_from_list"), action: () => { store.setStatus(id, null); renderInfo(); } }] }]);
    } else if (a === "score") {
      sheet([{ title: t("anime.my_score"), items: [...Array.from({ length: 10 }, (_x, i) => 10 - i).map((v) => ({
        label: `${v} ${"★".repeat(Math.round(v / 2))}`, on: en.score === v,
        action: () => { store.setScore(id, v); toast(t("anime.score_saved", { n: v })); renderInfo(); } })),
        { label: t("anime.remove_score"), action: () => { store.setScore(id, null); renderInfo(); } }] }]);
    } else if (a === "plan") {
      store.setStatus(id, en.status === "planned" ? "watching" : "planned");
      toast(t(en.status === "planned" ? "library.plan_removed" : "library.plan_added"));
      renderInfo();
    }
  });
  side.addEventListener("click", (ev) => {
    const f = ev.target.closest("[data-f]");
    if (f) { filter = f.dataset.f; renderSide(); return; }
    const it = ev.target.closest("[data-i]");
    if (it) ctl.go(+it.dataset.i);
  });

  const page = {
    root,
    close,
    isFs,
    toggleFs: () => setFs(!isFs()),
    comments: () => { if (isFs()) cp.toggle(); else cp.el.scrollIntoView({ behavior: "smooth", block: "start" }); },
    episode: (i) => { curIdx = i; renderInfo(); renderSide(); },
  };
  const popts = { ...opts, cp, page };
  ctl = opts.dub.native ? nativePlayer(box, popts) : kodikPlayer(box, popts);
  setFs(store.setting("playerFs", false));
  // Браузер, iPad, Mac: вышли из полного экрана системным жестом или Esc — возвращаем страницу просмотра
  const onFsChange = () => { if (!document.fullscreenElement && isFs() && !platform.isNative()) setFs(false); };
  document.addEventListener("fullscreenchange", onFsChange);
  current = {
    exitFs: () => (isFs() ? (setFs(false), true) : false),
    destroy(notify = true) {
      document.removeEventListener("fullscreenchange", onFsChange);
      ctl.destroy();
      cp.destroy();
      root.hidden = true;
      root.innerHTML = "";
      root.className = "";
      current = null;
      platform.fullscreen(false);
      if (notify) opts.onClose?.();
    },
  };
  store.markWatching(opts.rel.id);
}

/** «Назад»: из полного экрана — на страницу просмотра, со страницы — закрыть плеер. */
export function close() {
  if (!current) return false;
  if (current.exitFs()) return true;
  current.destroy();
  return true;
}

export const isOpen = () => !!current;
