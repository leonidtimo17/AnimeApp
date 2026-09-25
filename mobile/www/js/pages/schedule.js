// Расписание выхода серий на неделю.
import * as api from "../core/api/anilibria.js";
import { renderCards } from "../components/AnimeCard.js";
import { showError, skeletonCards } from "../components/StateView.js";
import { isoWeekday } from "../utils/format.js";
import { formatDay, t, weekdayName } from "../i18n/index.js";
import { itemFromRelease, openAnime } from "../app/items.js";

export default function schedule(view, _arg, nav) {
  const today = isoWeekday();
  const order = [...Array(7)].map((_, i) => ((today - 1 + i) % 7) + 1);
  view.innerHTML = `<h1>${t("schedule.title")}</h1>` + order.map((d, i) => {
    const date = new Date(Date.now() + i * 86400_000);
    return `<h2>${weekdayName(d)}, ${formatDay(date)}${i === 0 ? ` — ${t("dates.today")}` : ""}</h2>
      <div class="strip" id="d${d}">${skeletonCards(4)}</div>`;
  }).join("");
  const load = () => api.schedule(nav.signal).then((data) => {
    if (!nav.active()) return;
    for (const d of order) {
      const items = data.filter((x) => x.release?.publish_day?.value === d).map((x) => ({ ...itemFromRelease(x.release),
        subtitle: x.next_release_episode_number ? t("schedule.expected", { n: x.next_release_episode_number }) : "" }));
      renderCards(view.querySelector(`#d${d}`), items, { onOpen: (it) => openAnime(nav, it), empty: t("schedule.nothing") });
    }
  }).catch((e) => nav.active() && showError(view.querySelector(`#d${today}`), e, load));
  load();
}
