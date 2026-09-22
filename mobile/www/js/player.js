// Плеер: встроенный (HLS/mp4) с фишками как в Кинопоиске и экран плеера Kodik.
import * as store from "./store.js";
import * as src from "./sources.js";
import { I, episodeRow, esc, fa, fmtTime, sheet, toast } from "./ui.js";

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

// Замер скорости по кусочку этого же видео (как у онлайн-кинотеатров)
async function measure(url, force = false) {
  if (!force && speedCache.mbps != null && Date.now() - speedCache.t < 600_000) return speedCache.mbps;
  try {
    let seg = url;
    for (let depth = 0; depth < 2 && seg.split("?")[0].endsWith(".m3u8"); depth++) {
      const text = await (await fetch(seg)).text();
      const line = text.split("\n").map((s) => s.trim()).find((s) => s && !s.startsWith("#"));
      if (!line) return null;
      seg = new URL(line, seg).href;
    }
    const ctrl = new AbortController();
    const res = await fetch(seg, { headers: { Range: "bytes=0-2499999" }, signal: ctrl.signal });
    const reader = res.body.getReader();
    let bytes = 0, t0 = 0;
    const deadline = performance.now() + 4000;
    while (true) {
      const { done, value } = await reader.read();
      if (!t0) t0 = performance.now();
      if (done) break;
      bytes += value.length;
      if (bytes >= 2_500_000 || performance.now() > deadline) { ctrl.abort(); break; }
    }
    const sec = (performance.now() - t0) / 1000;
    if (bytes < 150_000 || sec <= 0.05) return null;
    speedCache = { t: Date.now(), mbps: (bytes * 8) / sec / 1e6 };
    return speedCache.mbps;
  } catch { return null; }
}

const HIDE_MS = 5000;  // через сколько бездействия прятать управление

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
    root.querySelectorAll("[data-a=fs]").forEach((b) => (b.innerHTML = fa(fill ? "compress" : "expand")));
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
 * open({rel, dub, dubs, eps, key, position, seasons, onDub(dub, key, pos), onSeason(entry), onClose})
 */
