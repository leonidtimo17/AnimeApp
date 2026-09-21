// Плеер: встроенный (HLS/mp4) с фишками как в Кинопоиске и экран плеера Kodik.
import * as store from "./store.js";
import * as src from "./sources.js";
import { I, esc, fa, fmtTime, sheet, toast } from "./ui.js";

const QUALITIES = ["1080", "720", "480"];
let speedCache = { t: 0, mbps: null };

function recommend(mbps, available) {
  const want = mbps == null ? "720" : mbps >= 9 ? "1080" : mbps >= 4 ? "720" : "480";
  const order = QUALITIES.slice(QUALITIES.indexOf(want)).concat(QUALITIES.slice(0, QUALITIES.indexOf(want)).reverse());
  return order.find((q) => available.includes(q)) || available[0];
}

// Замер скорости по кусочку этого же видео (как у онлайн-кинотеатров)
async function measure(url) {
  if (speedCache.mbps != null && Date.now() - speedCache.t < 600_000) return speedCache.mbps;
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
  const ctl = opts.dub.native ? nativePlayer(root, opts) : kodikPlayer(root, opts);
  close.current = (notify = true) => {
    ctl.destroy();
    root.hidden = true;
    root.innerHTML = "";
    close.current = null;
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
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
  const effQ = () => {
    const avail = QUALITIES.filter((q) => ep().streams[q] && !badQ.has(q));
    const pref = quality === "auto" ? recommended : quality;
    if (avail.includes(pref)) return pref;
    // Нужного качества нет — ближайшее ниже, иначе любое доступное
    return avail.find((q) => QUALITIES.indexOf(q) > QUALITIES.indexOf(pref)) || avail[0];
  };
  let osdTimer;
  const osd = (t, ms = 1200) => { const o = $(".pl-osd"); o.textContent = t; o.hidden = false; clearTimeout(osdTimer); osdTimer = setTimeout(() => (o.hidden = true), ms); };
  const poke = () => { root.classList.remove("pl-hidden"); clearTimeout(hideTimer); if (!video.paused) hideTimer = setTimeout(() => root.classList.add("pl-hidden"), 3000); };

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
    const avail = QUALITIES.filter((q) => e.streams[q]);
    if (quality === "auto") {
      $(".spinner").hidden = false;
      if (speedCache.mbps == null) osd("Проверяем скорость интернета…", 4000);
      const mbps = await measure(e.streams["720"] || e.streams["480"] || Object.values(e.streams)[0]);
      if (ep() !== e) return;
      recommended = recommend(mbps, avail);
      if (mbps) osd(`Интернет ~${Math.round(mbps)} Мбит/с → ${recommended}p (рекомендовано)`, 2500);
    }
    setSource(pos);
    renderMarks();
  }

  function setSource(pos) {
    const q = effQ();
    const url = ep().streams[q];
    $("[data-a=quality]").textContent = (quality === "auto" ? "Авто · " : "") + ({ 1080: "FHD", 720: "HD", 480: "SD" }[q]);
    if (hls) { hls.destroy(); hls = null; }
    $(".spinner").hidden = false;
    const startAt = pos > 3 ? pos : 0;
    if (url.split("?")[0].endsWith(".m3u8") && window.Hls?.isSupported()) {
      hls = new Hls({ maxBufferLength: 40, startPosition: startAt, manifestLoadingMaxRetry: 4,
        levelLoadingMaxRetry: 4, fragLoadingMaxRetry: 6, fragLoadingRetryDelay: 1000 });
      hls.on(Hls.Events.ERROR, (_e, data) => {
        if (!data.fatal) return;
        // Обрыв сети — переподключаемся к тому же качеству, а не понижаем его
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) recover();
        else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError();
        else fallback(video.currentTime || startAt);
      });
      hls.loadSource(url);
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
    if (next && next !== q) { osd(`Нет ${q}p, переключаемся на ${next}p`); setSource(pos); }
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
  const onNet = () => { speedCache = { t: 0, mbps: null }; if (!video.paused) frozenSince = Date.now() - 9000; };
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
    const prog = store.progress(rel.id);
    $(".pl-list").innerHTML = eps.map((e, i) => `<div data-i="${i}" class="${i === idx ? "on" : ""}">
      <span>${src.fmtOrd(e.ordinal)} серия${e.name ? " — " + esc(e.name) : ""}</span>
      <span>${prog[e.key]?.watched ? `<i class="fa" style="color:var(--green)">${I.circleCheck}</i>` : ""}</span></div>`).join("");
  }

  function pill() {
    const e = ep();
    const t = video.currentTime, d = video.duration || 0;
    const op = e.opening;
    const inOpening = op?.stop && op.start != null && t >= op.start && t < op.stop - 1.5;
    const inCredits = e.ending?.start ? t >= e.ending.start : d > 300 && d - t <= 45;
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
  video.addEventListener("loadedmetadata", renderMarks);
  video.addEventListener("timeupdate", () => {
    const d = video.duration || 0, t = video.currentTime;
    $(".pl-time").textContent = `${fmtTime(t)} / ${fmtTime(d)}`;
    if (!dragging && d) { $(".pl").style.width = `${(t / d) * 100}%`; $(".kn").style.left = `${(t / d) * 100}%`; }
    if (video.buffered.length && d) $(".buf").style.width = `${(video.buffered.end(video.buffered.length - 1) / d) * 100}%`;
    pill();
  });
  video.addEventListener("ended", () => {
    save("end");
    if (idx < eps.length - 1 && !nextCancelled) go(idx + 1);
    else osd("Это была последняя серия", 3000);
  });
  saveTimer = setInterval(save, 5000);

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
    if (wasSwipe()) return;
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
      root.classList.toggle("pl-hidden");
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
    else if (a === "list") { renderList(); $(".pl-list").hidden = !$(".pl-list").hidden; }
    else if (a === "dub") m.dub();
    else if (a === "seasons") m.seasons();
    else if (a === "speed") sheet([{ title: "Скорость", items: [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2].map((s) => ({
      label: `${s}x${s === 1 ? " (обычная)" : ""}`, on: video.playbackRate === s,
      action: () => { video.playbackRate = s; b.textContent = `${s}x`; } })) }]);
    else if (a === "quality") {
      const avail = QUALITIES.filter((q) => ep().streams[q]);
      sheet([{ title: "Качество", items: [
        { label: `Авто — по скорости интернета${speedCache.mbps ? ` · ${Math.round(speedCache.mbps)} Мбит/с` : ""}`,
          on: quality === "auto", action: () => setQuality("auto") },
        ...avail.map((q) => ({ label: `${q}p${q === recommended ? "  · рекомендовано" : ""}`, on: quality === q,
          action: () => setQuality(q) })),
      ] }, { title: "Настройки", items: [{ label: "Автопропуск заставки", on: store.setting("autoskip", false),
        action: () => store.setSetting("autoskip", !store.setting("autoskip", false)) }] }]);
    } else if (a === "fs") {
      if (document.fullscreenElement) document.exitFullscreen();
      else root.requestFullscreen?.().then(() => screen.orientation?.lock?.("landscape").catch(() => {})).catch(() => {});
    }
  };
  $(".pl-list").onclick = (e) => { const d = e.target.closest("[data-i]"); if (d) { go(+d.dataset.i); $(".pl-list").hidden = true; } };
  function setQuality(q) {
    quality = q;
    store.setSetting("qualityMode", q);
    setSource(video.currentTime);
    osd(q === "auto" ? "Авто" : `Качество ${q}p`);
  }

  renderList();
  load(startPos);
  poke();
  return {
    destroy() {
      save(); clearInterval(saveTimer); clearInterval(countTimer); clearTimeout(hideTimer); clearInterval(watchdog);
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
  // Своя панель под видео: поверх iframe Kodik ставить нельзя — он забирает касания себе.
  root.innerHTML = `
    <div class="pl-top solid">
      <button class="pl-btn" data-a="back">${fa("back")}</button>
      <div class="ttl"><b>${esc(src.title(rel))}</b><small class="sub"></small></div>
      <button class="pl-btn" data-a="seasons" ${opts.seasons?.length ? "" : "hidden"}>${fa("layers")}</button>
      <button class="pl-btn txt" data-a="dub">${fa("mic")} ${esc(opts.dub.name)}</button>
    </div>
    <iframe class="kodik" allow="autoplay; fullscreen" allowfullscreen></iframe>
    <div class="spinner"></div>
    <div class="pl-osd" hidden></div>
    <div class="pl-pill kpill"></div>
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
      </div>
    </div>`;
  const $ = (s) => root.querySelector(s);
  const frame = $("iframe");
  const m = menus(opts, () => [eps[idx].key, pos]);
  swipeToClose(root, $(".pl-top")); // свайп вниз по верхней панели — закрыть
  const cmd = (v) => frame.contentWindow?.postMessage({ key: "kodik_player_api", value: v }, "*");
  const osd = (t) => { const o = $(".pl-osd"); o.textContent = t; o.hidden = false; clearTimeout(osdTimer); osdTimer = setTimeout(() => (o.hidden = true), 1000); };
  const setAd = (on) => root.classList.toggle("k-ad", on);

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
      const r = await src.kodikSource(e.animelib, team);
      $(".sub").textContent = `${src.fmtOrd(e.ordinal)} серия · ${r.team || opts.dub.name}${r.fallback ? " (выбранной озвучки нет — другая)" : ""}`;
      frame.src = r.src;
    } catch (err) {
      $(".spinner").hidden = true;
      toast(err.message);
    }
  }
  function countdown() {
    if (idx >= eps.length - 1 || countTimer) return;
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
      if (seekTo > 5) { const s = seekTo; seekTo = 0; setTimeout(() => { cmd({ method: "seek", seconds: s }); osd(`Продолжаем с ${fmtTime(s)}`); }, 600); }
    } else if (d.key === "kodik_player_time_update") {
      pos = d.value; playing = true; started = true; userPaused = false; lastTick = Date.now(); setAd(false); render(); save(false);
      if (dur > 300 && dur - pos < 40) countdown();
    } else if (d.key === "kodik_player_play") { playing = true; userPaused = false; lastTick = Date.now(); render(); }
    else if (d.key === "kodik_player_pause") { playing = false; userPaused = true; render(); save(true); }
    else if (d.key === "kodik_player_video_ended") { pos = dur; playing = false; render(); save(true); countdown(); }
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
    else if (a === "skip85") { seek(pos + 85); osd("Заставка пропущена"); }
    else if (a === "eps") sheet([{ title: "Серии", items: eps.map((ep, i) => ({ label: `${src.fmtOrd(ep.ordinal)} серия${ep.name ? " — " + ep.name : ""}`,
      on: i === idx, hint: store.progress(rel.id)[ep.key]?.watched ? "✓" : "", action: () => load(i, null) })) }]);
    else if (a === "dub") m.dub();
    else if (a === "seasons") m.seasons();
  };
  load(idx, startPos);
  return { destroy() {
    save(true); clearInterval(countTimer); clearInterval(watchdog); window.removeEventListener("message", onMsg);
    window.removeEventListener("online", onNet); navigator.connection?.removeEventListener?.("change", onNet);
    frame.src = "about:blank";
  } };
}
