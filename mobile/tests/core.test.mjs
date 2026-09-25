import "./setup.mjs";
import assert from "node:assert/strict";
import { test } from "node:test";
import { MemoryCache } from "../www/js/core/cache/memory.js";
import { request, setConnectivity, setTransport, stats } from "../www/js/core/api/http.js";
import { ApiError, NetworkError } from "../www/js/core/errors.js";
import { createNetworkService } from "../www/js/core/network/network.js";
import { playlistTargets, speedFromSamples } from "../www/js/core/network/bandwidth.js";

const tick = () => new Promise((r) => setTimeout(r, 0));

test("MemoryCache: TTL, LRU и ограничение по весу", () => {
  let now = 0;
  const c = new MemoryCache({ maxSize: 2, ttl: 5, now: () => now });
  c.set("a", 1); c.set("b", 2); c.get("a"); c.set("c", 3);
  assert.equal(c.get("b"), undefined);
  assert.equal(c.get("a"), 1);
  now = 6000;
  assert.equal(c.get("a"), undefined);
  const w = new MemoryCache({ maxWeight: 10, weigh: (s) => s.length });
  w.set("x", "12345"); w.set("y", "123456");
  assert.equal(w.get("x"), undefined);
  w.set("big", "x".repeat(20));
  assert.equal(w.get("big"), undefined);
});

function fakeTransport(handler) {
  const calls = [];
  setTransport(async (req) => {
    calls.push(req);
    return handler(req, calls.length);
  });
  return calls;
}

test("http: одинаковые запросы не дублируются, ответ кэшируется в памяти", async () => {
  const calls = fakeTransport(async () => { await tick(); return { status: 200, text: '{"ok":1}' }; });
  const [a, b] = await Promise.all([request("https://x/dedup", { ttl: 60 }), request("https://x/dedup", { ttl: 60 })]);
  assert.deepEqual(a, { ok: 1 });
  a.changed = true;
  assert.equal(b.changed, undefined, "каждый получает свою копию");
  assert.equal(calls.length, 1);
  await request("https://x/dedup", { ttl: 60 });
  assert.equal(calls.length, 1, "второй раз — из памяти");
});

test("http: отмена одного подписчика не отменяет запрос для других", async () => {
  let release;
  const calls = fakeTransport((req) => new Promise((resolve, reject) => {
    release = () => resolve({ status: 200, text: '{"v":2}' });
    req.signal.addEventListener("abort", () => reject(Object.assign(new Error("abort"), { name: "AbortError" })));
  }));
  const ctrl = new AbortController();
  const first = request("https://x/shared", { signal: ctrl.signal });
  const second = request("https://x/shared");
  ctrl.abort();
  await assert.rejects(first, { name: "AbortError" });
  release();
  assert.deepEqual(await second, { v: 2 });
  assert.equal(calls.length, 1);
});

test("http: запрос, который никому не нужен, прерывается", async () => {
  let aborted = false;
  fakeTransport((req) => new Promise((_resolve, reject) => {
    req.signal.addEventListener("abort", () => { aborted = true; reject(Object.assign(new Error("abort"), { name: "AbortError" })); });
  }));
  const ctrl = new AbortController();
  const p = request("https://x/lonely", { signal: ctrl.signal });
  ctrl.abort();
  await assert.rejects(p, { name: "AbortError" });
  assert.ok(aborted);
});

test("http: повтор временной ошибки, 404 — без повтора", async () => {
  const before = stats.retries;
  let n = 0;
  fakeTransport(() => (++n === 1 ? { status: 503, text: "" } : { status: 200, text: "[1]" }));
  assert.deepEqual(await request("https://x/flaky"), [1]);
  assert.equal(stats.retries, before + 1);
  n = 0;
  fakeTransport(() => { n++; return { status: 404, text: "" }; });
  await assert.rejects(request("https://x/missing"), (e) => e instanceof ApiError && e.status === 404 && e.isClientError);
  assert.equal(n, 1);
});

test("http: неправильный JSON — ошибка; сеть недоступна — NetworkError и отчёт о связи", async () => {
  fakeTransport(() => ({ status: 200, text: "<html>" }));
  await assert.rejects(request("https://x/html", { ttl: 60 }), /Некорректный ответ/);
  const reports = [];
  setConnectivity({ reportRequest: (ok) => reports.push(ok) });
  fakeTransport(() => { throw new NetworkError("нет сети", { transient: false }); });
  await assert.rejects(request("https://x/offline"), NetworkError);
  assert.deepEqual(reports, [false]);
  setConnectivity(null);
  setTransport(null);
});

test("NetworkService: скорость меряется один раз при запуске, дальше — только по просьбе", async () => {
  const urls = [];
  const saved = {};
  const svc = createNetworkService({
    measure: async (u) => { urls.push(u); return 30; },
    settings: { get: (k, d) => saved[k] ?? d, set: (k, v) => { saved[k] = v; } },
    events: new EventTarget(),
  });
  const seen = [];
  svc.subscribe((s) => seen.push(s));
  assert.equal(svc.start(async () => "https://cdn/a.m3u8"), true);
  assert.equal(svc.start(async () => "https://cdn/b.m3u8"), false, "повторный запуск ничего не делает");
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(svc.state.bandwidthMbps, 30);
  assert.equal(svc.measurements, 1);
  assert.deepEqual(urls, ["https://cdn/a.m3u8"]);
  assert.equal(saved.networkBandwidth.mbps, 30);
  assert.ok(seen.some((s) => s.measuring));
  svc.reportRequest(false);
  svc.reportRequest(true);
  assert.equal(svc.measurements, 1, "ошибки и успехи запросов не запускают замер");
  await svc.measureNow(async () => "https://cdn/c.m3u8");
  assert.equal(svc.measurements, 2);
  svc.stop();
});

test("NetworkService: прошлый замер доступен сразу, неудачный замер его не стирает; online/offline — по событиям", async () => {
  const events = new EventTarget();
  const svc = createNetworkService({ measure: async () => null,
    settings: { get: () => ({ mbps: 12, checkedAt: 1 }), set: () => {} }, events });
  assert.equal(svc.state.bandwidthMbps, 12);
  const kinds = [];
  svc.onConnectionChange((k) => kinds.push(k));
  svc.start(async () => null);
  await tick();
  assert.equal(svc.state.bandwidthMbps, 12);
  events.dispatchEvent(new Event("offline"));
  assert.equal(svc.state.isOnline, false);
  events.dispatchEvent(new Event("online"));
  assert.deepEqual(kinds, ["offline", "online"]);
  assert.equal(svc.measurements, 1);
  svc.stop();
});

test("bandwidth: расчёт скорости и разбор плейлиста", () => {
  const s = [[0, 100_000], [500, 200_000], [1000, 4_200_000], [1500, 8_200_000]];
  assert.equal(Math.round(speedFromSamples(s, 8_200_000)), 64);
  assert.equal(speedFromSamples([[0, 10]], 10), null);
  assert.deepEqual(playlistTargets("https://c/a/m.m3u8", "#EXTM3U\n720/i.m3u8\n"), { variant: "https://c/a/720/i.m3u8" });
  assert.deepEqual(playlistTargets("https://c/a/i.m3u8", "#EXTINF:4,\ns1.ts\n#EXTINF:4,\ns2.ts\n#EXTINF:4,\ns3.ts").segments,
    ["https://c/a/s1.ts", "https://c/a/s2.ts"]);
});