export function open(opts) {
  const root = document.getElementById("player");
  // Сначала закрываем предыдущий плеер (смена озвучки/сезона), иначе он спрячет новый.
  close.current?.(false);
  root.hidden = false;
  root.innerHTML = "";
  root.style.transform = root.style.opacity = root.style.transition = "";
  root.className = "";
  systemBars(true);
  const ctl = opts.dub.native ? nativePlayer(root, opts) : kodikPlayer(root, opts);
  close.current = (notify = true) => {
    ctl.destroy();
    root.hidden = true;
    root.innerHTML = "";
    close.current = null;
    systemBars(false);
    if (notify) opts.onClose?.();
  };
  const entry = store.entry(opts.rel.id);
  if (!entry.status || entry.status === "planned" || entry.status === "postponed") store.setStatus(opts.rel.id, "watching");
}
export function close() { if (close.current) { close.current(); return true; } return false; }

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
    if (dy > Math.min(180, root.clientHeight * 0.25)) {
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
        <button class="pl-btn" data-a="fs">${fa("expand")}</button>
      </div>
    </div>
    <div class="pl-osd" hidden></div>
    <div class="pl-list" hidden></div>`;
  const $ = (s) => root.querySelector(s);
  const video = $("video");
  const m = menus(opts, () => [eps[idx].key, video.currentTime]);
  const wasSwipe = swipeToClose(root, video);  // тянуть видео вниз — закрыть плеер

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
    if (video.paused || dragging || !$(".pl-list").hidden || !document.getElementById("sheet").hidden) return poke();
    root.classList.add("pl-hidden");
  };
  const hideNow = () => { clearTimeout(hideTimer); root.classList.add("pl-hidden"); };
  root.addEventListener("pointerdown", (e) => { if (e.target.closest(".pl-top, .pl-bottom, .pl-center, .pl-list, .pl-pill")) poke(); });
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
    $("[data-a=prev]").disabled = idx === 0;
    $("[data-a=next]").disabled = idx >= eps.length - 1;
    openingSkipped = false; nextCancelled = false; badQ = new Set();
    clearInterval(countTimer); $(".pl-pill").innerHTML = "";
    const avail = qualities();
    if (quality === "auto") {
      $(".spinner").hidden = false;
      if (speedCache.mbps == null) osd("Проверяем скорость интернета…", 4000);
      const mbps = await measure(e.streams["720"] || e.streams["480"] || Object.values(e.streams)[0]);
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

  function setSource(pos) {
    const q = effQ();
    if (!q) return;
    const url = ep().streams[q];
    curQ = q;
    updateQualityUi();
    if (hls) { hls.destroy(); hls = null; }
    $(".spinner").hidden = false;
    const startAt = pos > 3 ? pos : 0;
    const allHls = qualities().every((x) => ep().streams[x].split("?")[0].endsWith(".m3u8"));
    if (url.split("?")[0].endsWith(".m3u8") && window.Hls?.isSupported()) {
      // Запас не больше ~45 с: иначе новое качество (после ускорения сети) видно только через пару минут
      hls = new Hls({ maxBufferLength: 40, maxMaxBufferLength: 45, startPosition: startAt, manifestLoadingMaxRetry: 4,
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
  video.addEventListener("playing", () => { $(".spinner").hidden = true; $("[data-a=play]").innerHTML = fa("pause"); poke(); });
  video.addEventListener("canplay", () => ($(".spinner").hidden = true));
  video.addEventListener("pause", () => { $("[data-a=play]").innerHTML = fa("play"); poke(); save(); });
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
    } else if (a === "fs") {
      const fill = !root.classList.contains("zoom-fill");
      zoom(fill);
      osd(fill ? "На весь экран" : "Весь кадр");
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
    destroy() {
      save(); clearInterval(saveTimer); clearInterval(countTimer); clearTimeout(hideTimer); clearInterval(watchdog); clearInterval(sleepTimer);
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
    </div>
    <iframe class="kodik" allow="autoplay; fullscreen" allowfullscreen></iframe>
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
        <button class="pl-btn" data-a="fs">${fa("expand")}</button>
      </div>
    </div>`;
  const $ = (s) => root.querySelector(s);
  const frame = $("iframe");
  const m = menus(opts, () => [eps[idx].key, pos]);
  swipeToClose(root, $(".pl-top")); // свайп вниз по верхней панели — закрыть
  const cmd = (v) => frame.contentWindow?.postMessage({ key: "kodik_player_api", value: v }, "*");
  const osd = (t, ms = 1000) => { const o = $(".pl-osd"); o.textContent = t; o.hidden = false; clearTimeout(osdTimer); osdTimer = setTimeout(() => (o.hidden = true), ms); };
  const setAd = (on) => { root.classList.toggle("k-ad", on); if (on) poke(); };
  let hideTimer = null;
  const poke = () => { root.classList.remove("pl-hidden"); clearTimeout(hideTimer); hideTimer = setTimeout(tryHide, HIDE_MS); };
  const tryHide = () => {
    if (!playing || dragging || root.classList.contains("k-ad") || !$(".kplist").hidden
      || !document.getElementById("sheet").hidden) return poke();
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
    if (e.target.closest(".pl-top, .kpanel, .kplist, .pl-pill")) poke();
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
    $("[data-a=prev]").disabled = i === 0;
    $("[data-a=next]").disabled = i >= eps.length - 1;
    $(".spinner").hidden = false;
    try {
      const r = e.kodik ? { src: e.kodik, team: opts.dub.name } : await src.kodikSource(e.animelib, team);
      $(".sub").textContent = `${src.fmtOrd(e.ordinal)} серия · ${r.team || opts.dub.name}${r.fallback ? " (выбранной озвучки нет — другая)" : ""}`;
      frame.src = r.src;
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
    } else if (d.key === "kodik_player_play") { playing = true; userPaused = false; lastTick = Date.now(); render(); poke(); }
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
    else if (a === "fs") { const fill = !root.classList.contains("zoom-fill"); zoom(fill); osd(fill ? "На весь экран" : "Весь кадр"); }
    else if (a === "sleep") sleepMenu(osd);
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
  zoom(store.setting("zoomFill", false));
  poke();
  return { destroy() {
    save(true); clearInterval(countTimer); clearInterval(watchdog); clearTimeout(hideTimer); clearInterval(sleepTimer);
    window.removeEventListener("message", onMsg);
    window.removeEventListener("resize", onResize);
    window.removeEventListener("online", onNet); navigator.connection?.removeEventListener?.("change", onNet);
    frame.src = "about:blank";
  } };
}
