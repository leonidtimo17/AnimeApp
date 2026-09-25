// Серии: единый формат для всех источников, продолжение просмотра, объединение серий разных озвучек.
// Ключ серии — её номер: прогресс общий для всех озвучек.

export const EPISODES_PAGE = 100;

export function parseOrdinal(v, fallback) {
  const n = parseFloat(String(v ?? "").replace(",", "."));
  if (!Number.isNaN(n)) return n;
  const m = String(v || "").match(/\d+(?:[.,]\d+)?/);
  return m ? parseFloat(m[0].replace(",", ".")) : fallback;
}

/**
 * С какой серии и позиции продолжать: [index, позиция в секундах].
 * progress — {ключ: {watched, pos}}, last — последняя запись ({key, watched, pos}).
 */
export function resumeTarget(eps, progress, last) {
  if (!eps.length) return [0, 0];
  let idx = last ? eps.findIndex((e) => e.key === last.key) : -1;
  if (idx < 0) {
    idx = eps.findIndex((e) => !progress[e.key]?.watched);
    return idx < 0 ? [0, 0] : [idx, progress[eps[idx].key]?.pos || 0];
  }
  if (last.watched) {
    for (let i = idx + 1; i < eps.length; i++) if (!progress[eps[i].key]?.watched) return [i, progress[eps[i].key]?.pos || 0];
    return [idx, 0];
  }
  return [idx, last.pos];
}

/** Группа источника серии: у встроенного плеера — сама озвучка, у всех Kodik — общая. */
export const dubGroup = (d) => (d.native ? d.id : "kodik");

/** Серии из всех источников: {ключ: {ep, groups: Set, preview}}. */
export function unionEpisodes(lists) {
  const union = new Map();
  for (const [group, eps] of lists) {
    for (const ep of eps) {
      const slot = union.get(ep.key) || { ep, groups: new Set(), preview: null };
      slot.groups.add(group);
      slot.preview = slot.preview || ep.preview || null;
      union.set(ep.key, slot);
    }
  }
  return union;
}

/** Серии выбранной озвучки + те, что есть только в других, по порядку. */
export function shownEpisodes(own, union) {
  const ownKeys = new Set(own.map((x) => x.key));
  return [...own, ...[...union.values()].filter((s) => !ownKeys.has(s.ep.key)).map((s) => s.ep)]
    .sort((a, b) => a.ordinal - b.ordinal);
}

export const progressFraction = (p) => (p?.watched ? 1 : p?.dur ? p.pos / p.dur : 0);
