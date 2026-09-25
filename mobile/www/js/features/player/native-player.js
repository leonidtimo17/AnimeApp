// Встроенный плеер (HLS/mp4) с фишками как в Кинопоиске.
//
// Качество «Авто» — по скорости из единственного замера при запуске приложения (NetworkService).
// Плеер сам скорость не меряет: для HLS качество подстраивает hls.js по фактической загрузке сегментов,
// для mp4 — понижаем при частых подгрузках. Повторный замер — только кнопкой «Проверить скорость».
//
// Каждая смена источника (серия, качество, переподключение) — новая сессия: события и обработчики старого
// потока ничего не меняют. Обрыв связи: переподключение к тому же потоку, потом со свежими ссылками, потом —
// ошибка с кнопкой «Повторить» (без бесконечных повторов); вернулся интернет — одна попытка сама.
import * as store from "../../core/state/store.js";
import { fa } from "../../components/Icons.js";
import { sheet, sheetOpen } from "../../components/Sheet.js";
import { createAutoHide } from "../../components/player/AutoHide.js";
import { createOsd } from "../../components/player/Osd.js";
import { createPlayerOverlay } from "../../components/player/PlayerOverlay.js";
import { createProgressBar } from "../../components/player/ProgressBar.js";
import { bitrate, QualityPolicy, qualityName, sortQ } from "../../domain/quality.js";
import { title } from "../../domain/titles.js";
import { t } from "../../i18n/index.js";
import { esc } from "../../utils/dom.js";
import { fmtOrd, fmtTime } from "../../utils/format.js";
import { network } from "../../app/network.js";
import * as src from "../../services/sources.js";
import { pinch, swipeToClose, zoomer } from "./gestures.js";
import { hotkeys } from "./hotkeys.js";
import { episodeList, menus, startIndex } from "./menus.js";
import { ErrorKind, Status, createPlayerState } from "./player-state.js";
import { createSessions } from "./playback-session.js";
import { createProgressTracker } from "./progress-tracker.js";
import { afterEpisode, attachSleep, sleepAfterEpisode, sleepMenu } from "./sleep-timer.js";

const HIDE_MS = 5000;        // через сколько бездействия прятать управление
const WATCH_MS = 2000, FROZEN_MS = 12000;
const MAX_RECONNECTS = 2;    // 1 — к тому же потоку, 2 — со свежими ссылками; дальше — ошибка и «Повторить»
const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];

