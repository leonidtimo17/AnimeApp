// Предстоящие серии: дата выхода в Японии (Shikimori) и примерная дата озвучки (по дню выхода серий у AniLibria).

/** [{n, date|null, state: "upcoming"|"no_dub"|"dub"}] */
export function upcoming(rel, info, knownKeys, dubWeekday, now = new Date()) {
  const known = knownKeys.map(Number).filter((x) => !Number.isNaN(x));
  const maxKnown = known.length ? Math.floor(Math.max(...known)) : 0;
  const status = info?.status;
  const total = info?.episodes || rel.episodes_total || 0;
  let aired = info?.episodes_aired || 0;
  if (status === "released") aired = Math.max(aired, total);
  let dubDate = null;
  if (dubWeekday) {
    const d = new Date(now); d.setHours(0, 0, 0, 0);
    const today = ((d.getDay() + 6) % 7) + 1;
    d.setDate(d.getDate() + ((((dubWeekday - today) % 7) + 7) % 7 || 7));
    dubDate = (i) => new Date(d.getTime() + i * 7 * 86400_000);
  }
  const out = [];
  for (let n = maxKnown + 1, i = 0; n <= Math.min(aired, maxKnown + 24); n++, i++) {
    out.push(dubDate ? { n, date: dubDate(i), state: "dub" } : { n, date: null, state: "no_dub" });
  }
  if (status !== "ongoing" && status !== "anons") return out;
  const start = Math.max(aired, maxKnown) + 1;
  const end = total >= start ? total : start + 2;
  const nxt = info.next_episode_at ? new Date(info.next_episode_at) : (status === "anons" && info.aired_on ? new Date(info.aired_on) : null);
  for (let n = start, i = 0; n <= Math.min(end, start + 24); n++, i++) {
    out.push({ n, date: nxt ? new Date(nxt.getTime() + i * 7 * 86400_000) : null, state: "upcoming" });
  }
  return out;
}
