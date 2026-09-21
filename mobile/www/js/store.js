// Локальная база: списки, избранное, оценки, прогресс, настройки (localStorage).
export const STATUSES = {
  watching: "Смотрю", planned: "Хочу посмотреть", completed: "Просмотрено", postponed: "Отложено", dropped: "Брошено",
};

const KEY = "animeapp:v1";
const state = load();

function load() {
  try {
    return { anime: {}, library: {}, progress: {}, settings: {}, ...JSON.parse(localStorage.getItem(KEY) || "{}") };
  } catch { return { anime: {}, library: {}, progress: {}, settings: {} }; }
}

let saveTimer = null;
function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* переполнение — пропускаем */ }
  }, 200);
}
window.addEventListener("pagehide", () => { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch {} });

// ------------------------------------------------------------------ тайтлы (офлайн-кэш карточек)
export function remember(rel, extra = {}) {
  if (!rel?.id) return;
  const name = rel.name || {};
  state.anime[rel.id] = {
    id: rel.id, title: name.main || name.english || "", poster: extra.poster ?? state.anime[rel.id]?.poster ?? null,
    subtitle: extra.subtitle ?? state.anime[rel.id]?.subtitle ?? "", year: rel.year ?? null,
    type: rel.type?.description || "", genres: (rel.genres || []).map((g) => g.name).filter(Boolean),
    shikimori: rel.shikimori?.id || null, updated: Date.now(),
  };
  if (!state.anime[rel.id].genres.length && extra.genres) state.anime[rel.id].genres = extra.genres;
  save();
}
export const anime = (id) => state.anime[id];

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
export const setStatus = (id, status) => setEntry(id, { status });
export const setFavorite = (id, favorite) => setEntry(id, { favorite });
export const setScore = (id, score) => setEntry(id, { score });

export function library(status) {
  return Object.entries(state.library)
    .filter(([, e]) => (status === "favorite" ? e.favorite : e.status === status))
    .sort((a, b) => b[1].updated - a[1].updated)
    .map(([id]) => state.anime[id]).filter(Boolean);
}
export const libraryIds = () => Object.keys(state.library).map(Number);

// ------------------------------------------------------------------ прогресс (ключ серии — её номер)
export function progress(id) { return state.progress[id] || {}; }

export function saveProgress(id, key, ordinal, pos, dur, endingStart) {
  if (!dur || dur < 30) return false;
  const p = (state.progress[id] ||= {});
  const prev = p[key] || {};
  const tail = dur - pos;
  const watched = prev.watched || (endingStart && pos >= endingStart) || tail <= Math.min(180, dur * 0.1);
  p[key] = { pos, dur, ordinal, watched: !!watched, t: Date.now() };
  save();
  return !!watched && !prev.watched;
}

export function setWatched(id, key, ordinal, watched) {
  const p = (state.progress[id] ||= {});
  p[key] = { ...(p[key] || { pos: 0, dur: 0 }), ordinal, watched, pos: watched ? (p[key]?.pos || 0) : 0, t: Date.now() };
  save();
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
}

export function stats() {
  let eps = 0, sec = 0;
  for (const e of Object.values(state.progress)) for (const v of Object.values(e)) if (v.watched) { eps++; sec += v.dur || 0; }
  return { episodes: eps, hours: sec / 3600, inLists: Object.values(state.library).filter((e) => e.status).length };
}

export function resumeTarget(id, eps) {
  if (!eps.length) return [0, 0];
  const prog = progress(id);
  const last = lastProgress(id);
  let idx = last ? eps.findIndex((e) => e.key === last.key) : -1;
  if (idx < 0) {
    idx = eps.findIndex((e) => !prog[e.key]?.watched);
    return idx < 0 ? [0, 0] : [idx, prog[eps[idx].key]?.pos || 0];
  }
  if (last.watched) {
    for (let i = idx + 1; i < eps.length; i++) if (!prog[eps[i].key]?.watched) return [i, prog[eps[i].key]?.pos || 0];
    return [idx, 0];
  }
  return [idx, last.pos];
}

// ------------------------------------------------------------------ настройки
export const setting = (k, d) => (k in state.settings ? state.settings[k] : d);
export function setSetting(k, v) { state.settings[k] = v; save(); }
export const raw = () => state;
