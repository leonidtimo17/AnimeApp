// Пользовательское соглашение и политика конфиденциальности: показ и согласие при первом запуске.
import * as store from "../../core/state/store.js";
import { esc } from "../../utils/dom.js";
import { i18n, t } from "../../i18n/index.js";

export const TERMS_VERSION = "2026-09-23";
// Юридические тексты — на русском (перевод документов — отдельная работа юристов); на других языках — пометка об этом
const DOCS = { terms: ["legal/TERMS.md", "legal.terms"], privacy: ["legal/PRIVACY.md", "legal.privacy"] };

async function text(key) {
  try {
    const r = await fetch(DOCS[key][0]);
    if (!r.ok) throw new Error();
    return await r.text();
  } catch (e) {
    console.warn("[AnimeApp] документ не найден", key, e);
    return `${t("legal.not_found")}\nhttps://github.com/leonidtimo17/AnimeApp`;
  }
}

/** Очень простой Markdown → HTML: заголовки, списки, жирный, ссылки. */
function render(md) {
  return esc(md).split("\n").map((l) => {
    if (l.startsWith("## ")) return `<h2>${l.slice(3)}</h2>`;
    if (l.startsWith("# ")) return `<h1>${l.slice(2)}</h1>`;
    if (l.startsWith("- ")) return `<div>• ${l.slice(2)}</div>`;
    if (!l.trim()) return "<br>";
    return `<div>${l}</div>`;
  }).join("")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

const russianNote = () => (i18n.locale === "ru" ? "" : `<p class="muted">${t("legal.russian_only")}</p>`);

/** Показать документ во весь экран. */
export async function showDoc(key) {
  const [, title] = DOCS[key];
  const box = document.createElement("div");
  box.className = "legal";
  box.innerHTML = `<div class="legal-head"><h1>${esc(t(title))}</h1><button class="btn small" data-close>${t("common.close")}</button></div>
    <div class="legal-body">${t("common.loading")}</div>`;
  document.body.appendChild(box);
  box.querySelector("[data-close]").onclick = () => box.remove();
  box.querySelector(".legal-body").innerHTML = russianNote() + render(await text(key));
}

/** Первый запуск: соглашение с кнопкой «Принимаю». */
export async function ensureAccepted() {
  if (store.setting("termsAccepted") === TERMS_VERSION) return;
  const box = document.createElement("div");
  box.className = "legal";
  box.innerHTML = `<div class="legal-head"><h1>${t("legal.terms")}</h1></div>
    <div class="legal-body">${t("common.loading")}</div>
    <div class="legal-foot"><button class="btn primary" data-ok disabled>${t("legal.accept")}</button>
      <span class="muted">${t("legal.scroll_to_end")}</span></div>`;
  document.body.appendChild(box);
  const body = box.querySelector(".legal-body"), ok = box.querySelector("[data-ok]");
  body.innerHTML = russianNote() + render(await text("terms")) + "<hr>" + render(await text("privacy"));
  const check = () => {
    if (body.scrollTop + body.clientHeight >= body.scrollHeight - 80) {
      ok.disabled = false;
      box.querySelector(".legal-foot .muted").textContent = "";
    }
  };
  body.addEventListener("scroll", check);
  check();
  ok.onclick = () => { store.setSetting("termsAccepted", TERMS_VERSION); box.remove(); };
}
