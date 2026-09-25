// Плеер Kodik: его встраиваемый плеер (iframe) на весь блок видео, наши панели — поверх него сверху и снизу.
//
// Надёжность:
// - каждая загрузка серии (смена серии, озвучки, повтор) — новая сессия: прошлый запрос отменяется, а его поздний
//   ответ ничего не меняет; каждый раз — новое окно Kodik, сообщения старого не принимаются;
// - позиция — параметром start_from в ссылке (Kodik сам начинает с нужного места);
// - «подгрузка» видна по отсутствию обновлений времени; зависло надолго — до 2 переподключений, потом ошибка
//   с кнопкой «Повторить»; вернулся интернет — одна попытка сама;
// - прогресс — раз в 5 с, на паузе, при смене серии, при сворачивании и в конце серии.
// Касания по видео забирает iframe, поэтому спрятанные панели остаются «прозрачными кнопками»:
// первое касание по краю экрана только показывает управление.
import * as store from "../../core/state/store.js";
import { NetworkError, NoSourceError, isAbort } from "../../core/errors.js";
import { fa } from "../../components/Icons.js";
import { sheetOpen } from "../../components/Sheet.js";
import { createAutoHide } from "../../components/player/AutoHide.js";
import { createOsd } from "../../components/player/Osd.js";
import { createPlayerOverlay } from "../../components/player/PlayerOverlay.js";
import { createProgressBar } from "../../components/player/ProgressBar.js";
import { title } from "../../domain/titles.js";
import { t } from "../../i18n/index.js";
import { esc } from "../../utils/dom.js";
import { fmtOrd, fmtTime } from "../../utils/format.js";
import { network } from "../../app/network.js";
import * as platform from "../../platform/platform.js";
import { resolveKodikSource } from "../../services/kodik.js";
import * as src from "../../services/sources.js";
import { swipeToClose, zoomer } from "./gestures.js";
import { hotkeys } from "./hotkeys.js";
import { createKodikFrame } from "./kodik-bridge.js";
import { episodeList, menus, startIndex } from "./menus.js";
import { ErrorKind, Status, createPlayerState } from "./player-state.js";
import { createSessions } from "./playback-session.js";
import { createProgressTracker } from "./progress-tracker.js";
import { afterEpisode, attachSleep, sleepAfterEpisode, sleepMenu } from "./sleep-timer.js";

const HIDE_MS = 5000;
const STALL_MS = 2500;          // нет обновлений времени — «подгружаем видео»
const FROZEN_MS = 15000;        // стоит так долго — переподключаемся
const MAX_RECONNECTS = 2;       // потом — ошибка и кнопка «Повторить», без бесконечных повторов
const RENDER_TIMEOUT_MS = 20000;
const WAKE_TRIES = 6, WAKE_EVERY_MS = 1500;   // команда play до первого ответа плеера // плеер Kodik не отрисовался — вероятно, мешает блокировка рекламы

