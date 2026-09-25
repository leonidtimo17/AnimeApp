// AnimeApp для планшета: запуск приложения.
//
// Порядок: хранилище → навигация и вкладки → главная → сеть (ОДИН замер скорости, когда главная загрузилась)
// → синхронизация с Shikimori → соглашение при первом запуске.
import * as api from "../core/api/anilibria.js";
import * as persistent from "../core/cache/persistent.js";
import * as store from "../core/state/store.js";
import { createBottomNav } from "../components/BottomNav.js";
import { closeSheet } from "../components/Sheet.js";
import { toast } from "../components/Toast.js";
import { ensureAccepted } from "../features/legal/legal.js";
import { setAfterClose } from "../features/player/launch.js";
import * as player from "../features/player/player.js";
import * as shiki from "../services/shiki.js";
import { network } from "./network.js";
import { i18n, t, translateDom } from "../i18n/index.js";
import { onBack } from "../platform/platform.js";
import { createRouter } from "./router.js";
import account from "../pages/account.js";
import catalog from "../pages/catalog.js";
import details from "../pages/details.js";
import home from "../pages/home.js";
import library from "../pages/library.js";
import recs from "../pages/recs.js";
import schedule from "../pages/schedule.js";
import search from "../pages/search.js";
import settings from "../pages/settings.js";

const BANDWIDTH_DELAY_MS = 2000;   // замер — после того, как главная и её постеры загрузились

const view = document.getElementById("view");
const tabs = createBottomNav(document.getElementById("tabs"), (name) => router.reset(name));
const router = createRouter({
  view, fallback: "home",
  pages: { home, schedule, search, catalog, account, library, recs, details, settings },
  onChange: (route) => tabs.select(route.name),
});
setAfterClose(() => router.refresh());

// ------------------------------------------------------------------ «назад» и клавиатура
function back() {
  if (closeSheet()) return true;
  if (player.isOpen()) { player.close(); return true; }
  return router.back();
}
// Esc на Android может прийти ещё и как системная «Назад» — второе срабатывание подряд пропускаем.
let lastEsc = 0;
onBack(() => (Date.now() - lastEsc < 400 ? true : back()));
// Клавиатура (планшет с клавиатурой): Esc — назад, Ctrl+F или / — поиск. Клавиши плеера — в features/player/hotkeys.js.
document.addEventListener("keydown", (e) => {
  const typing = e.target.closest?.("input, textarea, select");
  if (e.key === "Escape") {
    e.preventDefault();
    lastEsc = Date.now();
    if (typing) e.target.blur();
    else back();
    return;
  }
  if (typing || player.isOpen()) return;
  if ((e.ctrlKey && e.code === "KeyF") || e.key === "/") {
    e.preventDefault();
    if (router.current?.name !== "search") router.show("search");
    setTimeout(() => view.querySelector("#q")?.focus(), 50);
  }
});

// ------------------------------------------------------------------ язык
// Сменили язык — подписи вкладок и текущий экран перерисовываются сразу, без перезапуска приложения
translateDom(document);
i18n.subscribe(() => {
  translateDom(document);
  tabs.setAccount(shiki.user());
  router.refresh();
});

// ------------------------------------------------------------------ Shikimori и сеть
tabs.setAccount(shiki.user());
store.subscribe((kind, key) => { if (kind === "settings" && key === "shikiAuth") tabs.setAccount(shiki.user()); });
shiki.startSync();

const offline = document.getElementById("offline");
network.subscribe((st) => { offline.hidden = st.isOnline; });
network.onConnectionChange((kind) => { if (kind === "online") toast(t("network.back_online")); });

persistent.clearLegacy();            // старый кэш ответов из localStorage (до 1.8) — освобождаем место для списков
router.show("home");
// Один замер скорости за запуск — на последней серии свежего релиза (тот же запрос, что у главной)
network.start(async () => {
  const releases = await api.latest();
  await new Promise((r) => setTimeout(r, BANDWIDTH_DELAY_MS));
  return api.sampleStream(releases);
});
ensureAccepted();   // при первом запуске — соглашение
