// Обсуждение серии прямо в плеере: комментарии Shikimori, отметка момента серии, спойлеры.
import { isAbort } from "../../core/errors.js";
import { friendlyError } from "../../components/StateView.js";
import { toast } from "../../components/Toast.js";
import { formatAgo as AGO, t } from "../../i18n/index.js";
import { esc } from "../../utils/dom.js";
import { fmtOrd, fmtTime } from "../../utils/format.js";
import * as shiki from "../../services/shiki.js";

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
  let mode = "ep", topic = null, page = 1, forKey = null, timer = null, ctrl = null;

  function shell() {
    const e = o.ep();
    box.innerHTML = `
      <div class="ch">
        <button class="chip${mode === "ep" ? " on" : ""}" data-ct="ep">${esc(t("player.episode_n", { n: fmtOrd(e.ordinal) }))}</button>
        <button class="chip${mode === "all" ? " on" : ""}" data-ct="all">${t("comments.whole_anime")}</button>
        <span class="sp"></span>
        <button class="pl-btn" data-cx title="${t("common.close")}" aria-label="${t("common.close")}">✕</button>
      </div>
      <div class="cl"><p class="muted">${t("comments.loading")}</p></div>
      <div class="cf"></div>`;
    renderForm();
  }

  function renderForm() {
    const f = box.querySelector(".cf");
    if (!shiki.loggedIn()) {
      f.innerHTML = `<p class="muted">${t("comments.login_hint")}</p>`;
      return;
    }
    f.innerHTML = `
      <textarea placeholder="${t("comments.placeholder")}" aria-label="${t("comments.placeholder")}" maxlength="4000"></textarea>
      <div class="cfr">
        <label><input type="checkbox" class="cts" checked> ${t("comments.moment")} <b class="ctime"></b></label>
        <label><input type="checkbox" class="csp"> ${t("comments.spoiler")}</label>
        <span class="sp"></span>
        <button class="btn small primary csend">${t("comments.send")}</button>
      </div>`;
    tickTime();
  }
  const tickTime = () => { const t = box.querySelector(".ctime"); if (t) t.textContent = fmtTime(o.time()); };

  async function load(more = false) {
    const list = box.querySelector(".cl");
    if (!sid) { list.innerHTML = `<p class="muted">${t("comments.not_on_shikimori")}</p>`; return; }
    if (!more) { ctrl?.abort(); ctrl = new AbortController(); }   // обсуждение прошлой серии больше не нужно
    const signal = ctrl.signal;
    try {
      if (!more) {
        page = 1;
        topic = mode === "ep" ? await shiki.topic(sid, o.ep().ordinal) : await shiki.animeTopic(sid);
      }
      if (signal.aborted) return;
      if (!topic) { list.innerHTML = `<p class="muted">${t("comments.no_topic")}</p>`; return; }
      // Shikimori отдаёт на один комментарий больше, если есть следующая страница
      const got = await shiki.comments(topic.id, page, signal);
      const items = got.slice(0, 30);
      if (!more) list.innerHTML = mode === "ep" && !topic.episode
        ? `<p class="muted hint">${t("comments.general_topic")}</p>` : "";
      list.querySelector(".cmore")?.remove();
      // Вся страница комментариев — одной вставкой
      const html = items.map((c) => `<div class="cm">
          <img src="${esc(c.user?.avatar || "")}" alt="" loading="lazy">
          <div><div class="cmh"><b>${esc(c.user?.nickname || "")}</b><span class="muted">${esc(AGO(c.created_at))}</span>
            <button class="creply" data-cr="${c.id}" data-cn="${esc(c.user?.nickname || "")}">${t("comments.reply")}</button></div>
          <div class="cmb">${shiki.renderBody(c.body, esc)}</div></div></div>`).join("");
      list.insertAdjacentHTML("beforeend", (!items.length && !more ? `<p class="muted">${t("comments.empty")}</p>` : "")
        + html + (got.length > 30 ? `<button class="btn small cmore">${t("common.show_more")}</button>` : ""));
    } catch (e) {
      if (!isAbort(e)) list.innerHTML = `<p class="muted">${esc(friendlyError(e, "comments.load_failed"))}</p>`;
    }
  }

  async function send() {
    const ta = box.querySelector("textarea");
    const text = ta.value.trim();
    if (!text || !topic) return;
    const e = o.ep();
    const moment = box.querySelector(".cts").checked ? fmtTime(o.time()) : "";
    // В общей теме тайтла подписываем номер серии, чтобы было понятно, о чём речь
    // Подпись в самом комментарии — для читателей Shikimori (сайт на русском), поэтому по-русски
    const tag = [topic.episode ? "" : `${fmtOrd(e.ordinal)} серия`, moment].filter(Boolean).join(", ");
    const body = (tag ? `[b]${tag}[/b] ` : "") + (box.querySelector(".csp").checked ? `[spoiler]${text}[/spoiler]` : text);
    const btn = box.querySelector(".csend");
    btn.disabled = true;
    try {
      await shiki.postComment(topic.id, body);
      ta.value = "";
      toast(t("comments.posted"));
      load();
    } catch (err) {
      toast(friendlyError(err, "comments.send_failed"));
    } finally { btn.disabled = false; }
  }

  box.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const t = ev.target;
    if (t.closest("[data-cx]")) { toggle(false); return; }
    const tab = t.closest("[data-ct]");
    if (tab && tab.dataset.ct !== mode) { mode = tab.dataset.ct; shell(); load(); return; }
    const ts = t.closest(".ts");
    if (ts) { o.seek(+ts.dataset.t); o.osd(t("comments.seek_to", { time: ts.textContent })); return; }
    const sp = t.closest(".spoiler");
    if (sp) { sp.classList.toggle("open"); return; }
    if (t.closest(".cmore")) { page++; load(true); return; }
    const re = t.closest("[data-cr]");
    if (re) {   // цитата-ответ, как на Shikimori
      const ta = box.querySelector("textarea");
      if (!ta) { toast(t("comments.login_to_reply")); return; }
      ta.value = `[comment=${re.dataset.cr}]${re.dataset.cn}[/comment], ${ta.value}`;
      ta.focus();
      ta.setSelectionRange(ta.value.length, ta.value.length);
      return;
    }
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
    destroy() { clearInterval(timer); ctrl?.abort(); box.remove(); },
  };
}
