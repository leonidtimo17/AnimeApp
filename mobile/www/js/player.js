// Плеер: встроенный (HLS/mp4) с фишками как в Кинопоиске и экран плеера Kodik.
import * as store from "./store.js";
import * as src from "./sources.js";
import { I, episodeRow, esc, fa, fmtTime, sheet, toast } from "./ui.js";
import { commentsPanel } from "./comments.js";

/** HTML списка серий для боковой панели плеера. */
function episodeList(opts, idx) {
  const prog = store.progress(opts.rel.id);
  return `<div class="ttl">Серии · ${opts.eps.length}</div>` + opts.eps.map((e, i) => episodeRow({
    key: src.fmtOrd(e.ordinal), name: e.name, preview: e.preview, poster: opts.poster, current: i === idx,
    watched: !!prog[e.key]?.watched, progress: prog[e.key]?.dur ? prog[e.key].pos / prog[e.key].dur : 0 }, i)).join("");
}

let speedCache = { t: 0, mbps: null };

// Сколько Мбит/с нужно для качества (по высоте кадра)
const requiredMbps = (q) => { const h = +q; return h >= 2000 ? 20 : h >= 1400 ? 12 : h >= 1000 ? 9 : h >= 700 ? 4 : 0; };
export const qualityName = (h) => (h >= 2000 ? "4K" : h >= 1400 ? "2K" : h >= 1000 ? "Full HD" : h >= 700 ? "HD" : "SD");
const sortQ = (qs) => [...qs].sort((a, b) => +b - +a);
// Примерный битрейт для общего плейлиста (hls.js сам уточнит по факту загрузки)
const bitrate = (q) => ({ 2160: 15e6, 1440: 9e6, 1080: 5e6, 720: 2.5e6, 480: 1.2e6 }[q] || Math.max(0.6e6, +q * 2500));

function recommend(mbps, available) {
  const avail = sortQ(available);
  if (!avail.length) return null;
  if (mbps == null) return avail.find((q) => +q <= 720) || avail.at(-1);
  return avail.find((q) => requiredMbps(q) <= mbps) || avail.at(-1);
}

// Замер скорости по кусочку этого же видео (как у онлайн-кинотеатров).
// Качаем два куска параллельно до ~3.5 с и считаем скорость только после «разгона» соединения:
// короткая закачка почти целиком уходит на установку соединения и показывала в 5–10 раз меньше настоящей скорости.
const PROBE_MS = 3500, PROBE_BYTES = 16_000_000, WARMUP_MS = 500;

/** Адреса для замера: первые сегменты HLS или два куска mp4. [[url, range|null], ...] */
async function probeTargets(url) {
  let media = url;
  for (let depth = 0; depth < 2 && media.split("?")[0].endsWith(".m3u8"); depth++) {
    const text = await (await fetch(media)).text();
    const lines = text.split("\n").map((s) => s.trim()).filter((s) => s && !s.startsWith("#"));
    if (!lines.length) return [];
    if (!text.includes("#EXTINF")) { media = new URL(lines[0], media).href; continue; }  // мастер → вариант
    return lines.slice(0, 2).map((s) => [new URL(s, media).href, null]);
  }
  return [[media, "bytes=0-7999999"], [media, "bytes=8000000-15999999"]];
}

async function measure(url, force = false) {
  if (!force && speedCache.mbps != null && Date.now() - speedCache.t < 600_000) return speedCache.mbps;
  try {
    const targets = await probeTargets(url);
    if (!targets.length) return null;
    const ctrls = targets.map(() => new AbortController());
    const samples = [];  // [время, всего байт]
    let total = 0, t0 = 0;
    const stopAll = () => ctrls.forEach((c) => c.abort());
    const timer = setTimeout(stopAll, PROBE_MS);
    await Promise.all(targets.map(async ([u, range], i) => {
      try {
        const res = await fetch(u, { headers: range ? { Range: range } : {}, signal: ctrls[i].signal, cache: "no-store" });
        const reader = res.body.getReader();
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const now = performance.now();
          if (!t0) t0 = now;
          total += value.length;
          samples.push([now, total]);
          if (total >= PROBE_BYTES) { stopAll(); break; }
        }
      } catch { /* прервали по времени или объёму */ }
    }));
    clearTimeout(timer);
    if (total < 300_000 || samples.length < 2) return null;
    const end = samples.at(-1);
    // Окно после разгона; если всё скачалось мгновенно — считаем по всей закачке
    const warm = samples.find(([t]) => t - t0 >= WARMUP_MS);
    const [ta, ba] = warm && end[0] - warm[0] >= 300 ? warm : [t0, 0];
    const mbps = ((end[1] - ba) * 8) / ((end[0] - ta) / 1000) / 1e6;
    if (!isFinite(mbps) || mbps <= 0) return null;
    speedCache = { t: Date.now(), mbps };
    return mbps;
  } catch { return null; }
}

const HIDE_MS = 5000;  // через сколько бездействия прятать управление

/**
 * Горячие клавиши для планшета с клавиатурой — как на ПК. Буквы берём по физической клавише (e.code),
 * поэтому работают и в русской раскладке. Кнопочные действия нажимают те же кнопки, что и пальцем.
 * extra: {seek(сек), volume(шаг), mute(), skip(), speed?(±1), percent(0..0.9), osd(text, ms)}
 */
const HOTKEYS_HELP = "Пробел/K — пауза   ←/→ — 10 с (Shift — 30 с)   ↑/↓ — громкость   M — звук\n"
  + "N/P — следующая/предыдущая серия   S — пропустить заставку   E — список серий\n"
  + "F — полный экран   Z — масштаб   T — таймер сна   C — обсуждение   [ / ] — скорость   0–9 — перейти в %   Esc — закрыть";
function hotkeys(root, extra) {
  const click = (a) => {
    const b = root.querySelector(`[data-a="${a}"]`);
    if (b && !b.disabled && !b.hidden) b.click();
    document.activeElement?.blur?.();  // иначе пробел ещё раз «нажмёт» кнопку в фокусе
  };
  // Esc закрывает список серий, а обсуждение — только в полноэкранном режиме (на странице оно часть страницы)
  const list = () => root.querySelector(".pl-list:not([hidden])")
    || (document.getElementById("player").classList.contains("fs") ? root.querySelector(".pl-comments:not([hidden])") : null);
  const onKey = (e) => {
    if (e.target.closest?.("input, textarea, select") || e.ctrlKey || e.altKey || e.metaKey) return;
    if (!document.getElementById("sheet").hidden) return;  // открыто меню — Esc закроет его приложение
    const k = e.key.toLowerCase(), code = e.code;
    if (k === "escape") {
      if (!list()) return;  // закрыть плеер — это «назад» приложения
      list().hidden = true;
      e.preventDefault(); e.stopPropagation();
      return;
    }
    let done = true;
    if (k === " " || code === "KeyK" || k === "mediaplaypause") click("play");
    else if (k === "arrowleft" || code === "KeyJ") extra.seek(e.shiftKey ? -30 : -10);
    else if (k === "arrowright" || code === "KeyL") extra.seek(e.shiftKey ? 30 : 10);
    else if (k === "arrowup") extra.volume(0.1);
    else if (k === "arrowdown") extra.volume(-0.1);
    else if (code === "KeyM") extra.mute();
    else if (code === "KeyN" || k === "mediatracknext") click("next");
    else if (code === "KeyP" || k === "mediatrackprevious") click("prev");
    else if (code === "KeyS") extra.skip();
    else if (code === "KeyE") click(root.querySelector("[data-a=list]") ? "list" : "eps");
    else if (code === "KeyF") click("fs");
    else if (code === "KeyZ") click("zoom");
    else if (code === "KeyT") click("sleep");
    else if (code === "KeyC") click("comments");
    else if (code === "BracketRight" && extra.speed) extra.speed(1);
    else if (code === "BracketLeft" && extra.speed) extra.speed(-1);
    else if (/^(Digit|Numpad)\d$/.test(code)) extra.percent(+code.slice(-1) / 10);
    else if (k === "?" || code === "KeyH" || k === "f1") extra.osd(HOTKEYS_HELP, 6000);
    else done = false;
    if (done) e.preventDefault();
  };
  document.addEventListener("keydown", onKey, true);
  return () => document.removeEventListener("keydown", onKey, true);
}
const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];

