// Сценарий «Смотреть»: свежие ссылки на видео → озвучка → серии → прогресс с Shikimori → кадры серий → плеер.
import * as api from "../../core/api/anilibria.js";
import * as store from "../../core/state/store.js";
import { friendlyError } from "../../components/StateView.js";
import { toast } from "../../components/Toast.js";
import { NetworkError } from "../../core/errors.js";
import { t } from "../../i18n/index.js";
import * as shiki from "../../services/shiki.js";
import * as src from "../../services/sources.js";
import * as player from "./player.js";

let afterClose = () => {};
/** Что сделать, когда пользователь закрыл плеер (обычно — перерисовать текущий экран). */
export const setAfterClose = (fn) => { afterClose = fn; };

let token = 0;

/** play(id, ключ серии — "" = продолжить, {rel, dub, position}) */
export async function play(id, key = "", { rel = null, dub = null, position = null } = {}) {
  const my = ++token;           // нажали «Смотреть» у другого тайтла — прежний запуск отменяется
  toast(t("player.loading_episodes"), 1500);
  try {
    // Всегда свежие ссылки на поток (после смены сети/VPN старые не работают)
    rel = await src.loadRelease(id, true).catch(() => rel);
    if (!rel) throw new NetworkError("release unavailable");
    const { dubs } = await src.findDubs(rel);
    dub = dub || src.chooseDub(rel, dubs, store);
    if (!dub) return toast(t("anime.no_episodes_anywhere"));
    store.setSetting(`dub:${id}`, dub.id);
    let eps = await src.episodes(rel, dub);
    if (!eps.length) return toast(t("anime.no_episodes_in_dub"));
    // Серии, отмеченные на Shikimori, отмечаем и здесь — чтобы продолжить с нужной
    const [pulled, pv, seasons] = await Promise.all([shiki.pullProgress(id, eps).catch(() => 0),
      src.previews(rel, dubs).catch(() => ({})), src.franchise(rel).catch(() => [])]);
    if (my !== token) return;
    if (pulled) toast(t("shikimori.pulled", { n: pulled }));
    eps = eps.map((e) => ({ ...e, preview: e.preview || pv[e.key] || null }));
    player.open({
      rel, dub, dubs, eps, seasons, poster: api.posterUrl(rel), key: eps.some((e) => e.key === key) ? key : "", position,
      onDub: (d, k, pos) => { store.setSetting("preferredDub", d.name); play(id, k, { rel, dub: d, position: pos > 5 ? pos : null }); },
      onSeason: (entry) => play(entry.releaseId, ""),
      onClose: () => afterClose(),
      // Переподключение не помогло — получаем свежие ссылки и продолжаем с того же места
      onStale: (k, pos) => { src.invalidate(id); play(id, k, { dub, position: pos > 5 ? pos : null }); },
    });
  } catch (e) {
    if (my === token) toast(friendlyError(e, "player.errors.open_failed"));
  }
}
