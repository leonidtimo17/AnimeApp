// Источники серий и озвучек, каталог Shikimori, франшизы (тот же порядок работы, что в ПК-версии).
//
// Один и тот же поиск озвучек не запускается дважды: страница тайтла и кнопка «Смотреть» ждут один результат.
// Кэши в памяти ограничены по размеру и времени.
import * as api from "../core/api/anilibria.js";
import { request } from "../core/api/http.js";
import { MemoryCache } from "../core/cache/memory.js";
import * as store from "../core/state/store.js";
import { chooseDub as pickDub, sortDubs } from "../domain/dubs.js";
import { parseOrdinal } from "../domain/episodes.js";
import { matchKeys, norm, sameDub, searchQueries, stripBB, title, titleKey } from "../domain/titles.js";
import { fmtOrd } from "../utils/format.js";
import { t } from "../i18n/index.js";
import { NoSourceError } from "../core/errors.js";

export const ANIMELIB_OFFSET = 100_000_000;
export const SHIKI_OFFSET = 200_000_000;
const SHIKI = "https://shikimori.io";
const ANIMELIB = "https://api.cdnlibs.org/api";
const ANIMELIB_H = { "Site-Id": "5" };
const VOST = "https://api.animetop.info/v1";
const YANI = "https://api.yani.tv";
/** Тип тайтла Shikimori → подпись (anime.kinds.*). */
const kindLabel = (kind) => (kind && ["tv", "movie", "ova", "ona", "special", "tv_special"].includes(kind) ? t(`anime.kinds.${kind}`) : "");
const RATINGS = { g: "0+", pg: "6+", pg_13: "13+", r: "16+", r_plus: "18+", rx: "18+" };
const HIDDEN_KINDS = ["music", "pv", "cm"];
const TTL = { SEARCH: 3600, SHIKI: 3600, FRANCHISE: 86400, VOST: 900, YANI: 1800, ANIMELIB_EPS: 1800, ANISKIP: 7 * 86400 };

export const isShiki = (id) => id >= SHIKI_OFFSET;
export const isAnimeLib = (id) => id >= ANIMELIB_OFFSET && id < SHIKI_OFFSET;
export const isExternal = (id) => id >= ANIMELIB_OFFSET;
export { title, norm };

/** Повторные вызовы с тем же ключом, пока первый не закончился, получают тот же Promise. */
function shared(fn) {
  const pending = new Map();
  return (key, ...args) => {
    if (pending.has(key)) return pending.get(key);
    const p = fn(...args).finally(() => pending.delete(key));
    pending.set(key, p);
    return p;
  };
}

export function anilibriaEpisodes(rel) {
  const eps = [];
  for (const e of rel.episodes || []) {
    const streams = {};
    for (const q of ["1080", "720", "480"]) if (e[`hls_${q}`]) streams[q] = e[`hls_${q}`];
    if (!Object.keys(streams).length) continue;
    const o = parseOrdinal(e.ordinal, eps.length + 1);
    const pv = e.preview || {};
    eps.push({ key: fmtOrd(o), ordinal: o, name: e.name || e.name_english, duration: e.duration,
      opening: e.opening, ending: e.ending, streams, animelib: null,
      preview: api.mediaUrl(pv.optimized?.preview || pv.preview || pv.src) });
  }
  return eps;
}

// ------------------------------------------------------------------ Shikimori (полный каталог)
export function shikiItem(x) {
  const img = x.image?.original || "";
  const year = (x.aired_on || "").slice(0, 4);
  const rel = {
    id: SHIKI_OFFSET + x.id, name: { main: x.russian || x.name, english: x.name },
    poster: { src: img && !img.includes("missing") ? SHIKI + img : null },
    year: +year || null, type: { description: kindLabel(x.kind) }, episodes_total: x.episodes || null,
    is_ongoing: x.status === "ongoing", shikimori: { id: x.id, rating: x.score ? +x.score : null }, episodes: [],
  };
  const sub = [year, kindLabel(x.kind), x.episodes ? t("anime.eps_short", { n: x.episodes }) : ""].filter(Boolean).join(" · ");
  return { id: rel.id, title: rel.name.main, subtitle: sub, poster: rel.poster.src,
    badge: x.status === "anons" ? t("anime.announce_badge") : null, release: rel };
}

const KIND_RANK = { tv: 0, movie: 1, ona: 2, ova: 3, tv_special: 4, special: 5 };
const SHIKI_SEARCH_LIMIT = 50;

