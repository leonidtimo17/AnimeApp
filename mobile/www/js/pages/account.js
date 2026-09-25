// Вкладка Shikimori: вход, статистика, синхронизация списка.
import { renderAccountBox } from "../features/shikimori/account-box.js";
import { t } from "../i18n/index.js";

export default function account(view, _arg, nav) {
  view.innerHTML = `<h1>Shikimori</h1><div class="panel" id="shk"></div>
    <p class="muted">${t("shikimori.read_without_login")}</p>`;
  renderAccountBox(view.querySelector("#shk"), () => nav.active() && nav.replace());
}
