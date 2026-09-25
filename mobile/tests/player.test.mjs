import "./setup.mjs";
import assert from "node:assert/strict";
import { test } from "node:test";
import { setTransport } from "../www/js/core/api/http.js";
import { NoSourceError } from "../www/js/core/errors.js";
import { createNetworkService } from "../www/js/core/network/network.js";
import { normalizeKodikMessage } from "../www/js/features/player/kodik-bridge.js";
import { createSessions } from "../www/js/features/player/playback-session.js";
import { ErrorKind, Status, createPlayerState, nextStatus } from "../www/js/features/player/player-state.js";
import { createProgressTracker } from "../www/js/features/player/progress-tracker.js";
import { kodikUrl, pickKodikPlayer, resolveKodikSource } from "../www/js/services/kodik.js";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------ состояние плеера
test("состояния плеера: загрузка → готово → играет ⇄ пауза, подгрузка, конец, ошибка", () => {
  const S = Status;
  assert.equal(nextStatus(S.IDLE, "load"), S.LOADING);
  assert.equal(nextStatus(S.LOADING, "ready"), S.READY);
  assert.equal(nextStatus(S.READY, "playing"), S.PLAYING);
  assert.equal(nextStatus(S.PLAYING, "waiting"), S.BUFFERING);
  assert.equal(nextStatus(S.BUFFERING, "playing"), S.PLAYING);
  assert.equal(nextStatus(S.PLAYING, "pause"), S.PAUSED);
  assert.equal(nextStatus(S.PAUSED, "waiting"), S.PAUSED, "на паузе подгрузка не показывается");
  assert.equal(nextStatus(S.LOADING, "pause"), S.LOADING, "пауза при смене источника не прячет загрузку");
  assert.equal(nextStatus(S.PLAYING, "ended"), S.ENDED);
  assert.equal(nextStatus(S.ENDED, "pause"), S.ENDED);
  assert.equal(nextStatus(S.PLAYING, "error"), S.ERROR);
  assert.equal(nextStatus(S.ERROR, "playing"), S.ERROR, "после ошибки — только новая загрузка");
  assert.equal(nextStatus(S.ERROR, "load"), S.LOADING);

  const st = createPlayerState();
  const seen = [];
  st.subscribe((s) => seen.push(s.status));
  st.dispatch("load");
  st.dispatch("ready");
  st.dispatch("ready");                                   // без изменений — без события
  st.dispatch("error", { kind: ErrorKind.NO_SOURCE, detail: "test" });
  assert.deepEqual(seen, ["loading", "ready", "error"]);
  assert.equal(st.get().error.kind, "no_source");
  st.dispatch("load");
  assert.equal(st.get().error, null, "новая загрузка сбрасывает ошибку");
});

// ------------------------------------------------------------------ быстрые переключения
/** Как плеер грузит серию: сессия → запрос источника → применить, только если сессия ещё актуальна. */
function makeLoader(resolve) {
  const sessions = createSessions();
  const applied = [];
  return {
    applied,
    sessions,
    async load(ep) {
      const s = sessions.begin();
      try {
        const src = await resolve(ep, s.signal);
        if (!s.active()) return;
        applied.push(src);
      } catch (e) {
        if (!s.active() || e.name === "AbortError") return;
        applied.push(`error:${ep}`);
      }
    },
  };
}

test("быстрая смена серии: ответ серии 1 после серии 2 ничего не меняет, её запрос отменён", async () => {
  const aborted = [];
  const loader = makeLoader((ep, signal) => new Promise((resolve) => {
    signal.addEventListener("abort", () => aborted.push(ep));
    setTimeout(() => resolve(`src:${ep}`), ep === 1 ? 60 : 10);    // серия 1 отвечает медленнее
  }));
  const first = loader.load(1);
  await sleep(2);
  const second = loader.load(2);
  await Promise.all([first, second]);
  assert.deepEqual(loader.applied, ["src:2"]);
  assert.deepEqual(aborted, [1]);
});