/** Порядок: точное совпадение названия → сериалы, фильмы, потом спешлы → по дате выхода. */
export function sortShikiResults(q, items) {
  const key = titleKey(q);
  const exact = (x) => ([x.russian, x.name].some((n) => titleKey(n) === key) ? 0 : 1);
  return (items || []).filter((x) => !HIDDEN_KINDS.includes(x.kind))
    .map((x, i) => ({ x, i }))
    .sort((a, b) => exact(a.x) - exact(b.x) || (KIND_RANK[a.x.kind] ?? 6) - (KIND_RANK[b.x.kind] ?? 6)
      || (a.x.aired_on || "9999").localeCompare(b.x.aired_on || "9999") || a.i - b.i)
    .map(({ x }) => x);
}

/** Возвращает массив найденного; в свойстве hasMore — есть ли следующая страница. */
export async function shikiSearch(q, page = 1, signal) {
  const items = await request(`${SHIKI}/api/animes`, { params: { search: q, limit: SHIKI_SEARCH_LIMIT, page }, ttl: TTL.SEARCH, signal });
  const out = sortShikiResults(q, items);
  out.hasMore = (items || []).length >= SHIKI_SEARCH_LIMIT;
  return out;
}

/** Карточка тайтла Shikimori — один запрос на всех: страница тайтла, предстоящие серии, тема обсуждения. */
export const shikiAnime = (sid, signal) => request(`${SHIKI}/api/animes/${sid}`, { ttl: TTL.SHIKI, signal });

export async function shikiRelease(id, signal) {
  const x = await shikiAnime(id - SHIKI_OFFSET, signal);
  const rel = shikiItem(x).release;
  rel.name.alternative = (x.english || [])[0];
  rel.description = stripBB(x.description);
  rel.genres = (x.genres || []).map((g) => ({ name: g.russian || g.name }));
  rel.age_rating = { label: RATINGS[x.rating] };
  rel.average_duration_of_episode = x.duration;
  return rel;
}

export const shikiInfo = (sid, signal) => shikiAnime(sid, signal).catch(() => null);

export async function loadRelease(id, fresh = false, signal) {
  if (isShiki(id)) return shikiRelease(id, signal);
  if (isAnimeLib(id)) {
    const slug = animelibSlugs[id] || store.anime(id)?.animelib;
    if (!slug) throw new NoSourceError("AnimeLib slug unknown — open the title from search");
    const d = (await request(`${ANIMELIB}/anime/${slug}`, { params: { fields: ["summary", "genres"] },
      headers: ANIMELIB_H, ttl: TTL.SEARCH, signal })).data;
    return animelibRelease(d);
  }
  return api.release(id, fresh, signal);
}

// ------------------------------------------------------------------ AnimeLib (Kodik)
const animelibSlugs = {};
export function animelibRelease(x) {
  let summary = x.summary;
  if (summary && typeof summary === "object") {
    summary = (summary.content || []).map((p) => (p.content || []).map((t) => t.text || "").join("")).join("\n");
  }
  const m = (x.shikimori_href || "").match(/\/animes\/[a-z]*(\d+)/);
  const id = ANIMELIB_OFFSET + x.id;
  animelibSlugs[id] = x.slug_url;
  return { id, animelib: x.slug_url, name: { main: x.rus_name || x.name, english: x.name, alternative: x.eng_name },
    poster: { src: m ? `${SHIKI}/system/animes/original/${m[1]}.jpg` : null }, description: summary || "",
    genres: (x.genres || []).map((g) => ({ name: g.name })), episodes: [],
    shikimori: { id: m ? +m[1] : null, rating: x.shiki_rate ? +x.shiki_rate : null } };
}

const alSearch = (q) => request(`${ANIMELIB}/anime`, { params: { q }, headers: ANIMELIB_H, ttl: TTL.SEARCH })
  .then((d) => d.data || []).catch(() => []);

async function findAnimeLib(rel) {
  if (rel.animelib) return rel.animelib;
  const keys = matchKeys(rel);
  for (const q of searchQueries(rel)) {
    for (const x of await alSearch(q)) {
      const names = [x.name, x.rus_name, x.eng_name, ...(x.otherNames || [])].map(titleKey);
      if (names.some((n) => n && keys.has(n))) return x.slug_url;
    }
  }
  return null;
}

