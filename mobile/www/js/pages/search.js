// Поиск: пока пользователь печатает, ждём паузу (debounce); новый поиск отменяет запросы прошлого.
import * as api from "../core/api/anilibria.js";
import * as store from "../core/state/store.js";
import { cardCount, renderCards } from "../components/AnimeCard.js";
import { showError } from "../components/StateView.js";
import { debounce } from "../utils/dom.js";
import { itemFromRelease, openAnime } from "../app/items.js";
import { createSearchSession } from "../features/search/search-session.js";
import * as src from "../services/sources.js";
import { t } from "../i18n/index.js";

const SEARCH_DEBOUNCE_MS = 450;
const MIN_FIRST_PORTION = 20;   // мало нашлось — сразу добираем из полного каталога, без лишнего нажатия

export default function search(view, _arg, nav) {
  view.innerHTML = `<h1>${t("search.title")}</h1><input class="input" id="q" type="search" enterkeyhint="search" placeholder="${t("search.placeholder")}" aria-label="${t("search.title")}" autocomplete="off">
    <p class="muted" id="cnt"></p><div class="grid" id="res"></div>
    <div class="more-row"><button class="btn" id="more" hidden>${t("common.show_more")}</button></div>`;
  const q = view.querySelector("#q"), res = view.querySelector("#res"), cnt = view.querySelector("#cnt");
  const more = view.querySelector("#more");
  const open = (item) => openAnime(nav, item);
  q.value = store.setting("lastSearch", "");
  let session = null, ctrl = null;

  async function loadMore() {
    const my = session, signal = ctrl.signal;
    more.disabled = true;
    more.textContent = t("common.loading");
    try {
      const items = await my.next(signal);
      if (my !== session) return;
      renderCards(res, items, { onOpen: open, append: true });
      const shown = cardCount(res);
      cnt.textContent = shown
        ? t(my.extras ? "search.found_extra" : "search.found", { n: my.found, extra: my.extras, shown })
        : t("search.nothing");
      more.disabled = false;
      more.textContent = t("common.show_more");
      more.hidden = my.exhausted;
      if (!more.hidden && shown < MIN_FIRST_PORTION) loadMore();
    } catch (e) {
      if (my !== session) return;
      more.disabled = false;
      more.textContent = t("common.show_more");
      showError(cnt, e, loadMore, "search.failed");
    }
  }

  const run = () => {
    const text = q.value.trim();
    store.setSetting("lastSearch", text);
    ctrl?.abort();                                  // ответы прошлого поиска больше не нужны
    ctrl = new AbortController();
    nav.signal.addEventListener("abort", () => ctrl.abort(), { once: true });
    session = createSearchSession(text, { catalog: api.catalog, shikiSearch: src.shikiSearch,
      fromRelease: itemFromRelease, fromShiki: src.shikiItem });
    renderCards(res, [], { onOpen: open });
    more.hidden = true;
    if (!text) { cnt.textContent = ""; return; }
    cnt.textContent = t("search.searching");
    loadMore();
  };
  const runLater = debounce(run, SEARCH_DEBOUNCE_MS);
  nav.onCleanup(runLater.cancel);
  more.onclick = loadMore;
  q.oninput = runLater;
  run();
}