/** Таймер сна: остановить видео через N минут или после текущей серии. Живёт между сериями и сменой озвучки. */
const sleep = { until: 0, min: 0, episode: false };
const sleepActive = () => sleep.episode || sleep.until > Date.now();
function sleepMenu(osd) {
  const set = (min, episode) => {
    Object.assign(sleep, { min, episode, until: min ? Date.now() + min * 60_000 : 0 });
    osd(min ? `Таймер сна: остановлю через ${min} мин` : episode ? "Остановлю после этой серии" : "Таймер сна выключен", 1800);
  };
  const left = sleep.until > Date.now() ? ` · осталось ${Math.ceil((sleep.until - Date.now()) / 60_000)} мин` : "";
  sheet([{ title: `Таймер сна${left}`, items: [
    { label: "Выключен", on: !sleepActive(), action: () => set(0, false) },
    { label: "После этой серии", on: sleep.episode, action: () => set(0, true) },
    ...[15, 30, 45, 60, 90].map((m) => ({ label: `Через ${m} минут`, on: sleep.until > Date.now() && sleep.min === m, action: () => set(m, false) })),
  ] }]);
}
/** Раз в секунду: пора ли остановить видео по таймеру (минуты). */
function sleepTick(root, pause, osd) {
  root.querySelectorAll("[data-a=sleep]").forEach((b) => b.classList.toggle("on", sleepActive()));
  if (sleep.until && Date.now() >= sleep.until) {
    Object.assign(sleep, { until: 0, min: 0 });
    pause();
    osd("Таймер сна — видео остановлено. Спокойной ночи!", 4000);
  }
}
/** Серия закончилась: если таймер «после этой серии» — не включаем следующую. */
function sleepAfterEpisode(osd) {
  if (!sleep.episode) return false;
  sleep.episode = false;
  osd("Таймер сна — серия закончилась. Спокойной ночи!", 4000);
  return true;
}

/** Полноэкранный режим Android: без строки состояния и навигации (нативный плагин, веб-вариант Capacitor отменяет). */
const systemBars = (hidden) => window.Capacitor?.Plugins?.PlayerScreen?.fullscreen({ on: hidden }).catch(() => {});

/**
 * Масштаб картинки: «вписать» (видно весь кадр, возможны чёрные полосы) или «заполнить экран» (края обрезаются).
 * Возвращает apply(fill) — применить и запомнить.
 */
function zoomer(root, target, isFrame) {
  const apply = (fill) => {
    store.setSetting("zoomFill", fill);
    root.classList.toggle("zoom-fill", fill);
    if (!isFrame) { target.style.objectFit = fill ? "cover" : "contain"; return; }
    // Kodik — внутрь iframe не залезть, поэтому увеличиваем сам iframe так, чтобы кадр 16:9 закрыл экран
    const w = root.clientWidth, h = root.clientHeight;
    const vw = Math.min(w, (h * 16) / 9), vh = (vw * 9) / 16;
    target.style.transform = fill && vw && vh ? `scale(${Math.max(w / vw, h / vh).toFixed(3)})` : "";
  };
  return apply;
}

/**
 * Жест двумя пальцами: развести — заполнить экран, свести — вписать.
 */
function pinch(el, onZoom) {
  let d0 = 0;
  const dist = (t) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
  el.addEventListener("touchstart", (e) => { if (e.touches.length === 2) d0 = dist(e.touches); }, { passive: true });
  el.addEventListener("touchmove", (e) => {
    if (!d0 || e.touches.length !== 2) return;
    const r = dist(e.touches) / d0;
    if (r > 1.15 || r < 0.87) { onZoom(r > 1); d0 = 0; }
  }, { passive: true });
  el.addEventListener("touchend", () => (d0 = 0));
}

/**
 * Страница просмотра как на YouTube: видео, под ним название, серия, кнопки, описание и обсуждение,
 * справа (на планшете в книжной ориентации — ниже) — список серий с кадрами. Полный экран — кнопкой (F).
 * open({rel, dub, dubs, eps, key, position, seasons, poster, onDub(dub, key, pos), onSeason(entry), onClose})
 */