export function kodikTeams(players) {
  const seen = new Map();
  for (const p of players || []) {
    if (p.player !== "Kodik" || !p.team || seen.has(p.team.id)) continue;
    seen.set(p.team.id, { id: `kodik:${p.team.id}`, name: p.team.name || "?",
      kind: p.translation_type?.id === 1 ? "sub" : "voice", native: false });
  }
  return seen;
}

// ------------------------------------------------------------------ AnimeVost
async function vostSearch(q) {
  const clean = q.replace(/[^\p{L}\p{N}\s]/gu, " ").replace(/\s+/g, " ").trim();
  try {
    const d = await request(`${VOST}/search`, { form: { name: clean }, ttl: TTL.SEARCH });
    return d?.data && !d.error ? d.data : [];
  } catch { return []; }   // AnimeVost отвечает 404, когда ничего не найдено
}
export function vostNames(t) {
  const parts = (t || "").replace(/\[.*?\]/g, "").trim().split(" / ").map((s) => s.trim());
  return [parts[0], parts[1] || ""];
}
async function findVost(rel) {
  const keys = matchKeys(rel);
  for (const q of searchQueries(rel, false)) {
    for (const x of await vostSearch(q)) {
      if (vostNames(x.title).map(titleKey).some((n) => n && keys.has(n))) return x.id;
    }
  }
  return null;
}
export function vostEpisodes(items) {
  const eps = [];
  (items || []).forEach((it, i) => {
    const streams = {};
    if (it.hd) streams["720"] = it.hd;
    if (it.std) streams["480"] = it.std;
    if (!Object.keys(streams).length) return;
    const o = parseOrdinal(it.name, i + 1);
    eps.push({ key: fmtOrd(o), ordinal: o, name: null, streams, animelib: null, preview: it.preview || null });
  });
  return eps.sort((a, b) => a.ordinal - b.ordinal);
}

// ------------------------------------------------------------------ YummyAnime
// Открытый каталог с плеерами Kodik по каждой озвучке; есть тайтлы, скрытые в AnimeLib. Сверяем по id Shikimori.
const yaniSearch = (q) => request(`${YANI}/search`, { params: { q, limit: 20 }, ttl: TTL.SEARCH })
  .then((d) => d?.response || []).catch(() => []);
async function findYani(rel) {
  const sid = rel.shikimori?.id;
  const keys = matchKeys(rel);
  const queries = [rel.name?.main, ...searchQueries(rel)].filter((q, i, a) => q && a.indexOf(q) === i);
  for (const q of queries.slice(0, 4)) {
    const items = await yaniSearch(q);
    const hit = sid ? items.find((x) => x.remote_ids?.shikimori_id === sid)
      : items.find((x) => keys.has(titleKey(x.title)) && (!rel.year || Math.abs(x.year - rel.year) <= 1));
    if (hit) return hit.anime_id;
  }
  return null;
}
const yaniDubName = (s) => (s || "").replace(/^Озвучка\s+/i, "").trim() || "Kodik";
/** Серии YummyAnime по озвучкам: {"yani:<озвучка>": {name, kind, eps}} — только плеер Kodik (у него есть API управления). */
export function yaniGroups(videos) {
  const out = {};
  for (const v of videos || []) {
    if (!/kodik/i.test(v.data?.player || "") || !v.iframe_url) continue;
    const name = yaniDubName(v.data.dubbing);
    const g = (out[`yani:${name}`] ||= { name, kind: /субтитр/i.test(name) ? "sub" : "voice", eps: [] });
    const o = parseOrdinal(v.number, g.eps.length + 1);
    if (g.eps.some((e) => e.ordinal === o)) continue;
    const op = v.skips?.opening;
    g.eps.push({ key: fmtOrd(o), ordinal: o, name: null, streams: null, animelib: null,
      kodik: v.iframe_url.startsWith("//") ? "https:" + v.iframe_url : v.iframe_url,
      opening: op?.length ? { start: op.time, stop: op.time + op.length } : null });
  }
  for (const g of Object.values(out)) g.eps.sort((a, b) => a.ordinal - b.ordinal);
  return out;
}
const yaniDubs = async (id) => yaniGroups((await request(`${YANI}/anime/${id}/videos`, { ttl: TTL.YANI }))?.response);

