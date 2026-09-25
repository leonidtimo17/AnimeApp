// Сеть приложения. Нативный HTTP Capacitor (без ограничений CORS), в браузере — fetch.
//
// - одинаковые запросы, которые уже в пути, не дублируются — ответ получат все, кто его ждёт;
// - отмена: каждый вызов может передать signal (страница закрыта — ответ ей не нужен); сам запрос прерывается,
//   только когда он не нужен никому (его могут ждать и другие части приложения);
// - таймаут; повтор только временных ошибок (обрыв, 429/502/503/504) с нарастающей паузой;
// - кэш: память (LRU) → IndexedDB (ttl) → без интернета последний сохранённый ответ любой давности.
import { MemoryCache } from "../cache/memory.js";
import * as persistent from "../cache/persistent.js";
import { ApiError, NetworkError, abortError } from "../errors.js";
import { nativeHttp } from "../../platform/platform.js";

const RETRY_STATUSES = new Set([429, 502, 503, 504]);
const BACKOFF_MS = 600, MAX_BACKOFF_MS = 5000;
export const DEFAULT_TIMEOUT = 20000;

const memory = new MemoryCache({ maxSize: 200, maxWeight: 8_000_000, weigh: (s) => s.length });
const inflight = new Map();   // ключ → {promise, subscribers, controller, done}
export const stats = { sent: 0, deduplicated: 0, memoryHits: 0, diskHits: 0, retries: 0 };

let connectivity = null;      // NetworkService: узнаёт о сети по настоящим запросам
export const setConnectivity = (listener) => { connectivity = listener; };
let transport = defaultTransport;
/** Для тестов: подменить отправку запроса. */
export const setTransport = (fn) => { transport = fn || defaultTransport; };
export const clearMemory = () => memory.clear();

export function qs(params) {
  const parts = [];
  for (const [k, v] of Object.entries(params || {})) {
    if (v === null || v === undefined || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => parts.push(`${encodeURIComponent(k + "[]")}=${encodeURIComponent(x)}`));
    else parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  }
  return parts.join("&");
}

/**
 * request(url, {params, headers, form, json, method, ttl, raw, timeout, retries, signal})
 * form — POST x-www-form-urlencoded, json — POST JSON (method — другой метод, например PATCH). ttl — секунды свежести кэша.
 */
export async function request(url, opts = {}) {
  const query = qs(opts.params);
  const full = query ? `${url}${url.includes("?") ? "&" : "?"}${query}` : url;
  const key = full + (opts.form ? "|" + JSON.stringify(opts.form) : "");
  const cacheable = !opts.json && !opts.method && !opts.headers?.Authorization;
  if (opts.signal?.aborted) throw abortError();

  if (cacheable && opts.ttl) {
    const hit = memory.get(key);
    if (hit !== undefined) { stats.memoryHits++; return parse(hit, opts.raw); }
    const disk = await persistent.get(key, opts.ttl);
    if (disk != null) { stats.diskHits++; memory.set(key, disk, opts.ttl); return parse(disk, opts.raw); }
  }

  if (opts.signal?.aborted) throw abortError();      // отменили, пока смотрели кэш на диске
  let entry = cacheable ? inflight.get(key) : null;
  if (entry) stats.deduplicated++;
  else entry = start(key, full, opts, cacheable);
  entry.subscribers++;
  const text = await follow(entry, opts.signal);
  return parse(text, opts.raw);
}

function start(key, full, opts, cacheable) {
  const controller = new AbortController();
  const entry = { controller, subscribers: 0, done: false };
  entry.promise = (async () => {
    try {
      const text = await sendWithRetry(full, opts, controller.signal);
      if (cacheable && opts.ttl) {
        parse(text, opts.raw);                      // в кэш — только правильный ответ
        memory.set(key, text, opts.ttl);
        persistent.put(key, text);
      }
      connectivity?.reportRequest(true);
      return text;
    } catch (e) {
      if (e.name === "AbortError") throw e;
      const serverDown = e instanceof NetworkError || (e instanceof ApiError && e.status >= 500);
      if (e instanceof NetworkError) connectivity?.reportRequest(false);
      else if (e.status) connectivity?.reportRequest(true);
      if (serverDown && cacheable) {
        const stale = await persistent.get(key, null);    // офлайн — последний сохранённый ответ
        if (stale != null) return stale;
      }
      throw e;
    } finally {
      entry.done = true;
      if (inflight.get(key) === entry) inflight.delete(key);
    }
  })();
  if (cacheable) inflight.set(key, entry);
  return entry;
}

