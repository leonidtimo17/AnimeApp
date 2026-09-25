// Источник видео Kodik для серии: нормализованный VideoSource, кэш и отмена.
//
// Kodik отдаёт видео только через свой встраиваемый плеер (публичный iframe-API). Прямые ссылки на поток
// спрятаны внутри плеера и шифруются — разбирать их ненадёжно и против правил Kodik, поэтому iframe остаётся,
// а надёжность — за счёт порядка загрузки (сессии), start_from и понятных ошибок.
import { request } from "../core/api/http.js";
import { NoSourceError } from "../core/errors.js";

const ANIMELIB = "https://api.cdnlibs.org/api";
const ANIMELIB_H = { "Site-Id": "5" };
const PLAYERS_TTL = 600;   // список плееров серии: одна и та же серия при повторном открытии — без запроса

/** Нормализованная ссылка Kodik: https, без своего выбора озвучки и серий (они — в нашем интерфейсе), с позицией. */
export function kodikUrl(src, { startFrom = 0 } = {}) {
  const url = new URL(src.startsWith("//") ? "https:" + src : src);
  url.searchParams.set("translations", "false");
  if (url.pathname.startsWith("/season/") || url.pathname.startsWith("/serial/")) url.searchParams.set("only_episode", "true");
  if (startFrom > 5) url.searchParams.set("start_from", String(Math.floor(startFrom)));
  else url.searchParams.delete("start_from");
  return url.href;
}

/** Плеер Kodik нужной команды из списка плееров серии AnimeLib; нет её — первый доступный (fallback). */
export function pickKodikPlayer(players, teamId) {
  const kodik = (players || []).filter((p) => p.player === "Kodik" && p.src);
  const exact = kodik.filter((p) => p.team?.id === +teamId);
  const chosen = (exact.length ? exact : kodik)[0];
  return chosen ? { src: chosen.src, team: chosen.team?.name || null, fallback: !exact.length } : null;
}

/**
 * @param {import("../domain/models.js").Episode} ep
 * @param {string|number} teamId
 * @param {{signal?: AbortSignal, startFrom?: number, fallbackName?: string}} o
 * @returns {Promise<import("../domain/models.js").VideoSource>}
 */
export async function resolveKodikSource(ep, teamId, { signal, startFrom = 0, fallbackName = null } = {}) {
  if (ep.kodik) return { kind: "iframe", url: kodikUrl(ep.kodik, { startFrom }), team: fallbackName, fallback: false };
  if (!ep.animelib) throw new NoSourceError("no episode id");
  const d = await request(`${ANIMELIB}/episodes/${ep.animelib}`, { headers: ANIMELIB_H, ttl: PLAYERS_TTL, signal });
  const chosen = pickKodikPlayer(d?.data?.players, teamId);
  if (!chosen) throw new NoSourceError("no kodik player");
  return { kind: "iframe", url: kodikUrl(chosen.src, { startFrom }), team: chosen.team, fallback: chosen.fallback };
}
