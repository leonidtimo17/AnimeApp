// Нижнее меню вкладок. Вкладка Shikimori показывает ник и аватар, когда пользователь вошёл.
import { I } from "./Icons.js";
import { t } from "../i18n/index.js";

export function createBottomNav(el, onTab) {
  el.addEventListener("click", (e) => { const b = e.target.closest("[data-tab]"); if (b) onTab(b.dataset.tab); });
  return {
    /** Подсветить вкладку текущего экрана. */
    select(name) { el.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name)); },
    /** Подпись вкладки Shikimori: ник и аватар, если вошли. */
    setAccount(user) {
      const b = el.querySelector("#tabShiki");
      if (!b) return;
      b.querySelector("span").textContent = user ? user.nickname : "Shikimori";   // название сервиса не переводится
      b.setAttribute("aria-label", user ? t("navigation.account_user", { name: user.nickname }) : "Shikimori");
      const old = b.querySelector(".fa, .tab-av");
      const icon = user?.avatar ? Object.assign(document.createElement("img"), { className: "tab-av", src: user.avatar, alt: "" })
        : Object.assign(document.createElement("i"), { className: "fa", innerHTML: I.link });
      old.replaceWith(icon);
    },
  };
}
