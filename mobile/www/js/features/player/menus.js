// Меню плеера: озвучки, сезоны и фильмы; список серий для боковой панели.
import * as store from "../../core/state/store.js";
import { episodeRow } from "../../components/EpisodeTile.js";
import { sheet } from "../../components/Sheet.js";
import { menuGroups } from "../../domain/dubs.js";
import { progressFraction } from "../../domain/episodes.js";
import { fmtOrd } from "../../utils/format.js";
import { t } from "../../i18n/index.js";

/** getState() → [ключ текущей серии, позиция в секундах]. */
export function menus(opts, getState) {
  return {
    dub() {
      sheet(menuGroups(opts.dubs).map(([title, items]) => ({ title: t(title), items: items.map((d) => ({ label: d.name, on: d.id === opts.dub.id,
        action: () => { const [key, pos] = getState(); opts.onDub(d, key, pos); } })) })));
    },
    seasons() {
      sheet([{ title: t("anime.seasons"), items: opts.seasons.map((e) => ({ label: `${e.label} · ${e.year || t("anime.announce")} — ${e.name}`,
        on: e.current, action: () => !e.current && opts.onSeason(e) })) }]);
    },
  };
}

/** Строки серий с кадрами; filter "new" — только непросмотренные (и текущая). */
export function episodeRows(opts, idx, filter = "all") {
  const prog = store.progress(opts.rel.id);
  return opts.eps.map((e, i) => [e, i]).filter(([e, i]) => filter === "all" || !prog[e.key]?.watched || i === idx)
    .map(([e, i]) => episodeRow({ key: fmtOrd(e.ordinal), name: e.name, preview: e.preview, poster: opts.poster,
      current: i === idx, watched: !!prog[e.key]?.watched, progress: progressFraction(prog[e.key]) }, i)).join("");
}

/** HTML списка серий для боковой панели плеера. */
export const episodeList = (opts, idx) => `<div class="ttl">${t("player.episodes_count", { n: opts.eps.length })}</div>${episodeRows(opts, idx)}`;

/** С какой серии и позиции открыть: [индекс, секунды]. */
export function startIndex(opts) {
  const prog = store.progress(opts.rel.id);
  if (opts.key) {
    const i = Math.max(0, opts.eps.findIndex((e) => e.key === opts.key));
    const p = prog[opts.eps[i].key];
    return [i, opts.position ?? (p && !p.watched ? p.pos : 0)];
  }
  const [i, pos] = store.resumeTarget(opts.rel.id, opts.eps);
  return [i, opts.position ?? pos];
}
