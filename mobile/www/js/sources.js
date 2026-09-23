// Источники серий и озвучек, каталог Shikimori, франшизы и предстоящие серии (порт с ПК-версии).
import * as api from "./api.js";

export const ANIMELIB_OFFSET = 100_000_000;
export const SHIKI_OFFSET = 200_000_000;
const SHIKI = "https://shikimori.io";
const ANIMELIB = "https://api.cdnlibs.org/api";
const ANIMELIB_H = { "Site-Id": "5" };
const VOST = "https://api.animetop.info/v1";
const YANI = "https://api.yani.tv";
const KINDS = { tv: "ТВ", movie: "Фильм", ova: "OVA", ona: "ONA", special: "Спешл", tv_special: "ТВ-спешл" };
const RATINGS = { g: "0+", pg: "6+", pg_13: "13+", r: "16+", r_plus: "18+", rx: "18+" };

export const isShiki = (id) => id >= SHIKI_OFFSET;
export const isAnimeLib = (id) => id >= ANIMELIB_OFFSET && id < SHIKI_OFFSET;
export const isExternal = (id) => id >= ANIMELIB_OFFSET;
export const title = (rel) => rel?.name?.main || rel?.name?.english || "Без названия";
export const fmtOrd = (v) => (Number.isInteger(+v) ? String(+v) : String(v));

export function norm(t) { return (t || "").toLowerCase().replace(/ё/g, "е").replace(/[^0-9a-zа-я]+/g, ""); }

const ROMAN = { ii: "2", iii: "3", iv: "4", v: "5", vi: "6", vii: "7", viii: "8" };
const ORD = { первый: "1", второй: "2", третий: "3", четвертый: "4", пятый: "5", шестой: "6",
  первая: "1", вторая: "2", третья: "3", четвертая: "4", пятая: "5" };
// «Mushoku Tensei III» = «Mushoku Tensei 3», «(третий сезон)» = «3», «Часть 2» = «Part 2»
export function titleKey(text) {
  let t = ` ${(text || "").toLowerCase().replace(/ё/g, "е")} `;
  t = t.replace(/[^0-9a-zа-я]+/g, " ");
  // (\b в JS не работает с кириллицей — разбираем по словам)
  const drop = new Set(["сезон", "season", "tv", "тв"]);
  t = t.split(" ").map((w) => (drop.has(w) ? "" : ROMAN[w] || ORD[w] || (w === "часть" || w === "part" ? "p" : w))).join(" ");
  return norm(t);
}

function searchQueries(rel, fullFirst = true) {
  const out = [];
  for (const t of [rel.name?.english, rel.name?.main]) {
    if (!t) continue;
    const v = fullFirst ? [t] : [];
    const head = t.split(/[:.!?(\[]/)[0].trim();
    v.push(head);
    const words = head.replace(/[^\p{L}\p{N}\s]/gu, " ").split(/\s+/).filter(Boolean);
    if (words.length > 2) v.push(words.slice(0, 2).join(" "));
    for (const q of v) if (q && q.length >= 3 && !out.includes(q)) out.push(q);
  }
  return out;
}
const matchKeys = (rel) => new Set([rel.name?.english, rel.name?.main, rel.name?.alternative].map(titleKey).filter(Boolean));

function ordinal(v, fallback) {
  const n = parseFloat(String(v ?? "").replace(",", "."));
  if (!Number.isNaN(n)) return n;
  const m = String(v || "").match(/\d+(?:[.,]\d+)?/);
  return m ? parseFloat(m[0].replace(",", ".")) : fallback;
}

export function anilibriaEpisodes(rel) {
  const eps = [];
  for (const e of rel.episodes || []) {
    const streams = {};
    for (const q of ["1080", "720", "480"]) if (e[`hls_${q}`]) streams[q] = e[`hls_${q}`];
    if (!Object.keys(streams).length) continue;
    const o = ordinal(e.ordinal, eps.length + 1);
    const pv = e.preview || {};
    eps.push({ key: fmtOrd(o), ordinal: o, name: e.name || e.name_english, duration: e.duration,
      opening: e.opening, ending: e.ending, streams, animelib: null,
      preview: api.mediaUrl(pv.optimized?.preview || pv.preview || pv.src) });
  }
  return eps;
}

// ------------------------------------------------------------------ Shikimori (полный каталог)
function stripBB(t) { return (t || "").replace(/\[(\w+)=[^\]]*\](.*?)\[\/\1\]/g, "$2").replace(/\[\/?[^\]]+\]/g, "").trim(); }