test("много переключений подряд: применяется только последнее (серия → озвучка → серия, источник → источник)", async () => {
  const loader = makeLoader((key) => sleep(Math.random() * 20).then(() => `src:${key}`));
  const keys = ["ep1", "ep2:dubA", "ep2:dubB", "ep3", "ep3:srcB"];
  await Promise.all(keys.map((k, i) => sleep(i).then(() => loader.load(k))));
  await sleep(40);
  assert.deepEqual(loader.applied, ["src:ep3:srcB"]);
});

test("ошибка устаревшей серии не показывается", async () => {
  const loader = makeLoader((ep) => (ep === 1 ? sleep(30).then(() => { throw new Error("boom"); }) : Promise.resolve(`src:${ep}`)));
  const a = loader.load(1);
  await loader.load(2);
  await a;
  assert.deepEqual(loader.applied, ["src:2"]);
  loader.sessions.cancel();
  assert.equal(loader.sessions.current, null, "закрыли плеер — сессий нет");
});

// ------------------------------------------------------------------ прогресс
test("прогресс: не на каждый timeupdate — раз в 5 с, на паузе, при сворачивании и закрытии", () => {
  let now = 0;
  const saves = [];
  const doc = Object.assign(new EventTarget(), { visibilityState: "visible" });
  const win = new EventTarget();
  const tracker = createProgressTracker({ save: (s, reason) => saves.push([s.pos, reason]), now: () => now, doc, win });
  let pos = 0;
  tracker.track(() => ({ ep: { key: "1" }, pos, dur: 1440 }));
  for (let i = 0; i < 40; i++) { now += 250; pos += 0.25; tracker.tick(); }   // 10 с просмотра, 40 timeupdate
  assert.deepEqual(saves.map(([, r]) => r), ["interval", "interval"], "40 событий времени → 2 записи");
  tracker.flush("pause");
  doc.visibilityState = "hidden";
  doc.dispatchEvent(new Event("visibilitychange"));
  win.dispatchEvent(new Event("pagehide"));
  tracker.destroy();
  assert.deepEqual(saves.slice(2).map(([, r]) => r), ["pause", "hidden", "leave", "close"]);
  doc.dispatchEvent(new Event("visibilitychange"));
  assert.equal(saves.length, 6, "после закрытия обработчики сняты");
});

test("прогресс: начало серии (< 5 с) и неизвестная длительность не записываются", () => {
  const saves = [];
  const tracker = createProgressTracker({ save: () => saves.push(1), doc: null, win: null });
  tracker.track(() => ({ ep: {}, pos: 3, dur: 1440 }));
  assert.equal(tracker.flush("pause"), false);
  tracker.track(() => ({ ep: {}, pos: 300, dur: 0 }));
  assert.equal(tracker.flush("pause"), false);
  assert.equal(saves.length, 0);
});

// ------------------------------------------------------------------ Kodik
test("сообщения Kodik → события приложения (сырой формат наружу не выходит)", () => {
  assert.deepEqual(normalizeKodikMessage({ key: "kodik_player_time_update", value: 12.5 }), { type: "time", value: 12.5 });
  assert.deepEqual(normalizeKodikMessage({ key: "kodik_player_duration_update", value: 1560 }), { type: "duration", value: 1560 });
  assert.deepEqual(normalizeKodikMessage({ key: "player-rendered" }), { type: "rendered" });
  assert.deepEqual(normalizeKodikMessage({ event: "inited" }), { type: "rendered" });
  assert.deepEqual(normalizeKodikMessage({ event: "adShown" }), { type: "ad-start" });
  assert.deepEqual(normalizeKodikMessage({ title: "currentVastEnded" }), { type: "ad-end" });
  assert.deepEqual(normalizeKodikMessage({ key: "kodik_player_video_ended" }), { type: "ended" });
  assert.equal(normalizeKodikMessage("flow_progress"), null);
  assert.equal(normalizeKodikMessage({ key: "something_else" }), null);
});