// ------------------------------------------------------------------ AniSkip
// Время заставки и титров, размеченное сообществом. Ключ — id MyAnimeList (= id Shikimori).
const skipCache = new MemoryCache({ maxSize: 300 });
export function parseSkipTimes(d) {
  let res = null;
  for (const r of d?.found ? d.results || [] : []) {
    const k = r.skipType === "op" ? "opening" : "ending";
    res ||= {};
    if (!res[k]) res[k] = { start: r.interval.startTime, stop: r.interval.endTime };
  }
  return res;
}
export async function skipTimes(sid, ordinal, duration) {
  if (!sid || !Number.isInteger(+ordinal) || !(duration > 60)) return null;
  const key = `${sid}|${ordinal}|${Math.round(duration)}`;
  if (skipCache.has(key)) return skipCache.get(key) || null;
  let res = null;
  try {
    res = parseSkipTimes(await request(`https://api.aniskip.com/v2/skip-times/${sid}/${+ordinal}`,
      { params: { types: ["op", "ed"], episodeLength: Math.round(duration) }, ttl: TTL.ANISKIP }));
  } catch { /* разметки нет — кнопка «Пропустить заставку» просто не появится */ }
  skipCache.set(key, res ?? false);
  return res;
}

// ------------------------------------------------------------------ озвучки
const dubCache = new MemoryCache({ maxSize: 40, ttl: 1800 });
const epCache = new MemoryCache({ maxSize: 120, ttl: 1800 });

async function searchDubs(rel) {
  const dubs = [];
  const matches = {};
  const al = anilibriaEpisodes(rel);
  if (al.length) {
    dubs.push({ id: "anilibria", name: "AniLibria", kind: "voice", native: true });
    epCache.set(`${rel.id}|anilibria`, al);
  }
  const [vost, slug, yani] = await Promise.all([findVost(rel).catch(() => null), findAnimeLib(rel).catch(() => null),
    findYani(rel).then((id) => (id ? yaniDubs(id) : null)).catch(() => null)]);
  if (vost) {
    matches.vost = vost;
    dubs.push({ id: "animevost", name: "AnimeVost", kind: "voice", native: true });
  }
  if (slug) {
    try {
      const items = (await request(`${ANIMELIB}/episodes`, { params: { anime_id: slug }, headers: ANIMELIB_H, ttl: TTL.ANIMELIB_EPS })).data || [];
      const eps = items.map((e, i) => {
        const o = parseOrdinal(e.number || e.item_number, i + 1);
        return { key: fmtOrd(o), ordinal: o, name: e.name, streams: null, animelib: e.id };
      });
      matches.animelibEps = eps;
      // Составы озвучек — по первой и последней серии (параллельно)
      const probes = [...new Set([eps[0]?.animelib, eps.at(-1)?.animelib].filter(Boolean))];
      const players = await Promise.all(probes.map((eid) => request(`${ANIMELIB}/episodes/${eid}`,
        { headers: ANIMELIB_H, ttl: TTL.ANIMELIB_EPS }).then((d) => d.data?.players || []).catch(() => [])));
      const seen = kodikTeams(players.flat());
      const native = dubs.map((d) => norm(d.name));
      for (const d of seen.values()) if (!native.some((n) => norm(d.name).startsWith(n))) dubs.push(d);
    } catch (e) { console.warn("[AnimeApp] AnimeLib недоступен", e); }
  }
  // Озвучки YummyAnime, которых нет у других источников
  if (yani) {
    matches.yani = yani;
    for (const [id, g] of Object.entries(yani)) {
      if (!g.eps.length || dubs.some((d) => sameDub(d.name, g.name))) continue;
      dubs.push({ id, name: g.name, kind: g.kind, native: false });
    }
  }
  const res = { t: Date.now(), dubs: sortDubs(dubs), matches };
  dubCache.set(rel.id, res);
  return res;
}
const searchDubsOnce = shared(searchDubs);

/** {dubs, matches}. Если поиск по этому тайтлу уже идёт — ждём его, второй не запускаем. */
export function findDubs(rel) {
  const hit = dubCache.get(rel.id);
  return hit ? Promise.resolve(hit) : searchDubsOnce(rel.id, rel);
}

/** Картинки серий со всех «родных» источников: номер серии -> URL (у Kodik картинок нет). */
export async function previews(rel, dubs) {
  const map = {};
  const lists = await Promise.all(dubs.filter((x) => x.native).map((d) => episodes(rel, d).catch(() => [])));
  for (const eps of lists) for (const e of eps) if (e.preview && !map[e.key]) map[e.key] = e.preview;
  return map;
}

export function invalidate(id) {
  dubCache.delete(id);
  epCache.deleteWhere((k) => k.startsWith(`${id}|`));
}

