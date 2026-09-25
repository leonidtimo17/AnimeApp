// Данные пользователя: списки, избранное, оценки, прогресс, настройки (localStorage, ключ animeapp:v1 — как раньше).
//
// Единственное место, где они меняются. Экраны не хранят свои копии: читают отсюда и подписываются на изменения
// (subscribe), а связь с Shikimori — на изменения статуса, оценки и серий (onChange). Обе подписки можно снять.
import { createEmitter } from "../events.js";
import { resumeTarget as resumeFrom } from "../../domain/episodes.js";

/** Статусы списков; подписи — ключи перевода (t(STATUSES.watching)). */
export const STATUSES = {
  watching: "status.watching", planned: "status.planned", completed: "status.completed", postponed: "status.postponed", dropped: "status.dropped",
};

const KEY = "animeapp:v1";
const storage = () => globalThis.localStorage;
const state = load();
const changes = createEmitter();     // (kind, id) — любое изменение, для интерфейса
const synced = createEmitter();      // (kind, id) — статус/оценка/серии, для Shikimori

function load() {
  const empty = { anime: {}, library: {}, progress: {}, settings: {} };
  try {
    return { ...empty, ...JSON.parse(storage()?.getItem(KEY) || "{}") };
  } catch (e) {
    console.error("[AnimeApp] данные пользователя повреждены — начинаем с чистого листа", e);
    return empty;
  }
}

let saveTimer = null;
function writeNow() {
  const ls = storage();
  if (!ls) return;
  const raw = JSON.stringify(state);
  try {
    ls.setItem(KEY, raw);
  } catch (e) {
    // Переполнение: освобождаем место (старый кэш ответов) и пробуем ещё раз — списки важнее кэша
    console.warn("[AnimeApp] не хватило места для данных — чистим старый кэш", e);
    try {
      Object.keys(ls).filter((k) => k.startsWith("http:")).forEach((k) => ls.removeItem(k));
      ls.setItem(KEY, raw);
    } catch (e2) { console.error("[AnimeApp] не удалось сохранить данные", e2); }
  }
}
function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(writeNow, 200);
}
globalThis.addEventListener?.("pagehide", writeNow);

/** Изменения данных (для интерфейса). fn(kind, id): kind — "anime" | "status" | "favorite" | "score" | "episode" | "settings". */
export const subscribe = changes.subscribe;
/** Изменения для Shikimori: fn(kind, id), kind — "status" | "score" | "episode". Возвращает функцию отписки. */
export const onChange = synced.subscribe;
const notify = (kind, id, sync = false) => {
  changes.emit(kind, id);
  if (sync) synced.emit(kind, id);
};

// ------------------------------------------------------------------ тайтлы (офлайн-кэш карточек)
export function remember(rel, extra = {}) {
  if (!rel?.id) return;
  const name = rel.name || {};
  const prev = state.anime[rel.id];
  state.anime[rel.id] = {
    id: rel.id, title: name.main || name.english || "", poster: extra.poster ?? prev?.poster ?? null,
    subtitle: extra.subtitle ?? prev?.subtitle ?? "", year: rel.year ?? null,
    type: rel.type?.description || "", genres: (rel.genres || []).map((g) => g.name).filter(Boolean),
    shikimori: rel.shikimori?.id || null, animelib: rel.animelib || prev?.animelib || null, updated: Date.now(),
  };
  if (!state.anime[rel.id].genres.length && (extra.genres || prev?.genres)) state.anime[rel.id].genres = extra.genres || prev.genres;
  save();
}
export const anime = (id) => state.anime[id];
export const animeAll = () => state.anime;

// ------------------------------------------------------------------ списки
export function entry(id) {
  return state.library[id] || { status: null, favorite: false, score: null };
}
function setEntry(id, patch) {
  const e = { ...entry(id), ...patch, updated: Date.now() };
  if (!e.status && !e.favorite && !e.score) delete state.library[id];
  else state.library[id] = e;
  save();
}

