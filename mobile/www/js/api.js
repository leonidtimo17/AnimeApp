// Сеть: нативный HTTP Capacitor (без ограничений CORS) + кэш ответов в localStorage.
const Native = window.Capacitor?.Plugins?.CapacitorHttp;
const CACHE_PREFIX = "http:";
const CACHE_MAX = 3_000_000; // ~3 МБ ответов

function qs(params) {
  const parts = [];
  for (const [k, v] of Object.entries(params || {})) {
    if (v === null || v === undefined || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => parts.push(`${encodeURIComponent(k + "[]")}=${encodeURIComponent(x)}`));
    else parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  }
  return parts.join("&");
}

function cacheGet(key, ttl) {
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + key);
    if (!raw) return null;
    const { t, d } = JSON.parse(raw);
    if (ttl !== null && Date.now() - t > ttl * 1000) return null;
    return d;
  } catch { return null; }
}

function cachePut(key, data) {
  try {
    const raw = JSON.stringify({ t: Date.now(), d: data });
    if (raw.length > 600_000) return;
    localStorage.setItem(CACHE_PREFIX + key, raw);
    pruneCache();
  } catch { pruneCache(true); }
}

function pruneCache(force = false) {
  const items = [];
  let total = 0;
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (!k.startsWith(CACHE_PREFIX)) continue;
    const v = localStorage.getItem(k) || "";
    total += v.length;
    items.push([k, v.length, Number((v.match(/"t":(\d+)/) || [])[1] || 0)]);
  }
  if (total < CACHE_MAX && !force) return;
  items.sort((a, b) => a[2] - b[2]);
  for (const [k, len] of items) {
    localStorage.removeItem(k);
    total -= len;
    if (total < CACHE_MAX * 0.6) break;
  }
}

export function clearCache() {
  Object.keys(localStorage).filter((k) => k.startsWith(CACHE_PREFIX)).forEach((k) => localStorage.removeItem(k));
}

/**
 * request(url, {params, headers, form, json, ttl, raw, timeout})
 * form — POST x-www-form-urlencoded, json — POST JSON. ttl — секунды свежести кэша.
 * Без сети отдаёт последний сохранённый ответ.
 */
export async function request(url, opts = {}) {
  const query = qs(opts.params);
  const full = query ? `${url}${url.includes("?") ? "&" : "?"}${query}` : url;
  const key = full + (opts.form ? "|" + JSON.stringify(opts.form) : "");
  const cacheable = !opts.json;
  if (cacheable && opts.ttl) {
    const hit = cacheGet(key, opts.ttl);
    if (hit !== null) return hit;
  }
  const headers = { Accept: "application/json", ...(opts.headers || {}) };
  let body;
  let method = "GET";
  if (opts.form) {
    method = "POST";
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    body = qs(opts.form);
  } else if (opts.json) {
    method = "POST";
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }
  try {
    let data;
    if (Native) {
      // Нативному HTTP форму и JSON передаём объектом — он сам их закодирует.
      const res = await Native.request({ url: full, method, headers, data: opts.form || opts.json || undefined,
        connectTimeout: opts.timeout || 20000,
        readTimeout: opts.timeout || 20000, responseType: opts.raw ? "text" : "json" });
      if (res.status >= 400) throw new Error(`HTTP ${res.status}`);
      data = res.data;
      if (!opts.raw && typeof data === "string") data = JSON.parse(data);
      if (opts.raw && typeof data !== "string") data = JSON.stringify(data);
    } else {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), opts.timeout || 20000);
      const res = await fetch(full, { method, headers, body, signal: ctrl.signal });
      clearTimeout(timer);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = opts.raw ? await res.text() : await res.json();
    }
    if (cacheable && opts.ttl) cachePut(key, data);
    return data;
  } catch (e) {
    if (cacheable) {
      const stale = cacheGet(key, null);
      if (stale !== null && !String(e.message).startsWith("HTTP 4")) return stale;
    }
    throw e;
  }
}

// ------------------------------------------------------------------ AniLibria
const MIRRORS = ["https://anilibria.top", "https://api.anilibria.app"];
let mirror = 0;
export const site = () => MIRRORS[mirror];

export async function al(path, params, ttl = 0) {
  for (let i = 0; i < MIRRORS.length; i++) {
    try {
      return await request(`${site()}/api/v1${path}`, { params, ttl });
    } catch (e) {
      if (String(e.message).startsWith("HTTP")) throw e;
      mirror = (mirror + 1) % MIRRORS.length;
      if (i === MIRRORS.length - 1) throw e;
    }
  }
}

export function mediaUrl(path) {
  if (!path) return null;
  return path.startsWith("http") ? path : site() + path;
}

export function posterUrl(rel) {
  const p = rel?.poster || {};
  return mediaUrl(p.optimized?.src || p.src || p.preview);
}

export const catalog = (f = {}) => al("/anime/catalog/releases", {
  page: f.page || 1, limit: f.limit || 30, "f[search]": f.search, "f[genres]": (f.genres || []).join(",") || null,
  "f[types]": f.types?.length ? f.types : null, "f[years][from_year]": f.yearFrom, "f[years][to_year]": f.yearTo,
  "f[sorting]": f.sorting, "f[publish_statuses]": f.ongoing == null ? null : (f.ongoing ? "IS_ONGOING" : "IS_NOT_ONGOING"),
  "f[seasons]": f.season,
}, 600);

export const latest = () => al("/anime/releases/latest", { limit: 24 }, 300);
// fresh — без кэша: ссылки на видео AniLibria привязаны к сети (VPN/страна) и после её смены не работают
export const release = (id, fresh = false) => al(`/anime/releases/${id}`, null, fresh ? 0 : 120);
export const schedule = () => al("/anime/schedule/week", null, 900);
export const genres = () => al("/anime/catalog/references/genres", null, 86400);
export const years = () => al("/anime/catalog/references/years", null, 86400);
export const franchiseAL = (id) => al(`/anime/franchises/release/${id}`, null, 86400);
export const searchAL = (q) => al("/app/search/releases", { query: q }, 600);