export function shikiItem(x) {
  const img = x.image?.original || "";
  const year = (x.aired_on || "").slice(0, 4);
  const rel = {
    id: SHIKI_OFFSET + x.id, name: { main: x.russian || x.name, english: x.name },
    poster: { src: img && !img.includes("missing") ? SHIKI + img : null },
    year: +year || null, type: { description: KINDS[x.kind] || "" }, episodes_total: x.episodes || null,
    is_ongoing: x.status === "ongoing", shikimori: { id: x.id, rating: x.score ? +x.score : null }, episodes: [],
  };
  const sub = [year, KINDS[x.kind], x.episodes ? `${x.episodes} эп.` : ""].filter(Boolean).join(" · ");
  return { id: rel.id, title: rel.name.main, subtitle: sub, poster: rel.poster.src,
    badge: x.status === "anons" ? "Анонс" : null, release: rel };
}

const KIND_RANK = { tv: 0, movie: 1, ona: 2, ova: 3, tv_special: 4, special: 5 };
const SHIKI_SEARCH_LIMIT = 50;
/** Возвращает массив найденного; в свойстве hasMore — есть ли следующая страница. */
export async function shikiSearch(q, page = 1) {
  const items = await api.request(`${SHIKI}/api/animes`, { params: { search: q, limit: SHIKI_SEARCH_LIMIT, page }, ttl: 3600 });
  const key = titleKey(q);
  const exact = (x) => ([x.russian, x.name].some((n) => titleKey(n) === key) ? 0 : 1);
  const out = (items || []).filter((x) => !["music", "pv", "cm"].includes(x.kind))
    .map((x, i) => ({ x, i }))
    .sort((a, b) => exact(a.x) - exact(b.x) || (KIND_RANK[a.x.kind] ?? 6) - (KIND_RANK[b.x.kind] ?? 6)
      || (a.x.aired_on || "9999").localeCompare(b.x.aired_on || "9999") || a.i - b.i)
    .map(({ x }) => x);
  out.hasMore = (items || []).length >= SHIKI_SEARCH_LIMIT;
  return out;
}

export async function shikiRelease(id) {
  const x = await api.request(`${SHIKI}/api/animes/${id - SHIKI_OFFSET}`, { ttl: 3600 });
  const rel = shikiItem(x).release;
  rel.name.alternative = (x.english || [])[0];
  rel.description = stripBB(x.description);
  rel.genres = (x.genres || []).map((g) => ({ name: g.russian || g.name }));
  rel.age_rating = { label: RATINGS[x.rating] };
  rel.average_duration_of_episode = x.duration;
  return rel;
}

export const shikiInfo = (sid) => api.request(`${SHIKI}/api/animes/${sid}`, { ttl: 3600 }).catch(() => null);

export async function loadRelease(id, fresh = false) {
  if (isShiki(id)) return shikiRelease(id);
  if (isAnimeLib(id)) {
    const slug = animelibSlugs[id];
    if (!slug) throw new Error("Откройте тайтл заново через поиск");
    const d = (await api.request(`${ANIMELIB}/anime/${slug}`, { params: { fields: ["summary", "genres"] },
      headers: ANIMELIB_H, ttl: 3600 })).data;
    return animelibRelease(d);
  }
  return api.release(id, fresh);
}

