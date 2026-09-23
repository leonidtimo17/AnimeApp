// Пользовательское соглашение и политика конфиденциальности: показ и согласие при первом запуске.
import * as store from "./store.js";
import { esc } from "./ui.js";

export const TERMS_VERSION = "2026-09-23";
const DOCS = { terms: ["legal/TERMS.md", "Пользовательское соглашение"],
  privacy: ["legal/PRIVACY.md", "Политика конфиденциальности"] };

async function text(key) {
  try {
    const r = await fetch(DOCS[key][0]);
    if (!r.ok) throw new Error();
    return await r.text();
  } catch {
    return "Текст не найден. Актуальная версия — в репозитории проекта:\nhttps://github.com/leonidtimo17/AnimeApp";
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

/** Показать документ во весь экран. */
export async function showDoc(key) {
  const [, title] = DOCS[key];
  const box = document.createElement("div");
  box.className = "legal";
  box.innerHTML = `<div class="legal-head"><h1>${esc(title)}</h1><button class="btn small" data-close>Закрыть</button></div>
    <div class="legal-body">Загружаем…</div>`;
  document.body.appendChild(box);
  box.querySelector("[data-close]").onclick = () => box.remove();
  box.querySelector(".legal-body").innerHTML = render(await text(key));
}

/** Первый запуск: соглашение с кнопкой «Принимаю». */
export async function ensureAccepted() {
  if (store.setting("termsAccepted") === TERMS_VERSION) return;
  const box = document.createElement("div");
  box.className = "legal";
  box.innerHTML = `<div class="legal-head"><h1>Пользовательское соглашение</h1></div>
    <div class="legal-body">Загружаем…</div>
    <div class="legal-foot"><button class="btn primary" data-ok disabled>Принимаю</button>
      <span class="muted">Прокрутите до конца</span></div>`;
  document.body.appendChild(box);
  const body = box.querySelector(".legal-body"), ok = box.querySelector("[data-ok]");
  body.innerHTML = render(await text("terms")) + "<hr>" + render(await text("privacy"));
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