export function open(opts) {
  const root = document.getElementById("player");
  // Сначала закрываем предыдущий плеер (смена озвучки/сезона), иначе он спрячет новый.
  close.current?.(false);
  root.hidden = false;
  root.style.transform = root.style.opacity = root.style.transition = "";
  root.className = "";
  root.innerHTML = `<div class="pv-main"><div class="pv-video"></div><div class="pv-info"><div class="pv-top"></div>
      <h2 class="pv-h">${fa("comments")} Обсуждение</h2></div></div>
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
    systemBars(on);
    store.setSetting("playerFs", on);
    root.querySelectorAll("[data-a=fs]").forEach((b) => (b.innerHTML = fa(on ? "compress" : "expand")));
    // Обсуждение: на странице — под видео и открыто всегда, в полном экране — по кнопке поверх видео
    if (on) { cp.toggle(false); cp.mount(box); } else { cp.mount(info); cp.toggle(true); }
    window.dispatchEvent(new Event("resize"));
  }

  function renderInfo() {
    const e = opts.eps[curIdx], en = store.entry(opts.rel.id);
    top.innerHTML = `
      <h1 class="pv-title">${esc(src.title(opts.rel))}</h1>
      <div class="pv-sub">${esc(src.fmtOrd(e.ordinal))} серия${e.name ? ` · ${esc(e.name)}` : ""} · ${curIdx + 1} из ${opts.eps.length}</div>
      <div class="pv-actions">
        <button class="chip" data-p="dub">${fa("mic")} ${esc(opts.dub.name)}</button>
        <button class="chip${en.favorite ? " on" : ""}" data-p="fav">${fa("heart")} Избранное</button>
        <button class="chip${en.status === "planned" ? " on" : ""}" data-p="plan">${fa("bookmark")} Хочу посмотреть</button>
        <button class="chip" data-p="status">${fa("check")} ${esc(store.STATUSES[en.status] || "Статус")}</button>
        <button class="chip${en.score ? " on" : ""}" data-p="score">${fa("star")} ${en.score ? `Оценка ${en.score}` : "Оценить"}</button>
        ${opts.seasons?.length ? `<button class="chip" data-p="seasons">${fa("layers")} Сезоны и фильмы</button>` : ""}
        <button class="chip" data-p="fs">${fa("expand")} На весь экран</button>
      </div>
      ${opts.rel.description ? `<div class="pv-desc" data-p="desc">${esc(opts.rel.description)}</div>` : ""}`;
  }

  function renderSide() {
    const prog = store.progress(opts.rel.id);
    const rows = opts.eps.map((e, i) => [e, i]).filter(([e, i]) => filter === "all" || !prog[e.key]?.watched || i === curIdx)
      .map(([e, i]) => episodeRow({ key: src.fmtOrd(e.ordinal), name: e.name, preview: e.preview, poster: opts.poster,
        current: i === curIdx, watched: !!prog[e.key]?.watched,
        progress: prog[e.key]?.dur ? prog[e.key].pos / prog[e.key].dur : 0 }, i)).join("");
    side.innerHTML = `<div class="pv-chips">
        <button class="chip${filter === "all" ? " on" : ""}" data-f="all">Все серии · ${opts.eps.length}</button>
        <button class="chip${filter === "new" ? " on" : ""}" data-f="new">Непросмотренные</button>
      </div><div class="pv-list pl-list">${rows || `<p class="muted">Все серии просмотрены 🎉</p>`}</div>`;
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
    else if (a === "fav") { store.setFavorite(id, !en.favorite); toast(en.favorite ? "Убрано из избранного" : "Добавлено в избранное"); renderInfo(); }
    else if (a === "status") {
      sheet([{ title: "Статус", items: [...Object.entries(store.STATUSES).map(([k, n]) => ({ label: n, on: en.status === k,
        action: () => { store.setStatus(id, k); toast(`Статус: ${n}`); renderInfo(); } })),
        { label: "Убрать из списка", action: () => { store.setStatus(id, null); renderInfo(); } }] }]);
    } else if (a === "score") {
      sheet([{ title: "Моя оценка", items: [...Array.from({ length: 10 }, (_x, i) => 10 - i).map((v) => ({
        label: `${v} ${"★".repeat(Math.round(v / 2))}`, on: en.score === v,
        action: () => { store.setScore(id, v); toast(`Оценка ${v} — уйдёт на Shikimori`); renderInfo(); } })),
        { label: "Убрать оценку", action: () => { store.setScore(id, null); renderInfo(); } }] }]);
    }
    else if (a === "plan") {
      store.setStatus(id, en.status === "planned" ? "watching" : "planned");
      toast(en.status === "planned" ? "Убрано из «Хочу посмотреть»" : "Добавлено в «Хочу посмотреть»");
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
    toggleFs: () => setFs(!isFs()),
    exitFs: () => (isFs() ? (setFs(false), true) : false),
    comments: () => { if (isFs()) cp.toggle(); else cp.el.scrollIntoView({ behavior: "smooth", block: "start" }); },
    episode: (i) => { curIdx = i; renderInfo(); renderSide(); },
  };
  const popts = { ...opts, cp, page };
  ctl = opts.dub.native ? nativePlayer(box, popts) : kodikPlayer(box, popts);
  setFs(store.setting("playerFs", false));
  close.exitFs = page.exitFs;
  close.current = (notify = true) => {
    ctl.destroy();
    cp.destroy();
    root.hidden = true;
    root.innerHTML = "";
    root.className = "";
    close.current = null;
    systemBars(false);
    if (notify) opts.onClose?.();
  };
  const entry = store.entry(opts.rel.id);
  if (!entry.status || entry.status === "planned" || entry.status === "postponed") store.setStatus(opts.rel.id, "watching");
}
/** «Назад»: из полного экрана — на страницу просмотра, со страницы — закрыть плеер. */
export function close() {
  if (!close.current) return false;
  if (close.exitFs?.()) return true;
  close.current();
  return true;
}

/**
 * Закрытие плеера свайпом сверху вниз (как в YouTube). handle — за что тянуть.
 * Возвращает функцию, которая говорит, был ли только что свайп (чтобы не срабатывал тап).
 */
function swipeToClose(root, handle) {
  let start = null, dy = 0, lastSwipe = 0;
  const reset = (animate) => {
    root.style.transition = animate ? "transform .2s, opacity .2s" : "";
    root.style.transform = "";
    root.style.opacity = "";
  };
  handle.addEventListener("touchstart", (e) => {
    if (e.touches.length !== 1) return;
    start = { x: e.touches[0].clientX, y: e.touches[0].clientY };
    dy = 0;
    root.style.transition = "";
  }, { passive: true });
  handle.addEventListener("touchmove", (e) => {
    if (!start) return;
    if (e.touches.length > 1) { start = null; reset(true); return; }
    const dx = e.touches[0].clientX - start.x;
    dy = e.touches[0].clientY - start.y;
    if (dy <= 10 || Math.abs(dx) > dy) { if (dy <= 0) root.style.transform = ""; return; }
    root.style.transform = `translateY(${dy}px)`;
    root.style.opacity = String(Math.max(0.35, 1 - dy / (root.clientHeight * 1.2)));
  }, { passive: true });
  handle.addEventListener("touchend", () => {
    if (!start) return;
    start = null;
    if (dy > 12) lastSwipe = Date.now();
    if (dy > Math.min(180, root.clientHeight * 0.25) && root.classList.contains("fs")) {
      reset(true);
      close();
    } else if (dy > Math.min(180, root.clientHeight * 0.25)) {
      root.style.transition = "transform .2s, opacity .2s";
      root.style.transform = "translateY(100%)";
      root.style.opacity = "0";
      setTimeout(() => { reset(false); close(); }, 200);
    } else {
      reset(true);
    }
  });
  handle.addEventListener("touchcancel", () => { start = null; reset(true); });
  return () => Date.now() - lastSwipe < 400;
}
export const isOpen = () => !!close.current;

function startIndex(opts) {
  const prog = store.progress(opts.rel.id);
  if (opts.key) {
    const i = Math.max(0, opts.eps.findIndex((e) => e.key === opts.key));
    const p = prog[opts.eps[i].key];
    return [i, opts.position ?? (p && !p.watched ? p.pos : 0)];
  }
  const [i, pos] = store.resumeTarget(opts.rel.id, opts.eps);
  return [i, opts.position ?? pos];
}

function menus(opts, getState) {
  return {
    dub() {
      const groups = [
        ["Встроенный плеер", opts.dubs.filter((d) => d.native)],
        ["Плеер Kodik — озвучка", opts.dubs.filter((d) => !d.native && d.kind === "voice")],
        ["Плеер Kodik — субтитры", opts.dubs.filter((d) => !d.native && d.kind === "sub")],
      ].filter(([, items]) => items.length);
      sheet(groups.map(([title, items]) => ({ title, items: items.map((d) => ({ label: d.name, on: d.id === opts.dub.id,
        action: () => { const [key, pos] = getState(); opts.onDub(d, key, pos); } })) })));
    },
    seasons() {
      sheet([{ title: "Сезоны и фильмы", items: opts.seasons.map((e) => ({ label: `${e.label} · ${e.year || "анонс"} — ${e.name}`,
        on: e.current, action: () => !e.current && opts.onSeason(e) })) }]);
    },
  };
}

// ================================================================== встроенный плеер
function nativePlayer(root, opts) {
  const { rel, eps } = opts;
  let [idx, startPos] = startIndex(opts);
  let hls = null, hideTimer = null, saveTimer = null, countTimer = null, count = 0;
  let quality = store.setting("qualityMode", "auto");
  let recommended = "720", badQ = new Set(), openingSkipped = false, nextCancelled = false;
  root.innerHTML = `
    <video playsinline webkit-playsinline preload="auto"></video>
    <div class="spinner" hidden></div>
    <div class="pl-top">
      <button class="pl-btn" data-a="back">${fa("back")}</button>
      <div class="ttl"><b>${esc(src.title(rel))}</b><small class="sub"></small></div>
      <button class="pl-btn" data-a="comments" title="Обсуждение серии">${fa("comments")}</button>
      <button class="pl-btn" data-a="list">${fa("list")}</button>
    </div>
    <div class="pl-center">
      <button class="pl-btn" data-a="rw">${fa("rewind")}</button>
      <button class="pl-btn big" data-a="play">${fa("play")}</button>
      <button class="pl-btn" data-a="ff">${fa("forward")}</button>
    </div>
    <div class="pl-pill"></div>
    <div class="pl-bottom">
      <div class="seek"><div class="tr"></div><div class="buf"></div><div class="marks"></div><div class="pl"></div><div class="kn"></div></div>
      <div class="pl-row">
        <button class="pl-btn" data-a="prev">${fa("prev")}</button>
        <button class="pl-btn" data-a="next">${fa("next")}</button>
        <span class="pl-time">0:00 / 0:00</span><span class="sp"></span>
        <button class="pl-btn" data-a="seasons" ${opts.seasons?.length ? "" : "hidden"}>${fa("layers")}</button>
        <button class="pl-btn txt" data-a="dub">${fa("mic")} ${esc(opts.dub.name)}</button>
        <button class="pl-btn txt" data-a="speed">1x</button>
        <button class="pl-btn txt" data-a="quality">HD</button>
        <button class="pl-btn" data-a="sleep" title="Таймер сна">${fa("moon")}</button>
        <button class="pl-btn" data-a="zoom" title="Масштаб (Z)">${fa("zoom")}</button>
        <button class="pl-btn" data-a="fs" title="Полный экран (F)">${fa("expand")}</button>
      </div>
    </div>
    <div class="pl-osd" hidden></div>
    <div class="pl-list" hidden></div>`;
  const $ = (s) => root.querySelector(s);
  const video = $("video");
  const m = menus(opts, () => [eps[idx].key, video.currentTime]);
  const wasSwipe = swipeToClose(document.getElementById("player"), video);  // тянуть видео вниз — закрыть/выйти из полного экрана
  const cp = opts.cp;

  const ep = () => eps[idx];
  // Только качества, которые реально есть у серии, от лучшего к худшему
  const qualities = () => sortQ(Object.keys(ep().streams).filter((q) => ep().streams[q]));
  const realH = {};  // «озвучка|качество» -> настоящая высота кадра (подписи у источников бывают неточными)
  const height = (q) => realH[`${opts.dub.id}|${q}`] || +q;
  const qLabel = (q, short = false) => (short ? `${qualityName(height(q))} ${height(q)}p` : `${height(q)}p · ${qualityName(height(q))}`);
  let autoCap = null, upVotes = 0, curQ = null;  // потолок «Авто» после подгрузок; текущее качество
  const effQ = () => {
    const avail = qualities().filter((q) => !badQ.has(q));
    if (!avail.length) return null;
    let pref = quality === "auto" ? recommended : quality;
    if (quality === "auto" && autoCap && +pref > +autoCap) pref = autoCap;
    if (avail.includes(pref)) return pref;
    // Нужного нет — ближайшее ниже, иначе самое низкое
    return avail.find((q) => +q < +pref) || avail.at(-1);
  };
  const updateQualityUi = () => {
    const q = curQ || effQ();
    if (q) $("[data-a=quality]").textContent = (quality === "auto" ? "Авто · " : "") + qLabel(q, true);
  };
  // Настоящее разрешение — по первому кадру
  video.addEventListener("resize", () => {
    const q = curQ || effQ();
    if (q && video.videoHeight && realH[`${opts.dub.id}|${q}`] !== video.videoHeight) {
      realH[`${opts.dub.id}|${q}`] = video.videoHeight;
      updateQualityUi();
    }
  });
  let osdTimer;
  const osd = (t, ms = 1200) => { const o = $(".pl-osd"); o.textContent = t; o.hidden = false; clearTimeout(osdTimer); osdTimer = setTimeout(() => (o.hidden = true), ms); };
  // Управление видно HIDE_MS после последнего касания; на паузе, при перемотке и в меню — не прячем
  const poke = () => { root.classList.remove("pl-hidden"); clearTimeout(hideTimer); hideTimer = setTimeout(tryHide, HIDE_MS); };
  const tryHide = () => {
    // Список серий и обсуждение — отдельные панели: из-за них управление не держим (иначе оно не пряталось вовсе)
    if (video.paused || dragging || !document.getElementById("sheet").hidden) return poke();
    root.classList.add("pl-hidden");
  };
  const hideNow = () => { clearTimeout(hideTimer); root.classList.add("pl-hidden"); };
  root.addEventListener("pointerdown", (e) => { if (e.target.closest(".pl-top, .pl-bottom, .pl-center, .pl-pill")) poke(); });
  const zoom = zoomer(root, video, false);
  zoom(store.setting("zoomFill", false));
  pinch(video, (fill) => { zoom(fill); osd(fill ? "На весь экран" : "Весь кадр"); });

  function save(force) {
    const e = ep();
    if (!video.duration || (video.currentTime < 5 && !force)) return;
    const pos = force === "end" ? video.duration : video.currentTime;
    store.saveProgress(rel.id, e.key, e.ordinal, pos, video.duration, e.ending?.start || null);
  }

  async function load(pos) {
    const e = ep();
    $(".sub").textContent = `${src.fmtOrd(e.ordinal)} серия · ${idx + 1} из ${eps.length} · ${opts.dub.name}`;
    cp.episodeChanged();
    opts.page.episode(idx);
    $("[data-a=prev]").disabled = idx === 0;
    $("[data-a=next]").disabled = idx >= eps.length - 1;
    openingSkipped = false; nextCancelled = false; badQ = new Set();
    clearInterval(countTimer); $(".pl-pill").innerHTML = "";
    const avail = qualities();
    if (quality === "auto") {
      $(".spinner").hidden = false;
      if (speedCache.mbps == null) osd("Проверяем скорость интернета…", 4000);
      // Замеряем на самом высоком качестве: у него крупные куски, замер точнее
      const mbps = await measure(e.streams[qualities()[0]] || Object.values(e.streams)[0]);
      if (ep() !== e) return;
      recommended = recommend(mbps, avail);
      if (mbps) osd(`Интернет ~${Math.round(mbps)} Мбит/с → ${qLabel(recommended)} (рекомендовано)`, 2500);
    }
    setSource(pos);
    renderMarks();
  }

  let masterUrl = null;
  // Качество уровня hls.js: по нашему полю QUALITY, иначе — по ссылке на поток
  const levelKey = (i) => {
    const l = hls?.levels?.[i];
    if (!l) return null;
    const tag = String(l.attrs?.QUALITY || "").replace(/"/g, "");
    if (tag) return tag;
    const urls = [].concat(l.url || l.uri || []);
    return qualities().find((q) => urls.includes(ep().streams[q])) || null;
  };
  const levelIndex = (q) => (hls?.levels || []).findIndex((_, i) => levelKey(i) === q);

  function buildMaster() {
    // Один «мастер-плейлист» из всех качеств серии: hls.js сам поднимает качество, когда сеть ускоряется,
    // и опускает, когда замедляется — плавно, без перезагрузки видео.
    const qs = qualities().filter((q) => !badQ.has(q));
    const lines = ["#EXTM3U"];
    for (const q of qs) {
      const h = height(q);
      lines.push(`#EXT-X-STREAM-INF:BANDWIDTH=${Math.round(bitrate(q))},RESOLUTION=${Math.round(h * 16 / 9)}x${h},QUALITY="${q}"`);
      lines.push(ep().streams[q]);
    }
    if (masterUrl) URL.revokeObjectURL(masterUrl);
    masterUrl = URL.createObjectURL(new Blob([lines.join("\n")], { type: "application/vnd.apple.mpegurl" }));
    return masterUrl;
  }

  /**
   * Полностью освободить прошлое видео перед новым: отвязать MediaSource, очистить буферы элемента <video>.
   * Без этого каждая серия оставляла в памяти WebView десятки мегабайт — на длинных сериалах приложение
   * съедало память и планшет его закрывал.
   */
  function releaseMedia() {
    if (hls) {
      hls.stopLoad();
      hls.detachMedia();
      hls.destroy();
      hls = null;
      root.__hls = null;
    }
    video.pause();
    video.removeAttribute("src");
    video.load();
  }

  function setSource(pos) {
    const q = effQ();
    if (!q) return;
    reloading = true;  // смена потока сама шлёт «pause»/«play» — панель от них не показываем
    const url = ep().streams[q];
    curQ = q;
    updateQualityUi();
    releaseMedia();
    $(".spinner").hidden = false;
    const startAt = pos > 3 ? pos : 0;
    const allHls = qualities().every((x) => ep().streams[x].split("?")[0].endsWith(".m3u8"));
    if (url.split("?")[0].endsWith(".m3u8") && window.Hls?.isSupported()) {
      // Запас не больше ~45 с: иначе новое качество (после ускорения сети) видно только через пару минут
      // backBufferLength: уже просмотренное держим в памяти не дольше 30 с. По умолчанию hls.js хранит всю серию —
      // к концу 24-минутной серии это сотни мегабайт, и на планшете система закрывала приложение.
      hls = new Hls({ maxBufferLength: 40, maxMaxBufferLength: 45, backBufferLength: 30, maxBufferSize: 40 * 1000 * 1000,
        startPosition: startAt, manifestLoadingMaxRetry: 4,
        levelLoadingMaxRetry: 4, fragLoadingMaxRetry: 6, fragLoadingRetryDelay: 1000,
        capLevelToPlayerSize: false, abrEwmaDefaultEstimate: (speedCache.mbps || 3) * 1e6 });
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        const i = levelIndex(q);
        if (i < 0) return;
        hls.startLevel = i;
        // «Авто» — адаптивное качество hls.js; вручную — фиксированный уровень
        if (quality === "auto") {
          hls.currentLevel = -1;
          if (autoCap) hls.autoLevelCapping = Math.max(levelIndex(autoCap), 0);
        } else hls.currentLevel = i;
      });
      hls.on(Hls.Events.LEVEL_SWITCHED, (_e, data) => {
        const k = levelKey(data.level);
        if (!k || k === curQ) return;
        const up = +k > +curQ;
        curQ = k;
        updateQualityUi();
        if (quality === "auto") osd(up ? `Сеть стала быстрее — ${qLabel(k)}` : `Сеть медленнее — ${qLabel(k)}`, 2200);
      });
      hls.on(Hls.Events.ERROR, (_e, data) => {
        if (!data.fatal) return;
        // Обрыв сети — переподключаемся к тому же качеству, а не понижаем его
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) recover();
        else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError();
        else fallback(video.currentTime || startAt);
      });
      root.__hls = hls;  // для диагностики (без глобальных переменных)
      hls.loadSource(allHls && qualities().length > 1 ? buildMaster() : url);
      hls.attachMedia(video);
    } else {
      video.src = url;
      video.addEventListener("loadedmetadata", () => { if (startAt) video.currentTime = startAt; }, { once: true });
    }
    video.play().catch(() => {});
    if (startAt > 15) osd(`Продолжаем с ${fmtTime(startAt)}`, 2000);
  }

  function fallback(pos) {
    const q = effQ();
    badQ.add(q);
    const next = effQ();
    if (next && next !== q) { osd(`Нет ${qLabel(q)}, переключаемся на ${qLabel(next)}`); setSource(pos); }
    else { $(".spinner").hidden = true; osd("Не удалось воспроизвести серию", 4000); }
  }
  video.addEventListener("error", () => {
    // MEDIA_ERR_NETWORK посреди просмотра — это обрыв связи, а не отсутствие качества
    if (video.error?.code === 2 && video.currentTime > 3) recover();
    else if (!hls) fallback(video.currentTime);
  });

  // --- восстановление после обрыва сети (смена Wi-Fi/VPN)
  let lastTime = -1, frozenSince = 0, tries = 0, recovering = false;
  function recover() {
    if (recovering) return;
    recovering = true;
    setTimeout(() => (recovering = false), 3000);
    tries++;
    frozenSince = 0;
    const pos = video.currentTime || startPos;
    osd(tries > 3 ? "Нет соединения — пробуем снова… Проверьте интернет или VPN" : "Связь прервалась — переподключаемся…", 2500);
    if (tries >= 2 && opts.onStale) { opts.onStale(ep().key, pos); return; }  // свежие ссылки
    setSource(pos);
  }
  const watchdog = setInterval(() => {
    if (video.paused || video.ended || !video.src && !hls) { frozenSince = 0; return; }
    if (video.currentTime !== lastTime) {
      if (video.currentTime > lastTime && lastTime >= 0) tries = 0;
      lastTime = video.currentTime; frozenSince = 0; return;
    }
    if (!frozenSince) frozenSince = Date.now();
    else if (Date.now() - frozenSince > 12000) recover();
  }, 2000);
  const onNet = () => { speedCache = { t: 0, mbps: null }; autoCap = null; upVotes = 0; if (hls) hls.autoLevelCapping = -1;
    if (!video.paused) frozenSince = Date.now() - 9000; };
  window.addEventListener("online", onNet);
  navigator.connection?.addEventListener?.("change", onNet);

  function renderMarks() {
    const e = ep();
    const d = video.duration || e.duration || 0;
    $(".marks").innerHTML = !d ? "" : ["opening", "ending"].map((k) => e[k]?.stop && e[k].start != null
      ? `<div class="mk" style="left:${(e[k].start / d) * 100}%;width:${((e[k].stop - e[k].start) / d) * 100}%"></div>` : "").join("");
  }

  function go(i, pos = null) {
    if (i < 0 || i >= eps.length) return;
    save();
    idx = i;
    const p = store.progress(rel.id)[eps[i].key];
    load(pos ?? (p && !p.watched ? p.pos : 0));
    renderList();
  }

  function renderList() {
    $(".pl-list").innerHTML = episodeList(opts, idx);
    $(".pl-list .on")?.scrollIntoView({ block: "center" });
  }

  function pill() {
    const e = ep();
    const t = video.currentTime, d = video.duration || 0;
    const op = e.opening;
    const inOpening = op?.stop && op.start != null && t >= op.start && t < op.stop - 1.5;
    const inCredits = (e.ending?.start ? t >= e.ending.start : d > 300 && d - t <= 45) && !sleep.episode;
    const box = $(".pl-pill");
    if (inOpening && store.setting("autoskip", false) && !openingSkipped) { skipOpening(); return; }
    if (inOpening && !box.dataset.mode) {
      box.dataset.mode = "op";
      box.innerHTML = `<button data-a="skip">Пропустить заставку ${fa("fwd")}</button>`;
    } else if (!inOpening && box.dataset.mode === "op") { box.dataset.mode = ""; box.innerHTML = ""; }
    if (inCredits && idx < eps.length - 1 && !nextCancelled && box.dataset.mode !== "next") {
      box.dataset.mode = "next";
      count = 10;
      box.innerHTML = `<button data-a="stay">Смотреть титры</button><button class="acc" data-a="gonext">Следующая серия через ${count}</button>`;
      clearInterval(countTimer);
      countTimer = setInterval(() => {
        count--;
        const b = box.querySelector("[data-a=gonext]");
        if (count <= 0) { clearInterval(countTimer); go(idx + 1); }
        else if (b) b.textContent = `Следующая серия через ${count}`;
      }, 1000);
    } else if (!inCredits && box.dataset.mode === "next") { box.dataset.mode = ""; box.innerHTML = ""; clearInterval(countTimer); }
  }
  function skipOpening() {
    const stop = ep().opening?.stop;
    if (!stop) return;
    openingSkipped = true;
    video.currentTime = stop;
    osd("Заставка пропущена");
  }

  // --- события видео
  video.addEventListener("waiting", () => ($(".spinner").hidden = false));
  let reloading = false;
  video.addEventListener("playing", () => { $(".spinner").hidden = true; $("[data-a=play]").innerHTML = fa("pause"); reloading = false; });
  // «playing» приходит и после каждой подгрузки — от него панель не показываем, иначе она всплывает сама
  video.addEventListener("play", () => { if (!reloading) poke(); });
  video.addEventListener("canplay", () => ($(".spinner").hidden = true));
  video.addEventListener("pause", () => { $("[data-a=play]").innerHTML = fa("play"); if (!reloading) poke(); save(); });
  video.addEventListener("loadedmetadata", () => { renderMarks(); fillSkips(); });
  // Нет разметки заставки/титров у источника — берём у AniSkip
  async function fillSkips() {
    const e = ep();
    if (e.opening?.stop && e.ending?.start) return;
    const s = await src.skipTimes(rel.shikimori?.id, e.ordinal, video.duration);
    if (!s || ep() !== e) return;
    if (!e.opening?.stop && s.opening) e.opening = s.opening;
    if (!e.ending?.start && s.ending) e.ending = s.ending;
    renderMarks();
  }
  video.addEventListener("timeupdate", () => {
    const d = video.duration || 0, t = video.currentTime;
    $(".pl-time").textContent = `${fmtTime(t)} / ${fmtTime(d)}`;
    if (!dragging && d) { $(".pl").style.width = `${(t / d) * 100}%`; $(".kn").style.left = `${(t / d) * 100}%`; }
    if (video.buffered.length && d) $(".buf").style.width = `${(video.buffered.end(video.buffered.length - 1) / d) * 100}%`;
    pill();
  });
  video.addEventListener("ended", () => {
    save("end");
    if (sleepAfterEpisode(osd)) return;
    if (idx < eps.length - 1 && !nextCancelled) go(idx + 1);
    else osd("Это была последняя серия", 3000);
  });
  saveTimer = setInterval(save, 5000);
  const sleepTimer = setInterval(() => sleepTick(root, () => video.pause(), osd), 1000);
  const unbindKeys = hotkeys(root, {
    osd,
    seek: (s) => { video.currentTime = Math.max(0, video.currentTime + s); osd(s > 0 ? `+${s} с` : `−${-s} с`, 700); },
    volume: (d) => {
      video.muted = false;
      video.volume = Math.min(1, Math.max(0, Math.round((video.volume + d) * 10) / 10));
      osd(`Громкость ${Math.round(video.volume * 100)}%`, 800);
    },
    mute: () => { video.muted = !video.muted; osd(video.muted ? "Звук выключен" : "Звук включён", 800); },
    skip: () => { if (ep().opening?.stop && video.currentTime < ep().opening.stop) skipOpening(); else osd("Заставки сейчас нет", 900); },
    speed: (d) => {
      const i = SPEEDS.indexOf(video.playbackRate);
      const s = SPEEDS[Math.min(SPEEDS.length - 1, Math.max(0, (i < 0 ? 2 : i) + d))];
      video.playbackRate = s;
      $("[data-a=speed]").textContent = `${s}x`;
      osd(`Скорость ${s}x`, 800);
    },
    percent: (f) => { if (video.duration) { video.currentTime = f * video.duration; osd(`${Math.round(f * 100)}%`, 700); } },
  });

  // --- удержание пальца на видео — скорость 2x, пока держите (как в YouTube)
  let holdTimer = null, holdFrom = null, holdRate = null, holdEnded = 0;
  video.addEventListener("pointerdown", (e) => {
    if (!e.isPrimary) return;
    holdFrom = { x: e.clientX, y: e.clientY };
    clearTimeout(holdTimer);
    holdTimer = setTimeout(() => {
      if (video.paused) return;
      holdRate = video.playbackRate;
      video.playbackRate = 2;
      osd("▶▶ Скорость 2x — пока держите палец", 60_000);
    }, 450);
  });
  video.addEventListener("pointermove", (e) => {
    if (holdFrom && Math.hypot(e.clientX - holdFrom.x, e.clientY - holdFrom.y) > 12) clearTimeout(holdTimer);
  });
  const endHold = () => {
    clearTimeout(holdTimer);
    holdFrom = null;
    if (holdRate == null) return;
    video.playbackRate = holdRate;
    holdRate = null;
    holdEnded = Date.now();
    $(".pl-osd").hidden = true;
  };
  video.addEventListener("pointerup", endHold);
  video.addEventListener("pointercancel", endHold);

  // --- перемотка пальцем
  let dragging = false;
  const seek = $(".seek");
  const at = (x) => { const r = seek.getBoundingClientRect(); return Math.min(1, Math.max(0, (x - r.left) / r.width)); };
  seek.addEventListener("pointerdown", (e) => { dragging = true; seek.setPointerCapture(e.pointerId); move(e); });
  seek.addEventListener("pointermove", (e) => dragging && move(e));
  seek.addEventListener("pointerup", (e) => { dragging = false; if (video.duration) video.currentTime = at(e.clientX) * video.duration; poke(); });
  function move(e) { const f = at(e.clientX); $(".pl").style.width = `${f * 100}%`; $(".kn").style.left = `${f * 100}%`;
    $(".pl-time").textContent = `${fmtTime(f * (video.duration || 0))} / ${fmtTime(video.duration)}`; poke(); }

  // --- касания: тап — показать/скрыть панель, двойной тап слева/справа — ±10 с
  let lastTap = 0;
  video.addEventListener("click", (e) => {
    if (wasSwipe() || Date.now() - holdEnded < 400) return;
    const now = Date.now();
    if (now - lastTap < 300) {
      const right = e.clientX > root.clientWidth / 2;
      video.currentTime += right ? 10 : -10;
      osd(right ? "+10 с" : "−10 с", 700);
      lastTap = 0;
      return;
    }
    lastTap = now;
    setTimeout(() => {
      if (lastTap !== now) return;
      if (!$(".pl-list").hidden) { $(".pl-list").hidden = true; return; }
      if (root.classList.contains("pl-hidden")) poke(); else hideNow();
    }, 300);
  });

  root.onclick = (e) => {
    const b = e.target.closest("[data-a]");
    if (!b) return;
    poke();
    const a = b.dataset.a;
    if (a === "back") close();
    else if (a === "play") video.paused ? video.play() : video.pause();
    else if (a === "rw") { video.currentTime -= 10; osd("−10 с", 700); }
    else if (a === "ff") { video.currentTime += 10; osd("+10 с", 700); }
    else if (a === "prev") go(idx - 1);
    else if (a === "next" || a === "gonext") go(idx + 1);
    else if (a === "skip") skipOpening();
    else if (a === "stay") { nextCancelled = true; clearInterval(countTimer); $(".pl-pill").innerHTML = ""; $(".pl-pill").dataset.mode = ""; }
    else if (a === "list") { $(".pl-list").hidden = !$(".pl-list").hidden; renderList(); }
    else if (a === "comments") opts.page.comments();
    else if (a === "dub") m.dub();
    else if (a === "seasons") m.seasons();
    else if (a === "sleep") sleepMenu(osd);
    else if (a === "speed") sheet([{ title: "Скорость", items: [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2].map((s) => ({
      label: `${s}x${s === 1 ? " (обычная)" : ""}`, on: video.playbackRate === s,
      action: () => { video.playbackRate = s; b.textContent = `${s}x`; } })) }]);
    else if (a === "quality") {
      const now = quality === "auto" && curQ ? ` · сейчас ${height(curQ)}p` : "";
      sheet([{ title: "Качество", items: [
        { label: `Авто — по скорости интернета${now}${speedCache.mbps ? ` · ${Math.round(speedCache.mbps)} Мбит/с` : ""}`,
          on: quality === "auto", action: () => setQuality("auto") },
        ...qualities().map((q) => ({ label: `${qLabel(q)}${q === recommended ? "  · рекомендовано" : ""}`,
          on: quality === q, action: () => setQuality(q) })),
      ] }, { title: "Настройки", items: [{ label: "Автопропуск заставки", on: store.setting("autoskip", false),
        action: () => store.setSetting("autoskip", !store.setting("autoskip", false)) }] }]);
    } else if (a === "fs") opts.page.toggleFs();
    else if (a === "zoom") {
      const fill = !root.classList.contains("zoom-fill");
      zoom(fill);
      osd(fill ? "Заполнить экран" : "Весь кадр");
    }
  };
  $(".pl-list").onclick = (e) => { const d = e.target.closest("[data-i]"); if (d) { go(+d.dataset.i); $(".pl-list").hidden = true; } };
  function setQuality(q) {
    quality = q;
    store.setSetting("qualityMode", q);
    const i = q === "auto" ? -1 : levelIndex(q);
    if (hls && (q === "auto" || i >= 0) && hls.levels?.length > 1) {
      // Общий плейлист уже загружен — переключаем уровень без перезагрузки видео
      autoCap = null;
      hls.autoLevelCapping = -1;
      hls.currentLevel = i;
      if (q !== "auto") { curQ = q; updateQualityUi(); }
    } else {
      setSource(video.currentTime);
    }
    osd(q === "auto" ? "Авто — по скорости интернета" : `Качество ${qLabel(q)}`);
  }

  // --- mp4 (AnimeVost): у файла нет общего плейлиста — сами проверяем сеть раз в минуту
  let waits = [];
  video.addEventListener("waiting", () => {
    if (hls || quality !== "auto" || video.currentTime < 5) return;
    const now = Date.now();
    waits = waits.filter((t) => now - t < 60_000).concat(now);
    const lower = qualities().find((x) => +x < +(curQ || 0) && !badQ.has(x));
    if (waits.length >= 3 && lower) {
      waits = []; upVotes = 0; autoCap = lower;
      osd(`Медленный интернет — переключили на ${qLabel(lower)}`, 2500);
      setSource(video.currentTime);
    }
  });
  const upgradeTimer = setInterval(async () => {
    if (hls || quality !== "auto" || video.paused || !curQ) return;
    const higher = qualities().filter((x) => +x > +curQ && !badQ.has(x));
    if (!higher.length) { upVotes = 0; return; }
    const target = higher.at(-1);
    const e = ep();
    const mbps = await measure(e.streams[target], true);
    if (ep() !== e || mbps == null) return;
    if (mbps < requiredMbps(target)) { upVotes = 0; return; }
    if (++upVotes >= 2) {
      upVotes = 0;
      autoCap = target === qualities()[0] ? null : target;
      recommended = target;
      osd(`Сеть стала быстрее — включаю ${qLabel(target)}`, 2500);
      setSource(video.currentTime);
    }
  }, 60_000);

  renderList();
  load(startPos);
  poke();
  return {
    // Для страницы просмотра: текущая серия, время, перемотка, подсказка, переход на серию
    ep, time: () => video.currentTime, seek: (s) => { video.currentTime = s; }, osd: (t) => osd(t), go: (i) => go(i),
    destroy() {
      save(); clearInterval(saveTimer); clearInterval(countTimer); clearTimeout(hideTimer); clearInterval(watchdog); clearInterval(sleepTimer);
      unbindKeys();
      clearInterval(upgradeTimer); if (masterUrl) URL.revokeObjectURL(masterUrl);
      window.removeEventListener("online", onNet); navigator.connection?.removeEventListener?.("change", onNet);
      if (hls) hls.destroy(); video.pause(); video.removeAttribute("src"); video.load();
    },
  };
}