export const setStatus = (id, status) => { setEntry(id, { status }); notify("status", id, true); };
export const setFavorite = (id, favorite) => { setEntry(id, { favorite }); notify("favorite", id); };
export const setScore = (id, score) => { setEntry(id, { score }); notify("score", id, true); };
/** Без отправки на Shikimori — для загрузки списка оттуда. */
export const setEntryQuiet = (id, patch) => { setEntry(id, patch); notify("status", id); };
/** Начали смотреть: «Хочу посмотреть»/«Отложено»/без списка → «Смотрю». */
export function markWatching(id) {
  const st = entry(id).status;
  if (!st || st === "planned" || st === "postponed") setStatus(id, "watching");
}

export function library(status) {
  return Object.entries(state.library)
    .filter(([, e]) => (status === "favorite" ? e.favorite : e.status === status))
    .sort((a, b) => b[1].updated - a[1].updated)
    .map(([id]) => state.anime[id]).filter(Boolean);
}
export const libraryIds = () => Object.keys(state.library).map(Number);

// ------------------------------------------------------------------ прогресс (ключ серии — её номер)
export function progress(id) { return state.progress[id] || {}; }
export const progressAll = () => state.progress;

export function saveProgress(id, key, ordinal, pos, dur, endingStart) {
  if (!dur || dur < 30) return false;
  const p = (state.progress[id] ||= {});
  const prev = p[key] || {};
  const tail = dur - pos;
  const watched = prev.watched || (endingStart && pos >= endingStart) || tail <= Math.min(180, dur * 0.1);
  p[key] = { pos, dur, ordinal, watched: !!watched, t: Date.now() };
  save();
  if (watched && !prev.watched) notify("episode", id, true);
  return !!watched && !prev.watched;
}

/** Как setWatched, но без отправки на Shikimori — это её же данные. */
export function setWatchedQuiet(id, key, ordinal, watched) {
  const p = (state.progress[id] ||= {});
  p[key] = { ...(p[key] || { pos: 0, dur: 0 }), ordinal, watched, pos: 0, t: Date.now() };
  save();
  notify("episode", id);
}

export function setWatched(id, key, ordinal, watched) {
  const p = (state.progress[id] ||= {});
  p[key] = { ...(p[key] || { pos: 0, dur: 0 }), ordinal, watched, pos: watched ? (p[key]?.pos || 0) : 0, t: Date.now() };
  save();
  notify("episode", id, true);
}

export function lastProgress(id) {
  let best = null;
  for (const [key, v] of Object.entries(progress(id))) {
    if (!best || v.t > best.t || (v.t === best.t && v.ordinal > best.ordinal)) best = { key, ...v };
  }
  return best;
}

export function continueWatching(limit = 20) {
  const rows = [];
  for (const id of Object.keys(state.progress)) {
    const last = lastProgress(id);
    const a = state.anime[id];
    const st = entry(id).status;
    if (last && a && st !== "completed" && st !== "dropped") rows.push({ anime: a, last });
  }
  return rows.sort((x, y) => y.last.t - x.last.t).slice(0, limit);
}

export function history(limit = 100) {
  const rows = [];
  for (const [id, eps] of Object.entries(state.progress)) {
    for (const [key, v] of Object.entries(eps)) if (v.pos > 0 && state.anime[id]) rows.push({ anime: state.anime[id], key, ...v });
  }
  return rows.sort((a, b) => b.t - a.t).slice(0, limit);
}

export function clearHistory() {
  for (const eps of Object.values(state.progress)) {
    for (const [k, v] of Object.entries(eps)) { if (!v.watched) delete eps[k]; else v.pos = 0; }
  }
  save();
  notify("episode", null);
}

export function stats() {
  let eps = 0, sec = 0;
  for (const e of Object.values(state.progress)) for (const v of Object.values(e)) if (v.watched) { eps++; sec += v.dur || 0; }
  return { episodes: eps, hours: sec / 3600, inLists: Object.values(state.library).filter((e) => e.status).length };
}

/** [индекс серии, позиция в секундах], с которых продолжить просмотр. */
export const resumeTarget = (id, eps) => resumeFrom(eps, progress(id), lastProgress(id));

// ------------------------------------------------------------------ настройки
export const setting = (k, d) => (k in state.settings ? state.settings[k] : d);
export function setSetting(k, v) { state.settings[k] = v; save(); notify("settings", k); }
export const raw = () => state;
/** Для тестов: сохранить сразу. */
export const flush = writeNow;