export async function episodes(rel, dub) {
  const key = `${rel.id}|${dub.id}`;
  // Серии AniLibria — всегда из переданного (свежего) релиза: в них ссылки на поток
  if (dub.id === "anilibria") return anilibriaEpisodes(rel);
  const hit = epCache.get(key);
  if (hit) return hit;
  const { matches } = await findDubs(rel);
  let eps = [];
  if (dub.id === "animevost" && matches.vost) eps = vostEpisodes(await request(`${VOST}/playlist`, { form: { id: matches.vost }, ttl: TTL.VOST }));
  else if (dub.id.startsWith("kodik:")) eps = (matches.animelibEps || []).map((e) => ({ ...e }));
  else if (dub.id.startsWith("yani:")) eps = (matches.yani?.[dub.id]?.eps || []).map((e) => ({ ...e }));
  epCache.set(key, eps);
  return eps;
}

export function chooseDub(rel, dubs, st = store) {
  return pickDub(dubs, st.setting(`dub:${rel.id}`), st.setting("preferredDub", ""));
}

// ------------------------------------------------------------------ франшиза (сезоны и фильмы)
const HIDDEN = new Set(["Клип", "Реклама", "Проморолик"]);
const franchiseCache = new MemoryCache({ maxSize: 40, ttl: 3600 });
// Типы узлов франшизы Shikimori приходят по-русски («TV Сериал», «Фильм», «Спецвыпуск») — это данные API
function label(kind, n) {
  if (kind === "TV Сериал" || kind === "TV") return t("anime.season_n", { n });
  if (kind === "Фильм" || kind === "MOVIE") return t("anime.kinds.movie");
  if ((kind || "").includes("Спецвыпуск") || kind === "SPECIAL") return t("anime.kinds.special");
  return kind;
}

/** Похожие тайтлы по версии Shikimori. */
export async function similar(sid, signal) {
  if (!sid) return [];
  const items = await request(`${SHIKI}/api/animes/${sid}/similar`, { ttl: TTL.FRANCHISE, signal });
  return (items || []).filter((x) => !HIDDEN_KINDS.includes(x.kind)).map(shikiItem);
}

/** Сведение графа франшизы Shikimori с релизами AniLibria. */
export function mergeFranchise(rel, shiki, alData) {
  const sid = rel.shikimori?.id;
  const alRels = (alData || []).flatMap((f) => (f.franchise_releases || []).map((x) => x.release).filter(Boolean));
  const bySid = new Map(alRels.filter((r) => r.shikimori?.id).map((r) => [r.shikimori.id, r]));
  let entries = [];
  let n = 0;
  if (shiki?.nodes?.length) {
    const nodes = shiki.nodes.filter((x) => !HIDDEN.has(x.kind)).sort((a, b) => (a.year || 9999) - (b.year || 9999) || (a.date || 0) - (b.date || 0));
    for (const x of nodes) {
      if (x.kind === "TV Сериал") n++;
      const al = bySid.get(x.id);
      entries.push({ sid: x.id, label: label(x.kind, n), name: al ? title(al) : x.name, year: x.year,
        poster: al ? api.posterUrl(al) : (x.image_url?.includes("missing") ? null : `${SHIKI}/system/animes/original/${x.id}.jpg`),
        releaseId: al?.id || SHIKI_OFFSET + x.id, current: x.id === sid });
    }
  } else {
    for (const r of [...alRels].sort((a, b) => (a.year || 0) - (b.year || 0))) {
      if (r.type?.value === "TV") n++;
      entries.push({ sid: r.shikimori?.id, label: label(r.type?.value, n), name: title(r), year: r.year,
        poster: api.posterUrl(r), releaseId: r.id, current: r.id === rel.id });
    }
  }
  return entries.length < 2 ? [] : entries;
}

async function loadFranchise(rel) {
  const sid = rel.shikimori?.id;
  const [shiki, alData] = await Promise.all([
    sid ? request(`${SHIKI}/api/animes/${sid}/franchise`, { ttl: TTL.FRANCHISE }).catch(() => null) : null,
    isExternal(rel.id) ? null : api.franchiseAL(rel.id).catch(() => null),
  ]);
  const entries = mergeFranchise(rel, shiki, alData);
  franchiseCache.set(rel.id, entries);
  return entries;
}
const loadFranchiseOnce = shared(loadFranchise);

export function franchise(rel) {
  const hit = franchiseCache.get(rel.id);
  return hit ? Promise.resolve(hit) : loadFranchiseOnce(rel.id, rel);
}
