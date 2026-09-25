// Главная: «Продолжить просмотр», «Выходит сегодня», новые серии, «Хочу посмотреть», популярное.
import * as api from "../core/api/anilibria.js";
import * as store from "../core/state/store.js";
import { renderCards } from "../components/AnimeCard.js";
import { fa } from "../components/Icons.js";
import { showError, skeletonCards } from "../components/StateView.js";
import { isoWeekday } from "../utils/format.js";
import { itemFromRelease, itemFromStored, openAnime } from "../app/items.js";
import { play } from "../features/player/launch.js";
import { t } from "../i18n/index.js";

const strip = (title, id) => `<h2>${title}</h2><div class="strip" id="${id}">${skeletonCards(6)}</div>`;

export default function home(view, _arg, nav) {
  view.innerHTML = `<div class="row-head"><h1>${t("home.title")}</h1><button class="btn small" id="sched">${fa("calendar")} ${t("schedule.title")}</button></div>
    <div id="cont"></div>${strip(t("home.today"), "today")}${strip(t("home.latest"), "latest")}
    <div id="wish"></div>${strip(t("home.popular"), "top")}`;
  const $ = (s) => view.querySelector(s);
  const open = (item) => openAnime(nav, item);
  $("#sched").onclick = () => nav.show("schedule");

  const cont = store.continueWatching().map(({ anime, last }) => itemFromStored(anime, {
    progress: last.dur ? Math.min(1, last.pos / last.dur) : 0,
    subtitle: last.watched ? t("home.watched_next", { n: last.key }) : t("player.episode_n", { n: last.key }) }));
  if (cont.length) {
    $("#cont").innerHTML = `<h2>${t("home.continue")}</h2><div class="strip" id="contS"></div>`;
    renderCards($("#contS"), cont, { onOpen: (it) => play(it.id) });
  }
  const wish = store.library("planned").slice(0, 20).map((a) => itemFromStored(a));
  if (wish.length) {
    $("#wish").innerHTML = `<h2>${t("status.planned")}</h2><div class="strip" id="wishS"></div>`;
    renderCards($("#wishS"), wish, { onOpen: open });
  }

  const load = (id, fetcher, toItems, empty) => {
    const el = $(`#${id}`);
    el.innerHTML = skeletonCards(6);
    fetcher().then((d) => nav.active() && renderCards(el, toItems(d), { onOpen: open, empty }))
      .catch((e) => nav.active() && showError(el, e, () => load(id, fetcher, toItems, empty)));
  };
  load("latest", () => api.latest(nav.signal), (d) => d.map(itemFromRelease));
  load("top", () => api.catalog({ sorting: "RATING_DESC", limit: 24 }, nav.signal), (d) => d.data.map(itemFromRelease));
  load("today", () => api.schedule(nav.signal), (d) => {
    const today = isoWeekday();
    return d.filter((x) => x.release?.publish_day?.value === today).map((x) => ({ ...itemFromRelease(x.release),
      subtitle: x.next_release_episode_number ? t("home.expected_today", { n: x.next_release_episode_number }) : "" }));
  }, t("home.nothing_today"));
}