// ================================================================== плеер Kodik
function kodikPlayer(root, opts) {
  const { rel, eps } = opts;
  let [idx, startPos] = startIndex(opts);
  let pos = 0, dur = 0, lastSave = 0, seekTo = 0, countTimer = null, playing = false, dragging = false, osdTimer;
  let lastTick = Date.now(), userPaused = false, started = false;
  const team = opts.dub.id.split(":")[1];
  // Видео Kodik на весь экран, наши панели — поверх него сверху и снизу.
  // Касания по самому видео забирает iframe, поэтому спрятанные панели остаются «прозрачными кнопками»:
  // первое касание по краю экрана только показывает управление.
  root.classList.add("kp");
  root.innerHTML = `
    <div class="pl-top">
      <button class="pl-btn" data-a="back">${fa("back")}</button>
      <div class="ttl"><b>${esc(src.title(rel))}</b><small class="sub"></small></div>
      <button class="pl-btn" data-a="seasons" ${opts.seasons?.length ? "" : "hidden"}>${fa("layers")}</button>
      <button class="pl-btn txt" data-a="dub">${fa("mic")} ${esc(opts.dub.name)}</button>
      <button class="pl-btn txt" data-a="adblock" title="Блокировать рекламу Kodik"></button>
      <button class="pl-btn" data-a="comments" title="Обсуждение серии">${fa("comments")}</button>
    </div>
    <iframe class="kodik" allow="autoplay"></iframe>
    <div class="spinner"></div>
    <div class="pl-osd" hidden></div>
    <div class="pl-pill kpill"></div>
    <div class="pl-list kplist" hidden></div>
    <div class="kpanel">
      <div class="seek"><div class="tr"></div><div class="pl"></div><div class="kn"></div></div>
      <div class="pl-row">
        <button class="pl-btn" data-a="prev">${fa("prev")}</button>
        <button class="pl-btn ctl" data-a="rw">${fa("rewind")}</button>
        <button class="pl-btn ctl" data-a="play">${fa("play")}</button>
        <button class="pl-btn ctl" data-a="ff">${fa("forward")}</button>
        <button class="pl-btn" data-a="next">${fa("next")}</button>
        <span class="pl-time">0:00 / 0:00</span>
        <button class="pl-btn txt" data-a="eps"></button>
        <span class="sp"></span>
        <span class="kad">Идёт реклама Kodik…</span>
        <button class="pl-btn txt ctl kskip" data-a="skip85">${fa("fwd")} Пропустить заставку</button>
        <button class="pl-btn" data-a="sleep" title="Таймер сна">${fa("moon")}</button>
        <button class="pl-btn" data-a="zoom" title="Масштаб (Z)">${fa("zoom")}</button>
        <button class="pl-btn" data-a="fs" title="Полный экран (F)">${fa("expand")}</button>
      </div>
    </div>`;
  const $ = (s) => root.querySelector(s);
  const frame = $("iframe");
  const m = menus(opts, () => [eps[idx].key, pos]);
  swipeToClose(document.getElementById("player"), $(".pl-top")); // свайп вниз по верхней панели — закрыть
  const cmd = (v) => frame.contentWindow?.postMessage({ key: "kodik_player_api", value: v }, "*");
  const osd = (t, ms = 1000) => { const o = $(".pl-osd"); o.textContent = t; o.hidden = false; clearTimeout(osdTimer); osdTimer = setTimeout(() => (o.hidden = true), ms); };
  const setAd = (on) => { root.classList.toggle("k-ad", on); if (on) poke(); };
  const cp = opts.cp;
  // Блокировка рекламы: пока открыт Kodik, приложение пропускает только его серверы (нативный фильтр запросов)
  let adblock = store.setting("kodikAdblock", true), adCheck = null;
  const setAdblock = (on) => {
    adblock = on;
    window.Capacitor?.Plugins?.PlayerScreen?.adblock?.({ on }).catch(() => {});
    $("[data-a=adblock]").innerHTML = `${on ? fa("check") : fa("plus")} Без рекламы`;
    $("[data-a=adblock]").classList.toggle("on", on);
  };
  setAdblock(adblock);
  let hideTimer = null;
  const poke = () => { root.classList.remove("pl-hidden"); clearTimeout(hideTimer); hideTimer = setTimeout(tryHide, HIDE_MS); };
  const tryHide = () => {
    if (!playing || dragging || root.classList.contains("k-ad") || !document.getElementById("sheet").hidden) return poke();
    root.classList.add("pl-hidden");
  };
  // Касание по спрятанной панели — только показать её, без нажатия кнопки под пальцем
  const reveal = (e) => {
    if (!root.classList.contains("pl-hidden") || !e.target.closest(".pl-top, .kpanel")) return;
    e.stopPropagation(); e.preventDefault();
    poke();
  };
  root.addEventListener("pointerdown", (e) => {
    if (root.classList.contains("pl-hidden")) { root.dataset.reveal = "1"; return reveal(e); }
    delete root.dataset.reveal;
    if (e.target.closest(".pl-top, .kpanel, .pl-pill")) poke();
  }, true);
  root.addEventListener("click", (e) => { if (root.dataset.reveal) { delete root.dataset.reveal; e.stopPropagation(); } }, true);
  const zoom = zoomer(root, frame, true);
  const onResize = () => zoom(root.classList.contains("zoom-fill"));
  window.addEventListener("resize", onResize);

  function render() {
    $(".pl-time").textContent = `${fmtTime(pos)} / ${fmtTime(dur)}`;
    if (!dragging && dur) {
      const f = Math.min(1, pos / dur);
      $(".kpanel .pl").style.width = `${f * 100}%`;
      $(".kpanel .kn").style.left = `${f * 100}%`;
    }
    $("[data-a=play]").innerHTML = playing ? fa("pause") : fa("play");
  }
  function seek(s) { s = Math.max(0, Math.min(dur ? dur - 1 : s, s)); cmd({ method: "seek", seconds: Math.floor(s) }); pos = s; render(); }
  function save(force) {
    const e = eps[idx];
    if (dur > 0 && pos > 5 && (force || Date.now() - lastSave > 5000)) {
      lastSave = Date.now();
      store.saveProgress(rel.id, e.key, e.ordinal, pos, dur, null);
    }
  }
  async function load(i, start) {
    save(true);
    clearInterval(countTimer); countTimer = null;
    $(".pl-pill").innerHTML = "";
    setAd(false);
    idx = i; pos = 0; dur = 0; playing = false; started = false; lastTick = Date.now(); seekTo = start || 0;
    render();
    const e = eps[i];
    $("[data-a=eps]").textContent = `${src.fmtOrd(e.ordinal)} серия`;
    cp.episodeChanged();
    opts.page.episode(i);
    $("[data-a=prev]").disabled = i === 0;
    $("[data-a=next]").disabled = i >= eps.length - 1;
    $(".spinner").hidden = false;
    try {
      const r = e.kodik ? { src: e.kodik, team: opts.dub.name } : await src.kodikSource(e.animelib, team);
      $(".sub").textContent = `${src.fmtOrd(e.ordinal)} серия · ${r.team || opts.dub.name}${r.fallback ? " (выбранной озвучки нет — другая)" : ""}`;
      frame.src = r.src;
      // Видео не пошло с блокировкой (Kodik сменил серверы) — выключаем её для этого просмотра
      clearTimeout(adCheck);
      if (adblock) adCheck = setTimeout(() => {
        if (dur || !adblock) return;
        setAdblock(false);
        osd("Видео не загрузилось без рекламы — включаем как есть", 3000);
        load(idx, seekTo || pos);
      }, 25000);
    } catch (err) {
      $(".spinner").hidden = true;
      toast(err.message);
    }
  }
  function countdown() {
    if (idx >= eps.length - 1 || countTimer || sleep.episode) return;
    let n = 10;
    const box = $(".pl-pill");
    box.innerHTML = `<button data-a="stay">Смотреть титры</button><button class="acc" data-a="next">Следующая серия через ${n}</button>`;
    countTimer = setInterval(() => {
      n--;
      if (n <= 0) { clearInterval(countTimer); countTimer = null; load(idx + 1, 0); }
      else { const b = box.querySelector(".acc"); if (b) b.textContent = `Следующая серия через ${n}`; }
    }, 1000);
  }
  frame.onload = () => { $(".spinner").hidden = true; setTimeout(() => cmd({ method: "play" }), 1500); };
  const onMsg = (ev) => {
    const d = ev.data || {};
    if (d.key === "kodik_player_duration_update") {
      dur = d.value; render();
      const e = eps[idx];
      if (!e.opening?.stop || !e.ending?.start) {
        src.skipTimes(rel.shikimori?.id, e.ordinal, dur).then((s) => {
          if (!s || eps[idx] !== e) return;
          if (!e.opening?.stop && s.opening) e.opening = s.opening;
          if (!e.ending?.start && s.ending) e.ending = s.ending;
        });
      }
      if (seekTo > 5) { const s = seekTo; seekTo = 0; setTimeout(() => { cmd({ method: "seek", seconds: s }); osd(`Продолжаем с ${fmtTime(s)}`); }, 600); }
    } else if (d.key === "kodik_player_time_update") {
      pos = d.value; playing = true; started = true; userPaused = false; lastTick = Date.now(); setAd(false); render(); save(false);
      const e = eps[idx];
      if (e.ending?.start ? pos >= e.ending.start : dur > 300 && dur - pos < 40) countdown();
      // Автопропуск заставки (настройка встроенного плеера), когда её время известно
      const op = e.opening;
      if (op?.stop && op.start != null && pos >= op.start && pos < op.stop - 2 && store.setting("autoskip", false) && !e._skipped) {
        e._skipped = true; seek(op.stop); osd("Заставка пропущена");
      }
    } else if (d.key === "kodik_player_play") {
      // Kodik шлёт «play» и после подгрузок/рекламы — показываем панель, только если видео правда стояло
      const was = playing;
      playing = true; userPaused = false; lastTick = Date.now(); render();
      if (!was) poke();
    }
    else if (d.key === "kodik_player_pause") { playing = false; userPaused = true; render(); save(true); poke(); }
    else if (d.key === "kodik_player_video_ended") { pos = dur; playing = false; render(); save(true); if (!sleepAfterEpisode(osd)) countdown(); }
    else if (d.event === "adShown" || d.title === "vastStarted" || d.key === "kodik_player_advert_started") setAd(true);
    else if (d.key === "kodik_player_advert_ended" || d.title === "currentVastEnded") setAd(false);
  };
  window.addEventListener("message", onMsg);

  // --- восстановление после обрыва сети: видео должно идти, а время не обновляется — перезагружаем с того же места
  const watchdog = setInterval(() => {
    if (!started || userPaused || !dur || root.classList.contains("k-ad")) return;
    if (Date.now() - lastTick > 15000) { lastTick = Date.now(); osd("Связь прервалась — переподключаемся…"); load(idx, pos); }
  }, 3000);
  const onNet = () => { if (started && !userPaused) lastTick = 0; };
  window.addEventListener("online", onNet);
  navigator.connection?.addEventListener?.("change", onNet);

  // --- своя полоса перемотки
  const bar = $(".kpanel .seek");
  const frac = (x) => { const r = bar.getBoundingClientRect(); return Math.min(1, Math.max(0, (x - r.left) / r.width)); };
  const moveTo = (x) => {
    const f = frac(x);
    $(".kpanel .pl").style.width = `${f * 100}%`;
    $(".kpanel .kn").style.left = `${f * 100}%`;
    $(".pl-time").textContent = `${fmtTime(f * dur)} / ${fmtTime(dur)}`;
  };
  bar.addEventListener("pointerdown", (e) => { if (!dur) return; dragging = true; bar.setPointerCapture(e.pointerId); moveTo(e.clientX); });
  bar.addEventListener("pointermove", (e) => dragging && moveTo(e.clientX));
  bar.addEventListener("pointerup", (e) => { if (!dragging) return; dragging = false; seek(frac(e.clientX) * dur); });

  root.onclick = (e) => {
    const b = e.target.closest("[data-a]");
    if (!b) return;
    const a = b.dataset.a;
    if (a === "back") close();
    else if (a === "play") { cmd({ method: playing ? "pause" : "play" }); playing = !playing; render(); }
    else if (a === "rw") { seek(pos - 10); osd("−10 с"); }
    else if (a === "ff") { seek(pos + 10); osd("+10 с"); }
    else if (a === "prev") load(idx - 1, null);
    else if (a === "next") load(idx + 1, null);
    else if (a === "stay") { clearInterval(countTimer); countTimer = null; $(".pl-pill").innerHTML = ""; }
    else if (a === "skip85") {
      // Точное время заставки знает YummyAnime; иначе — стандартные 85 секунд
      const op = eps[idx].opening;
      seek(op?.stop && pos < op.stop ? op.stop : pos + 85);
      osd("Заставка пропущена");
    }
    else if (a === "eps") {
      const list = $(".kplist");
      list.innerHTML = episodeList(opts, idx);
      list.hidden = !list.hidden;
      if (!list.hidden) list.querySelector(".on")?.scrollIntoView({ block: "center" });
    }
    else if (a === "dub") m.dub();
    else if (a === "seasons") m.seasons();
    else if (a === "fs") opts.page.toggleFs();
    else if (a === "zoom") { const fill = !root.classList.contains("zoom-fill"); zoom(fill); osd(fill ? "Заполнить экран" : "Весь кадр"); }
    else if (a === "sleep") sleepMenu(osd);
    else if (a === "comments") opts.page.comments();
    else if (a === "adblock") {
      store.setSetting("kodikAdblock", !adblock);
      setAdblock(!adblock);
      osd(adblock ? "Реклама блокируется" : "Реклама не блокируется");
      load(idx, pos);  // перезагружаем серию с того же места, чтобы настройка подействовала
    }
  };
  $(".kplist").addEventListener("click", (ev) => {
    const it = ev.target.closest("[data-i]");
    if (!it) return;
    ev.stopPropagation();
    $(".kplist").hidden = true;
    load(+it.dataset.i, null);
  });
  load(idx, startPos);
  const sleepTimer = setInterval(() => sleepTick(root, () => { cmd({ method: "pause" }); playing = false; render(); }, osd), 1000);
  let kvol = 1, kmuted = false;
  const unbindKeys = hotkeys(root, {
    osd,
    seek: (s) => { seek(pos + s); osd(s > 0 ? `+${s} с` : `−${-s} с`); },
    volume: (d) => {
      kvol = Math.min(1, Math.max(0, Math.round((kvol + d) * 10) / 10));
      cmd({ method: "volume", volume: kvol });
      osd(`Громкость ${Math.round(kvol * 100)}%`);
    },
    mute: () => { kmuted = !kmuted; cmd({ method: kmuted ? "mute" : "unmute" }); osd(kmuted ? "Звук выключен" : "Звук включён"); },
    skip: () => root.querySelector("[data-a=skip85]").click(),
    percent: (f) => { if (dur) seek(f * dur); },
  });
  // После касания видео фокус клавиатуры уходит внутрь iframe Kodik, и клавиши туда не доходят — забираем фокус обратно
  const onBlur = () => setTimeout(() => {
    if (document.activeElement === frame) { frame.blur(); window.focus(); }
  }, 0);
  window.addEventListener("blur", onBlur);
  zoom(store.setting("zoomFill", false));
  poke();
  return {
    ep: () => eps[idx], time: () => pos, seek: (s) => seek(s), osd: (t) => osd(t), go: (i) => load(i, null),
    destroy() {
    save(true); clearInterval(countTimer); clearInterval(watchdog); clearTimeout(hideTimer); clearInterval(sleepTimer);
    unbindKeys(); window.removeEventListener("blur", onBlur);
    clearTimeout(adCheck);
    window.Capacitor?.Plugins?.PlayerScreen?.adblock?.({ on: false }).catch(() => {});
    window.removeEventListener("message", onMsg);
    window.removeEventListener("resize", onResize);
    window.removeEventListener("online", onNet); navigator.connection?.removeEventListener?.("change", onNet);
    frame.src = "about:blank";
  } };
}