export function nativePlayer(root, opts) {
  const { rel, eps } = opts;
  let [idx, startPos] = startIndex(opts);
  let hls = null, countTimer = null, count = 0;
  const quality = new QualityPolicy(store.setting("qualityMode", "auto"), () => network.state.bandwidthMbps);
  let openingSkipped = false, nextCancelled = false;
  root.innerHTML = `
    <video playsinline webkit-playsinline preload="auto"></video>
    <div class="pl-overlay" hidden></div>
    <div class="pl-top">
      <button class="pl-btn" data-a="back" data-i18n-aria="common.back">${fa("back")}</button>
      <div class="ttl"><b>${esc(title(rel))}</b><small class="sub"></small></div>
      <button class="pl-btn" data-a="comments" data-i18n-aria="player.comments">${fa("comments")}</button>
      <button class="pl-btn" data-a="list" data-i18n-aria="player.episodes">${fa("list")}</button>
    </div>
    <div class="pl-center">
      <button class="pl-btn" data-a="rw" data-i18n-aria="player.rewind">${fa("rewind")}</button>
      <button class="pl-btn big" data-a="play" data-i18n-aria="player.play">${fa("play")}</button>
      <button class="pl-btn" data-a="ff" data-i18n-aria="player.forward">${fa("forward")}</button>
    </div>
    <div class="pl-pill"></div>
    <div class="pl-bottom">
      <div class="seek"></div>
      <div class="pl-row">
        <button class="pl-btn" data-a="prev" data-i18n-aria="player.previous_episode">${fa("prev")}</button>
        <button class="pl-btn" data-a="next" data-i18n-aria="player.next_episode">${fa("next")}</button>
        <span class="pl-time">0:00 / 0:00</span><span class="sp"></span>
        <button class="pl-btn" data-a="seasons" ${opts.seasons?.length ? "" : "hidden"} data-i18n-aria="player.seasons">${fa("layers")}</button>
        <button class="pl-btn txt" data-a="dub">${fa("mic")} ${esc(opts.dub.name)}</button>
        <button class="pl-btn txt" data-a="speed" data-i18n-aria="player.speed">1x</button>
        <button class="pl-btn txt" data-a="quality" data-i18n-aria="player.quality">HD</button>
        <button class="pl-btn" data-a="sleep" data-i18n-aria="player.sleep">${fa("moon")}</button>
        <button class="pl-btn" data-a="zoom" data-i18n-aria="player.zoom">${fa("zoom")}</button>
        <button class="pl-btn" data-a="fs" data-i18n-aria="player.fullscreen">${fa("expand")}</button>
      </div>
    </div>
    <div class="pl-osd" hidden></div>
    <div class="pl-list" hidden></div>`;
  root.querySelectorAll("[data-i18n-aria]").forEach((el) => el.setAttribute("aria-label", t(el.dataset.i18nAria)));
  const $ = (s) => root.querySelector(s);
  const video = $("video");
  const m = menus(opts, () => [eps[idx].key, video.currentTime]);
  const wasSwipe = swipeToClose(opts.page.root, video, opts.page.close);  // тянуть видео вниз — закрыть/выйти из полного экрана
  const cp = opts.cp;
  const offs = [];   // функции, снимающие подписки и таймеры
  const osd = createOsd($(".pl-osd"));
  const say = (text, ms = 1200) => osd.show(text, ms);
  const state = createPlayerState();
  const sessions = createSessions();
  let session = sessions.begin();
  const overlay = createPlayerOverlay($(".pl-overlay"), { onRetry: () => retry(), onOtherDub: () => m.dub() });
  offs.push(state.subscribe((st) => { root.dataset.status = st.status; overlay.render(st); renderPlay(); }));
  const progress = createProgressTracker({
    save: ({ ep, pos, dur }) => store.saveProgress(rel.id, ep.key, ep.ordinal, pos, dur, ep.ending?.start || null),
  });
  progress.track(() => ({ ep: eps[idx], pos: video.currentTime, dur: video.duration }));
  const bar = createProgressBar($(".seek"), {
    onSeek: (s) => { if (video.duration) video.currentTime = s; hide.poke(); },
    onScrub: (s) => { $(".pl-time").textContent = `${fmtTime(s)} / ${fmtTime(video.duration)}`; hide.poke(); },
  });

  const ep = () => eps[idx];
  // Только качества, которые реально есть у серии, от лучшего к худшему
  const qualities = () => sortQ(Object.keys(ep().streams).filter((q) => ep().streams[q]));
  const realH = {};  // «озвучка|качество» -> настоящая высота кадра (подписи у источников бывают неточными)
  const height = (q) => realH[`${opts.dub.id}|${q}`] || +q;
  const qLabel = (q, short = false) => (short ? `${qualityName(height(q))} ${height(q)}p` : `${height(q)}p · ${qualityName(height(q))}`);
  let curQ = null;
  const effQ = () => quality.effective(qualities());
  const updateQualityUi = () => {
    const q = curQ || effQ();
    if (q) $("[data-a=quality]").textContent = (quality.mode === "auto" ? `${t("player.auto")} · ` : "") + qLabel(q, true);
  };
  // Настоящее разрешение — по первому кадру
  video.addEventListener("resize", () => {
    const q = curQ || effQ();
    if (q && video.videoHeight && realH[`${opts.dub.id}|${q}`] !== video.videoHeight) {
      realH[`${opts.dub.id}|${q}`] = video.videoHeight;
      updateQualityUi();
    }
  });
  // Управление видно HIDE_MS после последнего касания; на паузе, при перемотке и в меню — не прячем
  const hide = createAutoHide(root, { delay: HIDE_MS, canHide: () => !video.paused && !bar.dragging && !sheetOpen() });
  root.addEventListener("pointerdown", (e) => { if (e.target.closest(".pl-top, .pl-bottom, .pl-center, .pl-pill")) hide.poke(); });
  const zoom = zoomer(root, video, false);
  zoom(store.setting("zoomFill", false));
  pinch(video, (fill) => { zoom(fill); say(t(fill ? "player.zoom_fill_pinch" : "player.zoom_fit")); });

  function renderPlay() {
    const on = state.status === Status.PLAYING || state.status === Status.BUFFERING;
    $("[data-a=play]").innerHTML = fa(on ? "pause" : "play");
    $("[data-a=play]").setAttribute("aria-label", t(on ? "player.pause" : "player.play"));
  }

  function load(pos) {
    const e = ep();
    $(".sub").textContent = `${t("player.episode_of", { ep: fmtOrd(e.ordinal), i: idx + 1, n: eps.length })} · ${opts.dub.name}`;
    cp.episodeChanged();
    opts.page.episode(idx);
    $("[data-a=prev]").disabled = idx === 0;
    $("[data-a=next]").disabled = idx >= eps.length - 1;
    openingSkipped = false; nextCancelled = false; quality.bad = new Set(); reconnects = 0;
    clearInterval(countTimer); $(".pl-pill").innerHTML = "";
    // Качество — по скорости из замера при запуске приложения; никаких замеров перед серией
    quality.choose(qualities());
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
    // и опускает, когда замедляется — плавно, без перезагрузки видео и без отдельных замеров.
    const qs = qualities().filter((q) => !quality.bad.has(q));
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
   * Без этого каждая серия оставляла в памяти WebView десятки мегабайт.
   */
  function releaseMedia() {
    if (hls) {
      hls.stopLoad();
      hls.detachMedia();
      hls.destroy();
      hls = null;
    }
    video.pause();
    video.removeAttribute("src");
    video.load();
  }

  let reloading = false;
  function setSource(pos) {
    const q = effQ();
    if (!q) return state.dispatch("error", { kind: ErrorKind.NO_SOURCE, detail: "no streams" });
    session = sessions.begin();                 // события прошлого потока больше не учитываются
    const s = session;
    reloading = true;  // смена потока сама шлёт «pause»/«play» — панель от них не показываем
    const url = ep().streams[q];
    curQ = q;
    updateQualityUi();
    releaseMedia();
    state.dispatch("load");
    const startAt = pos > 3 ? pos : 0;
    const allHls = qualities().every((x) => ep().streams[x].split("?")[0].endsWith(".m3u8"));
    if (url.split("?")[0].endsWith(".m3u8") && globalThis.Hls?.isSupported()) {
      // Запас не больше ~45 с: иначе новое качество видно только через пару минут.
      // backBufferLength: просмотренное держим не дольше 30 с — иначе к концу серии сотни мегабайт в памяти.
      hls = new Hls({ maxBufferLength: 40, maxMaxBufferLength: 45, backBufferLength: 30, maxBufferSize: 40 * 1000 * 1000,
        startPosition: startAt, manifestLoadingMaxRetry: 4,
        levelLoadingMaxRetry: 4, fragLoadingMaxRetry: 6, fragLoadingRetryDelay: 1000,
        capLevelToPlayerSize: false, abrEwmaDefaultEstimate: (network.state.bandwidthMbps || 3) * 1e6 });
      const h = hls;
      h.on(Hls.Events.MANIFEST_PARSED, () => {
        if (!s.active()) return;
        const i = levelIndex(q);
        if (i < 0) return;
        h.startLevel = i;
        // «Авто» — адаптивное качество hls.js; вручную — фиксированный уровень
        if (quality.mode === "auto") {
          h.currentLevel = -1;
          if (quality.cap) h.autoLevelCapping = Math.max(levelIndex(quality.cap), 0);
        } else h.currentLevel = i;
      });
      h.on(Hls.Events.LEVEL_SWITCHED, (_e, data) => {
        if (!s.active()) return;
        const k = levelKey(data.level);
        if (!k || k === curQ) return;
        const up = +k > +curQ;
        curQ = k;
        updateQualityUi();
        if (quality.mode === "auto") say(t(up ? "player.network_faster" : "player.network_slower", { q: qLabel(k) }), 2200);
      });
      h.on(Hls.Events.ERROR, (_e, data) => {
        if (!data.fatal || !s.active()) return;
        // Обрыв сети — переподключаемся к тому же качеству, а не понижаем его
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) recover(data.details);
        else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) h.recoverMediaError();
        else fallback(video.currentTime || startAt, data.details);
      });
      h.loadSource(allHls && qualities().length > 1 ? buildMaster() : url);
      h.attachMedia(video);
    } else {
      video.src = url;
      // Позицию ставим только этому потоку (раньше обработчик прошлой серии мог сработать на новой)
      video.addEventListener("loadedmetadata", () => { if (s.active() && startAt) video.currentTime = startAt; }, { once: true });
    }
    video.play().catch(() => { /* автозапуск запрещён — пользователь нажмёт «Играть» */ });
    if (startAt > 15) say(t("player.resume", { time: fmtTime(startAt) }), 2000);
  }

  function fallback(pos, detail) {
    const q = effQ();
    quality.bad.add(q);
    const next = effQ();
    if (next && next !== q) { say(t("player.no_quality", { q: qLabel(q), next: qLabel(next) })); setSource(pos); }
    else state.dispatch("error", { kind: ErrorKind.SOURCE, detail });
  }
  video.addEventListener("error", () => {
    // MEDIA_ERR_NETWORK посреди просмотра — это обрыв связи, а не отсутствие качества
    if (video.error?.code === 2 && video.currentTime > 3) recover(video.error?.message);
    else if (!hls && video.error) fallback(video.currentTime, video.error?.message);
  });

  // --- восстановление после обрыва сети (смена Wi-Fi/VPN). Сторож смотрит только на время видео
  //     (запросов не делает) и работает, лишь пока видео играет.
  let lastTime = -1, frozenSince = 0, reconnects = 0, recovering = false, watchdog = null;
  function recover(detail) {
    if (recovering) return;
    if (reconnects >= MAX_RECONNECTS) {
      stopWatch();
      return state.dispatch("error", { kind: network.state.isOnline ? ErrorKind.NETWORK : ErrorKind.OFFLINE, detail });
    }
    recovering = true;
    setTimeout(() => (recovering = false), 3000);
    reconnects++;
    frozenSince = 0;
    const pos = video.currentTime || startPos;
    say(t("player.reconnecting"), 2500);
    if (reconnects >= 2 && opts.onStale) { opts.onStale(ep().key, pos); return; }  // свежие ссылки
    setSource(pos);
  }
  /** «Повторить»: та же серия с того же места. */
  function retry() {
    reconnects = 0;
    quality.bad = new Set();
    setSource(video.currentTime || startPos);
  }
  const watch = () => {
    if (video.paused || video.ended) { frozenSince = 0; return; }
    if (video.currentTime !== lastTime) {
      if (video.currentTime > lastTime && lastTime >= 0) reconnects = 0;
      lastTime = video.currentTime; frozenSince = 0; return;
    }
    if (!frozenSince) frozenSince = Date.now();
    else if (Date.now() - frozenSince > FROZEN_MS) recover("video frozen");
  };
  const stopWatch = () => { clearInterval(watchdog); watchdog = null; };
  const playing = (on) => { stopWatch(); if (on) watchdog = setInterval(watch, WATCH_MS); };
  // Смена сети (событие ОС): снимаем потолок качества и быстрее проверяем поток. Скорость не меряем.
  offs.push(network.onConnectionChange((kind) => {
    quality.reset();
    if (hls) hls.autoLevelCapping = -1;
    if (!video.paused) frozenSince = Date.now() - (FROZEN_MS - 3000);
    // Вернулся интернет, а серия остановилась с сетевой ошибкой — одна попытка сама
    if (kind === "online" && state.status === Status.ERROR && [ErrorKind.NETWORK, ErrorKind.OFFLINE].includes(state.get().error?.kind)) retry();
  }));

  function renderMarks() {
    const e = ep();
    bar.set(video.currentTime, video.duration || e.duration || 0);
    bar.marks([e.opening, e.ending]);
  }

  function go(i, pos = null) {
    if (i < 0 || i >= eps.length) return;
    progress.flush("switch");
    idx = i;
    const p = store.progress(rel.id)[eps[i].key];
    load(pos ?? (p && !p.watched ? p.pos : 0));
    renderList();
  }

  function renderList() {
    const list = $(".pl-list");
    if (list.hidden) return;             // список рисуется, только когда его открыли
    list.innerHTML = episodeList(opts, idx);
    list.querySelector(".on")?.scrollIntoView({ block: "center" });
  }

  function pill() {
    const e = ep();
    const tt = video.currentTime, d = video.duration || 0;
    const op = e.opening;
    const inOpening = op?.stop && op.start != null && tt >= op.start && tt < op.stop - 1.5;
    const inCredits = (e.ending?.start ? tt >= e.ending.start : d > 300 && d - tt <= 45) && !afterEpisode();
    const box = $(".pl-pill");
    if (inOpening && store.setting("autoskip", false) && !openingSkipped) { skipOpening(); return; }
    if (inOpening && !box.dataset.mode) {
      box.dataset.mode = "op";
      box.innerHTML = `<button data-a="skip">${t("player.skip_opening")} ${fa("fwd")}</button>`;
    } else if (!inOpening && box.dataset.mode === "op") { box.dataset.mode = ""; box.innerHTML = ""; }
    if (inCredits && idx < eps.length - 1 && !nextCancelled && box.dataset.mode !== "next") {
      box.dataset.mode = "next";
      count = 10;
      box.innerHTML = `<button data-a="stay">${t("player.watch_credits")}</button><button class="acc" data-a="gonext">${t("player.next_in", { n: count })}</button>`;
      clearInterval(countTimer);
      countTimer = setInterval(() => {
        count--;
        const b = box.querySelector("[data-a=gonext]");
        if (count <= 0) { clearInterval(countTimer); go(idx + 1); }
        else if (b) b.textContent = t("player.next_in", { n: count });
      }, 1000);
    } else if (!inCredits && box.dataset.mode === "next") { box.dataset.mode = ""; box.innerHTML = ""; clearInterval(countTimer); }
  }
  function skipOpening() {
    const stop = ep().opening?.stop;
    if (!stop) return;
    openingSkipped = true;
    video.currentTime = stop;
    say(t("player.opening_skipped"));
  }

  // --- события видео → состояние плеера
  video.addEventListener("loadedmetadata", () => { state.dispatch("ready"); renderMarks(); fillSkips(session); });
  video.addEventListener("waiting", () => state.dispatch("waiting"));
  video.addEventListener("playing", () => { state.dispatch("playing"); reloading = false; playing(true); });
  // «play» приходит и после каждой подгрузки — от него панель не показываем, иначе она всплывает сама
  video.addEventListener("play", () => { if (!reloading) hide.poke(); });
  video.addEventListener("canplay", () => { if (state.status === Status.LOADING) state.dispatch("ready"); });
  video.addEventListener("pause", () => {
    if (reloading) return;
    state.dispatch("pause");
    hide.poke();
    progress.flush("pause");
    playing(false);
  });
  // Нет разметки заставки/титров у источника — берём у AniSkip
  async function fillSkips(s) {
    const e = ep();
    if (e.opening?.stop && e.ending?.start) return;
    const sk = await src.skipTimes(rel.shikimori?.id, e.ordinal, video.duration);
    if (!sk || !s.active() || ep() !== e) return;
    if (!e.opening?.stop && sk.opening) e.opening = sk.opening;
    if (!e.ending?.start && sk.ending) e.ending = sk.ending;
    renderMarks();
  }
  video.addEventListener("timeupdate", () => {
    const d = video.duration || 0, tt = video.currentTime;
    $(".pl-time").textContent = `${fmtTime(tt)} / ${fmtTime(d)}`;
    bar.set(tt, d, video.buffered.length ? video.buffered.end(video.buffered.length - 1) : 0);
    progress.tick();
    pill();
  });
  video.addEventListener("ended", () => {
    playing(false);
    state.dispatch("ended");
    store.saveProgress(rel.id, ep().key, ep().ordinal, video.duration, video.duration, ep().ending?.start || null);
    if (sleepAfterEpisode(say)) return;
    if (idx < eps.length - 1 && !nextCancelled) go(idx + 1);
    else say(t("player.last_episode"), 3000);
  });
  offs.push(attachSleep(root, () => video.pause(), say));
  offs.push(hotkeys(root, {
    osd: say, isFs: opts.page.isFs,
    seek: (s) => { video.currentTime = Math.max(0, video.currentTime + s); say(t(s > 0 ? "player.seek_plus" : "player.seek_minus", { n: Math.abs(s) }), 700); },
    volume: (d) => {
      video.muted = false;
      video.volume = Math.min(1, Math.max(0, Math.round((video.volume + d) * 10) / 10));
      say(t("player.volume", { n: Math.round(video.volume * 100) }), 800);
    },
    mute: () => { video.muted = !video.muted; say(t(video.muted ? "player.muted" : "player.unmuted"), 800); },
    skip: () => { if (ep().opening?.stop && video.currentTime < ep().opening.stop) skipOpening(); else say(t("player.no_opening"), 900); },
    speed: (d) => {
      const i = SPEEDS.indexOf(video.playbackRate);
      const s = SPEEDS[Math.min(SPEEDS.length - 1, Math.max(0, (i < 0 ? 2 : i) + d))];
      video.playbackRate = s;
      $("[data-a=speed]").textContent = `${s}x`;
      say(t("player.speed_value", { s }), 800);
    },
    percent: (f) => { if (video.duration) { video.currentTime = f * video.duration; say(`${Math.round(f * 100)}%`, 700); } },
  }));

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
      say(t("player.hold_2x"), 60_000);
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
    osd.hide();
  };
  video.addEventListener("pointerup", endHold);
  video.addEventListener("pointercancel", endHold);

  // --- касания: тап — показать/скрыть панель, двойной тап слева/справа — ±10 с
  let lastTap = 0, tapTimer = null;
  video.addEventListener("click", (e) => {
    if (wasSwipe() || Date.now() - holdEnded < 400) return;
    const now = Date.now();
    if (now - lastTap < 300) {
      const right = e.clientX > root.clientWidth / 2;
      video.currentTime += right ? 10 : -10;
      say(t(right ? "player.seek_plus" : "player.seek_minus", { n: 10 }), 700);
      lastTap = 0;
      return;
    }
    lastTap = now;
    clearTimeout(tapTimer);
    tapTimer = setTimeout(() => {
      if (lastTap !== now) return;
      if (!$(".pl-list").hidden) { $(".pl-list").hidden = true; return; }
      if (hide.hidden) hide.poke(); else hide.hideNow();
    }, 300);
  });

  function qualityMenu() {
    const now = quality.mode === "auto" && curQ ? ` · ${t("player.quality_now", { h: height(curQ) })}` : "";
    const mbps = network.state.bandwidthMbps;
    sheet([{ title: t("player.quality"), items: [
      { label: `${t("player.quality_auto")}${now}${mbps ? ` · ${t("network.mbps", { n: Math.round(mbps) })}` : ""}`,
        on: quality.mode === "auto", action: () => setQuality("auto") },
      ...qualities().map((q) => ({ label: `${qLabel(q)}${q === quality.recommended ? `  · ${t("player.recommended")}` : ""}`,
        on: quality.mode === q, action: () => setQuality(q) })),
      { label: t(network.state.measuring ? "network.checking" : "network.check"), action: checkSpeed },
    ] }, { title: t("player.settings"), items: [{ label: t("player.autoskip"), on: store.setting("autoskip", false),
      action: () => store.setSetting("autoskip", !store.setting("autoskip", false)) }] }]);
  }

  /** Проверка скорости по кнопке — на этом же видео; потом качество подбирается заново. */
  async function checkSpeed() {
    const e = ep();
    say(t("network.checking"), 4000);
    const st = await network.measureNow(async () => e.streams[qualities()[0]]);
    if (ep() !== e) return;
    if (!st.bandwidthMbps) return say(t("network.check_failed"), 2500);
    quality.reset();
    const rec = quality.choose(qualities());
    say(t("player.speed_result", { mbps: Math.round(st.bandwidthMbps), q: qLabel(rec) }), 3000);
    if (quality.mode === "auto" && rec !== curQ) setSource(video.currentTime);
  }

  root.onclick = (e) => {
    const b = e.target.closest("[data-a]");
    if (!b) return;
    hide.poke();
    const a = b.dataset.a;
    if (a === "back") opts.page.close();
    else if (a === "play") {
      if (state.status === Status.ERROR) retry();
      else if (video.paused) video.play().catch(() => {}); else video.pause();
    }
    else if (a === "rw") { video.currentTime -= 10; say(t("player.seek_minus", { n: 10 }), 700); }
    else if (a === "ff") { video.currentTime += 10; say(t("player.seek_plus", { n: 10 }), 700); }
    else if (a === "prev") go(idx - 1);
    else if (a === "next" || a === "gonext") go(idx + 1);
    else if (a === "skip") skipOpening();
    else if (a === "stay") { nextCancelled = true; clearInterval(countTimer); $(".pl-pill").innerHTML = ""; $(".pl-pill").dataset.mode = ""; }
    else if (a === "list") { $(".pl-list").hidden = !$(".pl-list").hidden; renderList(); }
    else if (a === "comments") opts.page.comments();
    else if (a === "dub") m.dub();
    else if (a === "seasons") m.seasons();
    else if (a === "sleep") sleepMenu(say);
    else if (a === "speed") sheet([{ title: t("player.speed"), items: SPEEDS.map((s) => ({
      label: `${s}x${s === 1 ? ` ${t("player.speed_normal")}` : ""}`, on: video.playbackRate === s,
      action: () => { video.playbackRate = s; b.textContent = `${s}x`; } })) }]);
    else if (a === "quality") qualityMenu();
    else if (a === "fs") opts.page.toggleFs();
    else if (a === "zoom") {
      const fill = !root.classList.contains("zoom-fill");
      zoom(fill);
      say(t(fill ? "player.zoom_fill" : "player.zoom_fit"));
    }
  };
  $(".pl-list").onclick = (e) => { const d = e.target.closest("[data-i]"); if (d) { $(".pl-list").hidden = true; go(+d.dataset.i); } };
  function setQuality(q) {
    quality.mode = q;
    if (q === "auto") quality.reset();
    store.setSetting("qualityMode", q);
    const i = q === "auto" ? -1 : levelIndex(q);
    if (hls && (q === "auto" || i >= 0) && hls.levels?.length > 1) {
      // Общий плейлист уже загружен — переключаем уровень без перезагрузки видео
      hls.autoLevelCapping = -1;
      hls.currentLevel = i;
      if (q !== "auto") { curQ = q; updateQualityUi(); }
    } else {
      quality.choose(qualities());
      setSource(video.currentTime);
    }
    say(q === "auto" ? t("player.quality_auto") : t("player.quality_set", { q: qLabel(q) }));
  }

  // --- mp4 (AnimeVost): у файла нет общего плейлиста — при частых подгрузках понижаем качество
  video.addEventListener("waiting", () => {
    if (hls || video.currentTime < 5) return;
    const lower = quality.stalled(qualities(), curQ);
    if (lower) {
      say(t("player.slow_internet", { q: qLabel(lower) }), 2500);
      setSource(video.currentTime);
    }
  });

  load(startPos);
  hide.poke();
  return {
    // Для страницы просмотра: текущая серия, время, перемотка, подсказка, переход на серию
    ep, time: () => video.currentTime, seek: (s) => { video.currentTime = s; }, osd: (text) => say(text), go: (i) => go(i),
    state,
    destroy() {
      progress.destroy();
      sessions.cancel();
      playing(false); clearInterval(countTimer); clearTimeout(holdTimer); clearTimeout(tapTimer);
      hide.destroy(); osd.destroy();
      offs.forEach((off) => off());
      if (masterUrl) URL.revokeObjectURL(masterUrl);
      releaseMedia();
    },
  };
}