// ------------------------------------------------------------------ AnimeLib (Kodik)
const animelibSlugs = {};
function animelibRelease(x) {
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

const alSearch = (q) => api.request(`${ANIMELIB}/anime`, { params: { q }, headers: ANIMELIB_H, ttl: 3600 })
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

export async function kodikSource(animelibEpisodeId, teamId) {
  const d = (await api.request(`${ANIMELIB}/episodes/${animelibEpisodeId}`, { headers: ANIMELIB_H })).data;
  const players = (d.players || []).filter((p) => p.player === "Kodik" && p.src);
  const exact = players.filter((p) => p.team?.id === +teamId);
  const chosen = (exact.length ? exact : players)[0];
  if (!chosen) throw new Error("Для этой серии нет видео");
  const src = chosen.src.startsWith("//") ? "https:" + chosen.src : chosen.src;
  return { src, team: chosen.team?.name, fallback: !exact.length };
}

// ------------------------------------------------------------------ AnimeVost
async function vostSearch(q) {
  const clean = q.replace(/[^\p{L}\p{N}\s]/gu, " ").replace(/\s+/g, " ").trim();
  try {
    const d = await api.request(`${VOST}/search`, { form: { name: clean }, ttl: 3600 });
    return d?.data && !d.error ? d.data : [];
  } catch { return []; }
}
function vostNames(t) {
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
async function vostEpisodes(id) {
  const items = await api.request(`${VOST}/playlist`, { form: { id }, ttl: 900 });
  const eps = [];
  (items || []).forEach((it, i) => {
    const streams = {};
    if (it.hd) streams["720"] = it.hd;
    if (it.std) streams["480"] = it.std;
    if (!Object.keys(streams).length) return;
    const o = ordinal(it.name, i + 1);
    eps.push({ key: fmtOrd(o), ordinal: o, name: null, streams, animelib: null, preview: it.preview || null });
  });
  return eps.sort((a, b) => a.ordinal - b.ordinal);
}

// ------------------------------------------------------------------ YummyAnime
// Открытый каталог с плеерами Kodik по каждой озвучке; есть тайтлы, скрытые в AnimeLib
// (лицензионные: «Тетрадь смерти», «Сага о Винланде», фильмы Гибли…). Сверяем по id Shikimori.
const yaniSearch = (q) => api.request(`${YANI}/search`, { params: { q, limit: 20 }, ttl: 3600 })
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
async function yaniDubs(id) {
  const d = await api.request(`${YANI}/anime/${id}/videos`, { ttl: 1800 });
  const out = {};
  for (const v of d?.response || []) {
    if (!/kodik/i.test(v.data?.player || "") || !v.iframe_url) continue;
    const name = yaniDubName(v.data.dubbing);
    const g = (out[`yani:${name}`] ||= { name, kind: /субтитр/i.test(name) ? "sub" : "voice", eps: [] });
    const o = ordinal(v.number, g.eps.length + 1);
    if (g.eps.some((e) => e.ordinal === o)) continue;
    const op = v.skips?.opening;
    g.eps.push({ key: fmtOrd(o), ordinal: o, name: null, streams: null, animelib: null,
      kodik: v.iframe_url.startsWith("//") ? "https:" + v.iframe_url : v.iframe_url,
      opening: op?.length ? { start: op.time, stop: op.time + op.length } : null });
  }
  for (const g of Object.values(out)) g.eps.sort((a, b) => a.ordinal - b.ordinal);
  return out;
}
/** Одна и та же команда в разных каталогах пишется по-разному: «Дублированный» / «Дублированная», «2x2» / «2×2». */
const sameDub = (a, b) => {
  const x = norm(a.replace(/×/g, "x")), y = norm(b.replace(/×/g, "x"));
  return x === y || (Math.min(x.length, y.length) >= 5 && (x.startsWith(y) || y.startsWith(x) || x.slice(0, 8) === y.slice(0, 8)));
};

// ------------------------------------------------------------------ AniSkip
// Время заставки и титров, размеченное сообществом (api.aniskip.com). Ключ — id MyAnimeList, он совпадает с id Shikimori.
// Длительность серии передаём, чтобы получить разметку именно под такую версию видео.
const skipCache = {};
export async function skipTimes(sid, ordinal, duration) {
  if (!sid || !Number.isInteger(+ordinal) || !(duration > 60)) return null;
  const key = `${sid}|${ordinal}|${Math.round(duration)}`;
  if (key in skipCache) return skipCache[key];
  let res = null;
  try {
    const d = await api.request(`https://api.aniskip.com/v2/skip-times/${sid}/${+ordinal}`,
      { params: { types: ["op", "ed"], episodeLength: Math.round(duration) }, ttl: 7 * 86400 });
    for (const r of d?.found ? d.results || [] : []) {
      const k = r.skipType === "op" ? "opening" : "ending";
      res ||= {};
      if (!res[k]) res[k] = { start: r.interval.startTime, stop: r.interval.endTime };
    }
  } catch { /* разметки нет */ }
  skipCache[key] = res;
  return res;
}

// ------------------------------------------------------------------ озвучки
const dubCache = {};
const epCache = {};

export async function findDubs(rel) {
  const hit = dubCache[rel.id];
  if (hit && Date.now() - hit.t < 1800_000) return hit;
  const dubs = [];
  const matches = {};
  const al = anilibriaEpisodes(rel);
  if (al.length) {
    dubs.push({ id: "anilibria", name: "AniLibria", kind: "voice", native: true });
    epCache[`${rel.id}|anilibria`] = al;
  }
  const [vost, slug, yani] = await Promise.all([findVost(rel).catch(() => null), findAnimeLib(rel).catch(() => null),
    findYani(rel).then((id) => (id ? yaniDubs(id) : null)).catch(() => null)]);
  if (vost) {
    matches.vost = vost;
    dubs.push({ id: "animevost", name: "AnimeVost", kind: "voice", native: true });
  }
  if (slug) {
    try {
      const items = (await api.request(`${ANIMELIB}/episodes`, { params: { anime_id: slug }, headers: ANIMELIB_H, ttl: 1800 })).data || [];
      const eps = items.map((e, i) => {
        const o = ordinal(e.number || e.item_number, i + 1);
        return { key: fmtOrd(o), ordinal: o, name: e.name, streams: null, animelib: e.id };
      });
      matches.animelibEps = eps;
      const seen = new Map();
      for (const eid of new Set([eps[0]?.animelib, eps.at(-1)?.animelib].filter(Boolean))) {
        const d = (await api.request(`${ANIMELIB}/episodes/${eid}`, { headers: ANIMELIB_H, ttl: 1800 })).data;
        for (const p of d.players || []) {
          if (p.player !== "Kodik" || !p.team || seen.has(p.team.id)) continue;
          seen.set(p.team.id, { id: `kodik:${p.team.id}`, name: p.team.name || "?",
            kind: p.translation_type?.id === 1 ? "sub" : "voice", native: false });
        }
      }
      const native = dubs.map((d) => norm(d.name));
      for (const d of seen.values()) if (!native.some((n) => norm(d.name).startsWith(n))) dubs.push(d);
    } catch { /* AnimeLib недоступен */ }
  }
  // Озвучки YummyAnime, которых нет у других источников
  if (yani) {
    matches.yani = yani;
    for (const [id, g] of Object.entries(yani)) {
      if (!g.eps.length || dubs.some((d) => sameDub(d.name, g.name))) continue;
      dubs.push({ id, name: g.name, kind: g.kind, native: false });
    }
  }
  dubs.sort((a, b) => (a.native === b.native ? 0 : a.native ? -1 : 1) || (a.kind === "sub") - (b.kind === "sub")
    || a.name.localeCompare(b.name));
  const res = { t: Date.now(), dubs, matches };
  dubCache[rel.id] = res;
  return res;
}

/** Картинки серий со всех «родных» источников: номер серии -> URL (у Kodik картинок нет). */
export async function previews(rel, dubs) {
  const map = {};
  for (const d of dubs.filter((x) => x.native)) {
    for (const e of await episodes(rel, d).catch(() => [])) if (e.preview && !map[e.key]) map[e.key] = e.preview;
  }
  return map;
}

export function invalidate(id) {
  delete dubCache[id];
  for (const k of Object.keys(epCache)) if (k.startsWith(`${id}|`)) delete epCache[k];
}

export async function episodes(rel, dub) {
  const key = `${rel.id}|${dub.id}`;
  // Серии AniLibria — всегда из переданного (свежего) релиза: в них ссылки на поток
  if (dub.id === "anilibria") return anilibriaEpisodes(rel);
  if (epCache[key]) return epCache[key];
  const { matches } = await findDubs(rel);
  let eps = [];
  if (dub.id === "anilibria") eps = anilibriaEpisodes(rel);
  else if (dub.id === "animevost" && matches.vost) eps = await vostEpisodes(matches.vost);
  else if (dub.id.startsWith("kodik:")) eps = (matches.animelibEps || []).map((e) => ({ ...e }));
  else if (dub.id.startsWith("yani:")) eps = (matches.yani?.[dub.id]?.eps || []).map((e) => ({ ...e }));
  epCache[key] = eps;
  return eps;
}

export function chooseDub(rel, dubs, store) {
  if (!dubs.length) return null;
  const saved = store.setting(`dub:${rel.id}`);
  const s = dubs.find((d) => d.id === saved);
  if (s) return s;
  const pref = norm(store.setting("preferredDub", ""));
  if (pref) {
    const p = dubs.find((d) => norm(d.name).startsWith(pref) || pref.startsWith(norm(d.name)));
    if (p) return p;
  }
  return dubs[0];
}

// ------------------------------------------------------------------ франшиза (сезоны и фильмы)
const HIDDEN = new Set(["Клип", "Реклама", "Проморолик"]);
const franchiseCache = {};
function label(kind, n) {
  if (kind === "TV Сериал" || kind === "TV") return `${n} сезон`;
  if (kind === "Фильм" || kind === "MOVIE") return "Фильм";
  if ((kind || "").includes("Спецвыпуск") || kind === "SPECIAL") return "Спешл";
  return kind;
}

/** Похожие тайтлы по версии Shikimori. */
export async function similar(sid) {
  if (!sid) return [];
  const items = await api.request(`${SHIKI}/api/animes/${sid}/similar`, { ttl: 86400 }).catch(() => []);
  return (items || []).filter((x) => !["music", "pv", "cm"].includes(x.kind)).map(shikiItem);
}

export async function franchise(rel) {
  if (franchiseCache[rel.id]) return franchiseCache[rel.id];
  const sid = rel.shikimori?.id;
  const [shiki, alData] = await Promise.all([
    sid ? api.request(`${SHIKI}/api/animes/${sid}/franchise`, { ttl: 86400 }).catch(() => null) : null,
    isExternal(rel.id) ? null : api.franchiseAL(rel.id).catch(() => null),
  ]);
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
    for (const r of alRels.sort((a, b) => (a.year || 0) - (b.year || 0))) {
      if (r.type?.value === "TV") n++;
      entries.push({ sid: r.shikimori?.id, label: label(r.type?.value, n), name: title(r), year: r.year,
        poster: api.posterUrl(r), releaseId: r.id, current: r.id === rel.id });
    }
  }
  if (entries.length < 2) entries = [];
  franchiseCache[rel.id] = entries;
  return entries;
}

// ------------------------------------------------------------------ предстоящие серии
export function upcoming(rel, info, knownKeys, dubWeekday) {
  const known = knownKeys.map(Number).filter((x) => !Number.isNaN(x));
  const maxKnown = known.length ? Math.floor(Math.max(...known)) : 0;
  const status = info?.status;
  const total = info?.episodes || rel.episodes_total || 0;
  let aired = info?.episodes_aired || 0;
  if (status === "released") aired = Math.max(aired, total);
  let dubDate = null;
  if (dubWeekday) {
    const d = new Date(); d.setHours(0, 0, 0, 0);
    const today = ((d.getDay() + 6) % 7) + 1;
    d.setDate(d.getDate() + (((dubWeekday - today) % 7) + 7) % 7 || 7);
    dubDate = (i) => new Date(d.getTime() + i * 7 * 86400_000);
  }
  const out = [];
  for (let n = maxKnown + 1, i = 0; n <= Math.min(aired, maxKnown + 24); n++, i++) {
    out.push(dubDate ? { n, date: dubDate(i), state: "dub" } : { n, date: null, state: "no_dub" });
  }
  if (status !== "ongoing" && status !== "anons") return out;
  const start = Math.max(aired, maxKnown) + 1;
  const end = total >= start ? total : start + 2;
  let nxt = info.next_episode_at ? new Date(info.next_episode_at) : (status === "anons" && info.aired_on ? new Date(info.aired_on) : null);
  for (let n = start, i = 0; n <= Math.min(end, start + 24); n++, i++) {
    out.push({ n, date: nxt ? new Date(nxt.getTime() + i * 7 * 86400_000) : null, state: "upcoming" });
  }
  return out;
}
