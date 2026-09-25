// Бесплатный публичный API AniLibria: каталог, релизы, расписание. При сетевом сбое пробуем зеркало.
import { NetworkError } from "../errors.js";
import { request } from "./http.js";

const MIRRORS = ["https://anilibria.top", "https://api.anilibria.app"];
let mirror = 0;
export const site = () => MIRRORS[mirror];

/** Сроки свежести (секунды): справочники живут долго, ссылки на видео не кэшируются. */
export const TTL = { REFERENCES: 86400, FRANCHISE: 86400, CATALOG: 600, SEARCH: 600, SCHEDULE: 900, LATEST: 300,
  RELEASE: 120, PLAYER_SOURCE: 0 };

export async function al(path, params, ttl = 0, signal) {
  for (let i = 0; i < MIRRORS.length; i++) {
    try {
      return await request(`${site()}/api/v1${path}`, { params, ttl, signal });
    } catch (e) {
      if (!(e instanceof NetworkError) || i === MIRRORS.length - 1) throw e;
      mirror = (mirror + 1) % MIRRORS.length;
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

export const catalog = (f = {}, signal) => al("/anime/catalog/releases", {
  page: f.page || 1, limit: f.limit || 30, "f[search]": f.search, "f[genres]": (f.genres || []).join(",") || null,
  "f[types]": f.types?.length ? f.types : null, "f[years][from_year]": f.yearFrom, "f[years][to_year]": f.yearTo,
  "f[sorting]": f.sorting, "f[publish_statuses]": f.ongoing == null ? null : (f.ongoing ? "IS_ONGOING" : "IS_NOT_ONGOING"),
  "f[seasons]": f.season,
}, TTL.CATALOG, signal);

export const latest = (signal) => al("/anime/releases/latest", { limit: 24 }, TTL.LATEST, signal);
// fresh — без кэша: ссылки на видео AniLibria привязаны к сети (VPN/страна) и после её смены не работают
export const release = (id, fresh = false, signal) => al(`/anime/releases/${id}`, null, fresh ? TTL.PLAYER_SOURCE : TTL.RELEASE, signal);
export const schedule = (signal) => al("/anime/schedule/week", null, TTL.SCHEDULE, signal);
export const genres = () => al("/anime/catalog/references/genres", null, TTL.REFERENCES);
export const years = () => al("/anime/catalog/references/years", null, TTL.REFERENCES);
export const franchiseAL = (id) => al(`/anime/franchises/release/${id}`, null, TTL.FRANCHISE);
export const searchAL = (q) => al("/app/search/releases", { query: q }, TTL.SEARCH);

/** Видео для замера скорости: самое высокое качество последней серии свежего релиза. */
export function sampleStream(releases) {
  for (const r of releases || []) {
    const ep = r.latest_episode || {};
    for (const q of ["1080", "720", "480"]) if (ep[`hls_${q}`]) return ep[`hls_${q}`];
  }
  return null;
}