/** Ждать ответа; если signal этого подписчика отменён — отписаться (и прервать запрос, если он больше никому не нужен). */
function follow(entry, signal) {
  if (!signal) return entry.promise;
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      if (--entry.subscribers === 0 && !entry.done) entry.controller.abort();
      return reject(abortError());
    }
    const onAbort = () => {
      reject(abortError());
      if (--entry.subscribers === 0 && !entry.done) entry.controller.abort();
    };
    signal.addEventListener("abort", onAbort, { once: true });
    entry.promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", onAbort));
  });
}

async function sendWithRetry(url, opts, signal) {
  const idempotent = !opts.json && (!opts.method || opts.method === "GET");
  const retries = opts.retries ?? (idempotent ? 1 : 0);
  for (let attempt = 0; ; attempt++) {
    try {
      stats.sent++;
      const res = await transport(buildRequest(url, opts, signal));
      if (res.status >= 400) {
        if (RETRY_STATUSES.has(res.status) && attempt < retries) { await pause(attempt, signal); continue; }
        throw new ApiError(`HTTP ${res.status}`, res.status);
      }
      return res.text;
    } catch (e) {
      if (e.name === "AbortError" || !(e instanceof NetworkError) || !e.transient || attempt >= retries) throw e;
      await pause(attempt, signal);
    }
  }
}

async function pause(attempt, signal) {
  stats.retries++;
  const ms = Math.min(MAX_BACKOFF_MS, BACKOFF_MS * 2 ** attempt);
  await new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => { clearTimeout(t); reject(abortError()); }, { once: true });
  });
}

function buildRequest(url, opts, signal) {
  const headers = { Accept: "application/json", ...(opts.headers || {}) };
  let method = "GET", body, data;
  if (opts.form) {
    method = "POST";
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    body = qs(opts.form);
    data = opts.form;
  } else if (opts.json) {
    method = "POST";
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
    data = opts.json;
  }
  if (opts.method) method = opts.method;
  return { url, method, headers, body, data, raw: !!opts.raw, timeout: opts.timeout || DEFAULT_TIMEOUT, signal };
}

function parse(text, raw) {
  if (raw) return text;
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new ApiError(`Некорректный ответ сервера: ${e.message}`);
  }
}

/** Отправка: нативный HTTP Capacitor на устройстве, fetch в браузере. Возвращает {status, text}. */
async function defaultTransport(req) {
  const Native = nativeHttp();
  if (Native) {
    // Нативному HTTP форму и JSON передаём объектом — он сам их закодирует. Отменить его нельзя —
    // отменённый запрос просто доработает и положит ответ в кэш.
    try {
      const res = await Native.request({ url: req.url, method: req.method, headers: req.headers, data: req.data,
        connectTimeout: req.timeout, readTimeout: req.timeout, responseType: req.raw ? "text" : "json" });
      if (req.signal.aborted) throw abortError();
      return { status: res.status, text: typeof res.data === "string" ? res.data : JSON.stringify(res.data) };
    } catch (e) {
      if (e.name === "AbortError") throw e;
      const msg = e.message || "Нет соединения с сервером";
      throw new NetworkError(msg, { transient: !/time ?out/i.test(msg) });
    }
  }
  const timeout = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; timeout.abort(); }, req.timeout);
  const stop = () => timeout.abort();
  req.signal.addEventListener("abort", stop, { once: true });
  try {
    const res = await fetch(req.url, { method: req.method, headers: req.headers, body: req.body, signal: timeout.signal });
    return { status: res.status, text: await res.text() };
  } catch (e) {
    if (timedOut) throw new NetworkError("Сервер не отвечает — проверьте интернет или VPN", { transient: false });
    if (req.signal.aborted) throw abortError();
    throw new NetworkError(e.message || "Нет соединения");
  } finally {
    clearTimeout(timer);
    req.signal.removeEventListener("abort", stop);
  }
}
