// Обсуждение серии прямо в плеере: комментарии Shikimori, отметка момента серии, спойлеры.
import * as shiki from "./shiki.js";
import * as src from "./sources.js";
import { esc, fmtTime, toast } from "./ui.js";

const AGO = (iso) => {
  const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} мин назад`;
  if (s < 86400) return `${Math.round(s / 3600)} ч назад`;
  if (s < 86400 * 30) return `${Math.round(s / 86400)} дн назад`;
  return new Date(iso).toLocaleDateString("ru-RU");
};

/**
 * Панель комментариев. o: {rel, ep() → текущая серия, time() → секунды, seek(sec), osd(text)}.
 * Возвращает {toggle(), isOpen(), destroy()}.
 */
export function commentsPanel(root, o) {
  const box = document.createElement("div");
  box.className = "pl-comments";
  box.hidden = true;
  root.appendChild(box);
  const sid = shiki.sidOf(o.rel.id);
  let mode = "ep", topic = null, page = 1, forKey = null, timer = null;

  function shell() {
    const e = o.ep();
    box.innerHTML = `
      <div class="ch">
        <button class="chip${mode === "ep" ? " on" : ""}" data-ct="ep">${esc(src.fmtOrd(e.ordinal))} серия</button>
        <button class="chip${mode === "all" ? " on" : ""}" data-ct="all">Всё аниме</button>
        <span class="sp"></span>
        <button class="pl-btn" data-cx title="Закрыть">✕</button>
      </div>
      <div class="cl"><p class="muted">Загружаем обсуждение…</p></div>
      <div class="cf"></div>`;
    renderForm();
  }

  function renderForm() {
    const f = box.querySelector(".cf");
    if (!shiki.loggedIn()) {
      f.innerHTML = `<p class="muted">Чтобы писать комментарии, войдите через Shikimori в разделе «Моё».</p>`;
      return;
    }
    f.innerHTML = `
      <textarea placeholder="Комментарий к серии…" maxlength="4000"></textarea>
      <div class="cfr">
        <label><input type="checkbox" class="cts" checked> Момент <b class="ctime"></b></label>
        <label><input type="checkbox" class="csp"> Спойлер</label>
        <span class="sp"></span>
        <button class="btn small primary csend">Отправить</button>
      </div>`;
    tickTime();
  }
  const tickTime = () => { const t = box.querySelector(".ctime"); if (t) t.textContent = fmtTime(o.time()); };

  async function load(more = false) {
    const list = box.querySelector(".cl");
    if (!sid) { list.innerHTML = `<p class="muted">Этого тайтла нет на Shikimori — обсуждение недоступно.</p>`; return; }
    try {
      if (!more) {
        page = 1;
        topic = mode === "ep" ? await shiki.topic(sid, o.ep().ordinal) : await shiki.animeTopic(sid);
      }
      if (!topic) { list.innerHTML = `<p class="muted">На Shikimori нет темы для обсуждения.</p>`; return; }
      // Shikimori отдаёт на один комментарий больше, если есть следующая страница
      const got = await shiki.comments(topic.id, page);
      const items = got.slice(0, 30);
      if (!more) list.innerHTML = mode === "ep" && !topic.episode
        ? `<p class="muted hint">Отдельной темы у этой серии нет — показано общее обсуждение тайтла, ваш комментарий будет подписан номером серии.</p>` : "";
      list.querySelector(".cmore")?.remove();
      if (!items.length && !more) list.insertAdjacentHTML("beforeend", `<p class="muted">Пока никто не написал — будьте первым.</p>`);
      for (const c of items) {
        list.insertAdjacentHTML("beforeend", `<div class="cm">
          <img src="${esc(c.user?.avatar || "")}" alt="" loading="lazy">
          <div><div class="cmh"><b>${esc(c.user?.nickname || "")}</b><span class="muted">${esc(AGO(c.created_at))}</span></div>
          <div class="cmb">${shiki.renderBody(c.body, esc)}</div></div></div>`);
      }
      if (got.length > 30) list.insertAdjacentHTML("beforeend", `<button class="btn small cmore">Показать ещё</button>`);
    } catch (e) {
      list.innerHTML = `<p class="muted">Не удалось загрузить обсуждение: ${esc(e.message)}</p>`;
    }
  }

  async function send() {
    const ta = box.querySelector("textarea");
    const text = ta.value.trim();
    if (!text || !topic) return;
    const e = o.ep();
    const moment = box.querySelector(".cts").checked ? fmtTime(o.time()) : "";
    // В общей теме тайтла подписываем номер серии, чтобы было понятно, о чём речь
    const tag = [topic.episode ? "" : `${src.fmtOrd(e.ordinal)} серия`, moment].filter(Boolean).join(", ");
    const body = (tag ? `[b]${tag}[/b] ` : "") + (box.querySelector(".csp").checked ? `[spoiler]${text}[/spoiler]` : text);
    const btn = box.querySelector(".csend");
    btn.disabled = true;
    try {
      await shiki.postComment(topic.id, body);
      ta.value = "";
      toast("Комментарий опубликован на Shikimori");
      load();
    } catch (err) {
      toast(`Не удалось отправить: ${err.message}`);
    } finally { btn.disabled = false; }
  }

  box.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const t = ev.target;
    if (t.closest("[data-cx]")) { toggle(false); return; }
    const tab = t.closest("[data-ct]");
    if (tab && tab.dataset.ct !== mode) { mode = tab.dataset.ct; shell(); load(); return; }
    const ts = t.closest(".ts");
    if (ts) { o.seek(+ts.dataset.t); o.osd(`Перемотка на ${ts.textContent}`); return; }
    const sp = t.closest(".spoiler");
    if (sp) { sp.classList.toggle("open"); return; }
    if (t.closest(".cmore")) { page++; load(true); return; }
    if (t.closest(".csend")) send();
  });
  // Касания внутри панели не должны закрывать плеер свайпом и перематывать видео
  ["pointerdown", "touchstart", "dblclick"].forEach((n) => box.addEventListener(n, (ev) => ev.stopPropagation(), { passive: true }));

  function toggle(show = box.hidden) {
    box.hidden = !show;
    clearInterval(timer);
    if (!show) return;
    const key = `${o.ep().key}|${mode}`;
    if (key !== forKey || !box.innerHTML) { forKey = key; shell(); load(); }
    timer = setInterval(tickTime, 1000);
  }
  return {
    toggle,
    isOpen: () => !box.hidden,
    /** Сменилась серия — при следующем открытии загрузим её обсуждение. */
    episodeChanged() { forKey = null; if (!box.hidden) toggle(true); },
    /** Перенести панель: под видео (страница просмотра) или поверх видео (полный экран). */
    mount(el) { if (box.parentNode !== el) el.appendChild(box); },
    el: box,
    destroy() { clearInterval(timer); box.remove(); },
  };
}