test("ссылка Kodik: https, без своего выбора озвучки, позиция через start_from", () => {
  const u = new URL(kodikUrl("//kodikplayer.com/seria/1/abc/720p", { startFrom: 600.7 }));
  assert.equal(u.protocol, "https:");
  assert.equal(u.searchParams.get("translations"), "false");
  assert.equal(u.searchParams.get("start_from"), "600");
  assert.equal(new URL(kodikUrl("https://kodikplayer.com/seria/1/abc/720p", { startFrom: 3 })).searchParams.get("start_from"), null);
  const season = new URL(kodikUrl("//kodikplayer.com/season/9/x/720p?episode=2&start_from=50"));
  assert.equal(season.searchParams.get("only_episode"), "true");
  assert.equal(season.searchParams.get("episode"), "2");
  assert.equal(season.searchParams.get("start_from"), null, "старая позиция из ссылки не переносится");
});

test("выбор плеера команды: точная озвучка, иначе запасная, иначе — нет источника", () => {
  const players = [{ player: "Kodik", src: "//a", team: { id: 1, name: "A" } }, { player: "Kodik", src: "//b", team: { id: 2, name: "B" } },
    { player: "Other", src: "//c", team: { id: 3 } }];
  assert.deepEqual(pickKodikPlayer(players, 2), { src: "//b", team: "B", fallback: false });
  assert.deepEqual(pickKodikPlayer(players, 9), { src: "//a", team: "A", fallback: true });
  assert.equal(pickKodikPlayer([{ player: "Other", src: "//c" }], 1), null);
});

test("источник Kodik: кэш без повторных запросов, отмена, «нет видео»", async () => {
  let calls = 0;
  setTransport(async (req) => {
    calls++;
    await sleep(15);
    if (req.signal.aborted) throw Object.assign(new Error("abort"), { name: "AbortError" });
    if (req.url.endsWith("/episodes/404")) return { status: 200, text: JSON.stringify({ data: { players: [] } }) };
    return { status: 200, text: JSON.stringify({ data: { players: [{ player: "Kodik", src: "//kodikplayer.com/seria/5/h/720p", team: { id: 7, name: "T" } }] } }) };
  });
  const ep = { key: "1", animelib: 555 };
  const [a, b] = await Promise.all([resolveKodikSource(ep, 7), resolveKodikSource(ep, 7)]);
  assert.equal(calls, 1, "одинаковые запросы объединены");
  assert.equal(a.url, b.url);
  assert.equal(a.kind, "iframe");
  await resolveKodikSource(ep, 7, { startFrom: 120 });
  assert.equal(calls, 1, "повторное открытие серии — из кэша");

  const ctrl = new AbortController();
  const p = resolveKodikSource({ key: "2", animelib: 777 }, 7, { signal: ctrl.signal });
  ctrl.abort();
  await assert.rejects(p, { name: "AbortError" });
  await assert.rejects(resolveKodikSource({ key: "3", animelib: 404 }, 7), NoSourceError);
  await assert.rejects(resolveKodikSource({ key: "4" }, 7), NoSourceError);
  const ready = await resolveKodikSource({ key: "5", kodik: "//kodikplayer.com/season/1/x/720p?episode=5" }, 7, { startFrom: 90 });
  assert.match(ready.url, /start_from=90/);
  setTransport(null);
});

// ------------------------------------------------------------------ сеть: никаких фоновых проверок
test("NetworkService не заводит таймеров: ни при запуске, ни при событиях сети", async () => {
  const timers = [];
  const origInterval = globalThis.setInterval;
  globalThis.setInterval = (...a) => { timers.push("interval"); return origInterval(...a); };
  try {
    const events = new EventTarget();
    let measured = 0;
    const svc = createNetworkService({ measure: async () => { measured++; return 20; }, settings: null, events });
    svc.start(async () => "https://cdn/x.m3u8");
    await sleep(5);
    for (let i = 0; i < 5; i++) {
      events.dispatchEvent(new Event("offline"));
      events.dispatchEvent(new Event("online"));
      svc.reportRequest(false);
      svc.reportRequest(true);
    }
    await sleep(5);
    assert.equal(measured, 1, "один замер за запуск, смена сети его не повторяет");
    assert.deepEqual(timers, []);
    svc.stop();
  } finally {
    globalThis.setInterval = origInterval;
  }
});