export function kodikPlayer(root, opts) {
  const { rel, eps } = opts;
  let [idx, startPos] = startIndex(opts);
  const team = opts.dub.id.split(":")[1];
  let pos = 0, dur = 0, playing = false, userPaused = false, ad = false, rendered = false, seekTo = 0;
  let countTimer = null, stallTimer = null, frozenTimer = null, renderTimer = null, wakeTimer = null, reconnects = 0;
  const offs = [];
  root.classList.add("kp");
  root.innerHTML = `
    <div class="pl-top">
      <button class="pl-btn" data-a="back" data-i18n-aria="common.back">${fa("back")}</button>
      <div class="ttl"><b>${esc(title(rel))}</b><small class="sub"></small></div>
      <button class="pl-btn" data-a="seasons" ${opts.seasons?.length ? "" : "hidden"} data-i18n-aria="player.seasons">${fa("layers")}</button>
      <button class="pl-btn txt" data-a="dub">${fa("mic")} ${esc(opts.dub.name)}</button>
      <button class="pl-btn txt" data-a="adblock" ${platform.hasAdblock() ? "" : "hidden"}></button>
      <button class="pl-btn" data-a="comments" data-i18n-aria="player.comments">${fa("comments")}</button>
    </div>
    <div class="pl-overlay" hidden></div>
    <div class="pl-osd" hidden></div>
    <div class="pl-pill kpill"></div>
    <div class="pl-list kplist" hidden></div>
    <div class="kpanel">
      <div class="seek"></div>
      <div class="pl-row">
        <button class="pl-btn" data-a="prev" data-i18n-aria="player.previous_episode">${fa("prev")}</button>
        <button class="pl-btn ctl" data-a="rw" data-i18n-aria="player.rewind">${fa("rewind")}</button>
        <button class="pl-btn ctl" data-a="play" data-i18n-aria="player.play">${fa("play")}</button>
        <button class="pl-btn ctl" data-a="ff" data-i18n-aria="player.forward">${fa("forward")}</button>
        <button class="pl-btn" data-a="next" data-i18n-aria="player.next_episode">${fa("next")}</button>
        <span class="pl-time">0:00 / 0:00</span>
        <button class="pl-btn txt" data-a="eps"></button>
        <span class="sp"></span>
        <span class="kad">${t("player.ad_playing")}</span>
        <button class="pl-btn txt ctl kskip" data-a="skip85">${fa("fwd")} ${t("player.skip_opening")}</button>
        <button class="pl-btn" data-a="sleep" data-i18n-aria="player.sleep">${fa("moon")}</button>
        <button class="pl-btn" data-a="zoom" data-i18n-aria="player.zoom">${fa("zoom")}</button>
        <button class="pl-btn" data-a="fs" data-i18n-aria="player.fullscreen">${fa("expand")}</button>
      </div>
    </div>`;
  root.querySelectorAll("[data-i18n-aria]").forEach((el) => el.setAttribute("aria-label", t(el.dataset.i18nAria)));
  const $ = (s) => root.querySelector(s);
  const m = menus(opts, () => [eps[idx].key, pos]);
  swipeToClose(opts.page.root, $(".pl-top"), opts.page.close); // свайп вниз по верхней панели — закрыть
  const cp = opts.cp;
  const osd = createOsd($(".pl-osd"));
  const say = (text, ms = 1000) => osd.show(text, ms);
  const state = createPlayerState();
  const overlay = createPlayerOverlay($(".pl-overlay"), { onRetry: () => retry(), onOtherDub: () => m.dub() });
  offs.push(state.subscribe((st) => { root.dataset.status = st.status; overlay.render(st); renderPlay(); }));
  const sessions = createSessions();
  const progress = createProgressTracker({
    save: ({ ep, pos: p, dur: d }) => store.saveProgress(rel.id, ep.key, ep.ordinal, p, d, null),
  });
  progress.track(() => ({ ep: eps[idx], pos, dur }));
  const bar = createProgressBar($(".seek"), {
    onSeek: (s) => seek(s),
    onScrub: (s) => { $(".pl-time").textContent = `${fmtTime(s)} / ${fmtTime(dur)}`; hide.poke(); },
  });
  const bridge = createKodikFrame(root, onEvent);

  // Блокировка рекламы: пока открыт Kodik, приложение пропускает только его серверы (нативный фильтр Android)
  let adblock = platform.hasAdblock() && store.setting("kodikAdblock", true);
  const setAdblock = (on) => {
    adblock = on;
    platform.adblock(on);
    $("[data-a=adblock]").innerHTML = `${on ? fa("check") : fa("plus")} ${t("player.adblock")}`;
    $("[data-a=adblock]").classList.toggle("on", on);
  };
  if (platform.hasAdblock()) setAdblock(adblock);

  const hide = createAutoHide(root, { delay: HIDE_MS,
    canHide: () => playing && !bar.dragging && !ad && !sheetOpen() });
  // Касание по спрятанной панели — только показать её, без нажатия кнопки под пальцем
  const onPointerDown = (e) => {
    if (hide.hidden) {
      root.dataset.reveal = "1";
      if (e.target.closest(".pl-top, .kpanel")) { e.stopPropagation(); e.preventDefault(); hide.poke(); }
      return;
    }
    delete root.dataset.reveal;
    if (e.target.closest(".pl-top, .kpanel, .pl-pill")) hide.poke();
  };
  root.addEventListener("pointerdown", onPointerDown, true);
  root.addEventListener("click", (e) => { if (root.dataset.reveal) { delete root.dataset.reveal; e.stopPropagation(); } }, true);
  // Масштаб применяется к текущему окну Kodik (оно новое на каждую серию)
  const applyZoom = (fill) => zoomer(root, bridge.element || { style: {} }, true)(fill);
  const onResize = () => applyZoom(root.classList.contains("zoom-fill"));
  window.addEventListener("resize", onResize);
  offs.push(() => window.removeEventListener("resize", onResize));

  // ------------------------------------------------------------------ отрисовка
  function renderPlay() {
    const on = state.status === Status.PLAYING || state.status === Status.BUFFERING;
    $("[data-a=play]").innerHTML = on ? fa("pause") : fa("play");
    $("[data-a=play]").setAttribute("aria-label", t(on ? "player.pause" : "player.play"));
  }
  function renderTime() {
    $(".pl-time").textContent = `${fmtTime(pos)} / ${fmtTime(dur)}`;
    bar.set(pos, dur);
  }
  const setAd = (on) => { ad = on; root.classList.toggle("k-ad", on); if (on) hide.poke(); };

  // ------------------------------------------------------------------ загрузка серии
  function clearEpisodeTimers() {
    clearInterval(countTimer); clearTimeout(stallTimer); clearTimeout(frozenTimer); clearTimeout(renderTimer); clearTimeout(wakeTimer);
    countTimer = stallTimer = frozenTimer = renderTimer = wakeTimer = null;
  }

  async function load(i, start) {
    progress.flush("switch");                // позиция прошлой серии
    const s = sessions.begin();
    clearEpisodeTimers();
    idx = i; pos = 0; dur = 0; playing = false; userPaused = false; rendered = false; seekTo = start || 0;
    setAd(false);
    $(".pl-pill").innerHTML = "";
    const e = eps[i];
    $("[data-a=eps]").textContent = t("player.episode_n", { n: fmtOrd(e.ordinal) });
    $(".sub").textContent = t("player.episode_n", { n: fmtOrd(e.ordinal) });
    $("[data-a=prev]").disabled = i === 0;
    $("[data-a=next]").disabled = i >= eps.length - 1;
    cp.episodeChanged();
    opts.page.episode(i);
    renderTime();
    bridge.unload();
    state.dispatch("load");
    try {
      const source = await resolveKodikSource(e, team, { signal: s.signal, startFrom: seekTo, fallbackName: opts.dub.name });
      if (!s.active()) return;                                   // уже выбрана другая серия
      $(".sub").textContent = `${t("player.episode_n", { n: fmtOrd(e.ordinal) })} · ${source.team || opts.dub.name}`
        + (source.fallback ? ` ${t("player.fallback_translation")}` : "");
      bridge.load(source.url);
      onResize();
      renderTimer = setTimeout(() => s.active() && notRendered(), RENDER_TIMEOUT_MS);
    } catch (err) {
      if (!s.active() || isAbort(err)) return;
      fail(err instanceof NoSourceError ? ErrorKind.NO_SOURCE : err instanceof NetworkError ? netKind() : ErrorKind.SOURCE, err);
    }
  }

  const netKind = () => (network.state.isOnline ? ErrorKind.NETWORK : ErrorKind.OFFLINE);
  function fail(kind, detail) {
    clearEpisodeTimers();
    playing = false;
    bridge.unload();
    state.dispatch("error", { kind, detail });
    hide.poke();
  }

  /** Плеер Kodik так и не отрисовался: с блокировкой рекламы — выключаем её для этого просмотра, иначе — ошибка. */
  function notRendered() {
    if (adblock) {
      setAdblock(false);
      say(t("player.adblock_failed"), 3000);
      load(idx, seekTo);
    } else {
      fail(netKind(), new Error("Kodik player did not render"));
    }
  }

  /**
   * Автозапуск. Плеер Kodik спит, пока не получит первую команду play (или касание): до неё он не присылает
   * даже «player-rendered». Поэтому play — сразу после загрузки окна и ещё несколько раз, пока плеер не ответит.
   */
  function wake(s, attempt) {
    if (!s.active() || rendered) return;
    bridge.send("play");
    if (attempt < WAKE_TRIES) wakeTimer = setTimeout(() => wake(s, attempt + 1), WAKE_EVERY_MS);
  }

  /** «Повторить»: та же серия с того же места. */
  function retry() {
    reconnects = 0;
    load(idx, pos || seekTo || startPos);
  }

  // ------------------------------------------------------------------ события Kodik
  function onEvent(e) {
    const s = sessions.current;
    if (!s) return;
    switch (e.type) {
      case "loaded":
        wake(s, 0);
        break;
      case "rendered":
        if (!rendered) {
          rendered = true;
          clearTimeout(renderTimer); clearTimeout(wakeTimer);
        }
        break;
      case "duration":
        dur = e.value;
        state.dispatch("ready");
        renderTime();
        fillSkips(s);
        break;
      case "time":
        onTime(e.value);
        break;
      case "play":
        playing = true; userPaused = false;
        state.dispatch("play");
        armStall();
        break;
      case "pause":
        playing = false; userPaused = true;
        clearTimeout(stallTimer); clearTimeout(frozenTimer);
        state.dispatch("pause");
        progress.flush("pause");
        hide.poke();
        break;
      case "ended":
        pos = dur; playing = false;
        clearTimeout(stallTimer); clearTimeout(frozenTimer);
        renderTime();
        state.dispatch("ended");
        progress.flush("end");
        if (!sleepAfterEpisode(say)) countdown();
        break;
      case "ad-start": setAd(true); break;
      case "ad-end": setAd(false); break;
      default: break;
    }
  }

  function onTime(value) {
    pos = value;
    playing = true; userPaused = false;
    if (ad) setAd(false);
    if (state.status !== Status.PLAYING) state.dispatch("playing");
    reconnects = 0;
    // start_from не сработал (старые ссылки Kodik) — перематываем один раз
    if (seekTo > 5 && pos < seekTo - 10) { const target = seekTo; seekTo = 0; seek(target); say(t("player.resume", { time: fmtTime(target) })); }
    else if (seekTo > 5) { say(t("player.resume", { time: fmtTime(seekTo) }), 2000); seekTo = 0; }
    renderTime();
    progress.tick();
    armStall();
    const ep = eps[idx];
    if (ep.ending?.start ? pos >= ep.ending.start : dur > 300 && dur - pos < 40) countdown();
    // Автопропуск заставки (настройка встроенного плеера), когда её время известно
    const op = ep.opening;
    if (op?.stop && op.start != null && pos >= op.start && pos < op.stop - 2 && store.setting("autoskip", false) && !ep._skipped) {
      ep._skipped = true; seek(op.stop); say(t("player.opening_skipped"));
    }
  }

  /** Обновления времени перестали приходить: через STALL_MS — «подгружаем», через FROZEN_MS — переподключение. */
  function armStall() {
    clearTimeout(stallTimer); clearTimeout(frozenTimer);
    if (!playing || userPaused || ad) return;
    stallTimer = setTimeout(() => { if (playing && !ad) state.dispatch("waiting"); }, STALL_MS);
    frozenTimer = setTimeout(() => {
      if (!playing || userPaused || ad) return;
      if (reconnects >= MAX_RECONNECTS) return fail(netKind(), new Error("Kodik: video frozen"));
      reconnects++;
      say(t("player.reconnecting"), 2500);
      load(idx, pos);
    }, FROZEN_MS);
  }

  async function fillSkips(s) {
    const ep = eps[idx];
    if (ep.opening?.stop && ep.ending?.start) return;
    const sk = await src.skipTimes(rel.shikimori?.id, ep.ordinal, dur);
    if (!sk || !s.active()) return;
    if (!ep.opening?.stop && sk.opening) ep.opening = sk.opening;
    if (!ep.ending?.start && sk.ending) ep.ending = sk.ending;
  }

  function seek(s) {
    s = Math.max(0, Math.min(dur ? dur - 1 : s, s));
    bridge.send("seek", { seconds: Math.floor(s) });
    pos = s;
    renderTime();
  }

  function countdown() {
    if (idx >= eps.length - 1 || countTimer || afterEpisode()) return;
    let n = 10;
    const box = $(".pl-pill");
    box.innerHTML = `<button data-a="stay">${t("player.watch_credits")}</button><button class="acc" data-a="next">${t("player.next_in", { n })}</button>`;
    countTimer = setInterval(() => {
      n--;
      if (n <= 0) { clearInterval(countTimer); countTimer = null; load(idx + 1, 0); }
      else { const b = box.querySelector(".acc"); if (b) b.textContent = t("player.next_in", { n }); }
    }, 1000);
  }

  // ------------------------------------------------------------------ сеть
  // Вернулся интернет, а серия остановилась с сетевой ошибкой — одна попытка сама (без бесконечных повторов)
  offs.push(network.onConnectionChange((kind) => {
    if (kind === "online" && state.status === Status.ERROR && [ErrorKind.NETWORK, ErrorKind.OFFLINE].includes(state.get().error?.kind)) retry();
  }));

  // ------------------------------------------------------------------ кнопки
  root.onclick = (e) => {
    const b = e.target.closest("[data-a]");
    if (!b) return;
    const a = b.dataset.a;
    if (a === "back") opts.page.close();
    else if (a === "play") {
      if (state.status === Status.ERROR) return retry();
      bridge.send(playing ? "pause" : "play");
    }
    else if (a === "rw") { seek(pos - 10); say(t("player.seek_minus", { n: 10 })); }
    else if (a === "ff") { seek(pos + 10); say(t("player.seek_plus", { n: 10 })); }
    else if (a === "prev") load(idx - 1, null);
    else if (a === "next") load(idx + 1, null);
    else if (a === "stay") { clearInterval(countTimer); countTimer = null; $(".pl-pill").innerHTML = ""; }
    else if (a === "skip85") {
      // Точное время заставки знает YummyAnime/AniSkip; иначе — стандартные 85 секунд
      const op = eps[idx].opening;
      seek(op?.stop && pos < op.stop ? op.stop : pos + 85);
      say(t("player.opening_skipped"));
    }
    else if (a === "eps") {
      const list = $(".kplist");
      list.hidden = !list.hidden;
      if (!list.hidden) {
        list.innerHTML = episodeList(opts, idx);
        list.querySelector(".on")?.scrollIntoView({ block: "center" });
      }
    }
    else if (a === "dub") m.dub();
    else if (a === "seasons") m.seasons();
    else if (a === "fs") opts.page.toggleFs();
    else if (a === "zoom") { const fill = !root.classList.contains("zoom-fill"); applyZoom(fill); say(t(fill ? "player.zoom_fill" : "player.zoom_fit")); }
    else if (a === "sleep") sleepMenu(say);
    else if (a === "comments") opts.page.comments();
    else if (a === "adblock") {
      store.setSetting("kodikAdblock", !adblock);
      setAdblock(!adblock);
      say(t(adblock ? "player.adblock_on" : "player.adblock_off"));
      load(idx, pos);  // перезагружаем серию с того же места, чтобы настройка подействовала
    }
    hide.poke();
  };
  $(".kplist").addEventListener("click", (ev) => {
    const it = ev.target.closest("[data-i]");
    if (!it) return;
    ev.stopPropagation();
    $(".kplist").hidden = true;
    load(+it.dataset.i, null);
  });

  offs.push(attachSleep(root, () => bridge.send("pause"), say));
  let kvol = 1, kmuted = false;
  offs.push(hotkeys(root, {
    osd: say, isFs: opts.page.isFs,
    seek: (s) => { seek(pos + s); say(t(s > 0 ? "player.seek_plus" : "player.seek_minus", { n: Math.abs(s) })); },
    volume: (d) => {
      kvol = Math.min(1, Math.max(0, Math.round((kvol + d) * 10) / 10));
      bridge.send("volume", { volume: kvol });
      say(t("player.volume", { n: Math.round(kvol * 100) }));
    },
    mute: () => { kmuted = !kmuted; bridge.send(kmuted ? "mute" : "unmute"); say(t(kmuted ? "player.muted" : "player.unmuted")); },
    skip: () => root.querySelector("[data-a=skip85]").click(),
    percent: (f) => { if (dur) seek(f * dur); },
  }));
  // После касания видео фокус клавиатуры уходит внутрь iframe Kodik, и клавиши туда не доходят — забираем фокус обратно
  const onBlur = () => setTimeout(() => {
    if (bridge.element && document.activeElement === bridge.element) { bridge.element.blur(); window.focus(); }
  }, 0);
  window.addEventListener("blur", onBlur);
  offs.push(() => window.removeEventListener("blur", onBlur));

  applyZoom(store.setting("zoomFill", false));
  load(idx, startPos);
  hide.poke();
  return {
    ep: () => eps[idx], time: () => pos, seek: (s) => seek(s), osd: (text) => say(text), go: (i) => load(i, null),
    state,
    destroy() {
      progress.destroy();
      sessions.cancel();
      clearEpisodeTimers();
      hide.destroy();
      osd.destroy();
      offs.forEach((off) => off());
      if (platform.hasAdblock()) platform.adblock(false);
      bridge.destroy();
    },
  };
}
