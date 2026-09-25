// Данные карточек из релизов AniLibria и из сохранённых тайтлов — одинаково на всех экранах.
import * as api from "../core/api/anilibria.js";
import * as store from "../core/state/store.js";
import { title } from "../domain/titles.js";
import { t } from "../i18n/index.js";

export const itemFromRelease = (rel) => ({
  id: rel.id, title: title(rel), poster: api.posterUrl(rel), release: rel, badge: rel.is_ongoing ? t("anime.ongoing_badge") : null,
  subtitle: [rel.year, rel.type?.description, rel.episodes_total ? t("anime.eps_short", { n: rel.episodes_total }) : ""].filter(Boolean).join(" · "),
});

export const itemFromStored = (a, extra = {}) => ({ id: a.id, title: a.title, poster: a.poster, subtitle: a.subtitle, ...extra });

/** Открыть страницу тайтла, запомнив карточку (чтобы библиотека работала офлайн). */
export function openAnime(nav, item) {
  if (item.release) store.remember(item.release, { poster: item.poster, subtitle: item.subtitle });
  nav.show("details", item.id);
}
