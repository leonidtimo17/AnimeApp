// Блок Shikimori: вход по коду, статистика профиля, отправка и загрузка списка.
import * as store from "../../core/state/store.js";
import { fa } from "../../components/Icons.js";
import { friendlyError } from "../../components/StateView.js";
import { toast } from "../../components/Toast.js";
import { t } from "../../i18n/index.js";
import { esc } from "../../utils/dom.js";
import * as shiki from "../../services/shiki.js";
import * as src from "../../services/sources.js";
import { openExternal } from "../../platform/platform.js";


/** Нарисовать блок в el; refresh() — перерисовать (после входа/выхода). */
export async function renderAccountBox(el, refresh) {
  const cfg = await shiki.config();
  const u = shiki.user();
  if (!cfg) {
    el.innerHTML = `<b>${fa("link")} Shikimori</b><p class="muted">${t("shikimori.not_configured")}</p>`;
    return;
  }
  if (!u) {
    el.innerHTML = `<b>${fa("link")} Shikimori</b>
      <p class="muted">${t("shikimori.intro")}</p>
      <div class="shk-row"><button class="btn" id="shOpen">${t("shikimori.open_login")}</button>
        <input class="input" id="shCode" placeholder="${t("shikimori.code_placeholder")}" aria-label="${t("shikimori.code_placeholder")}" autocomplete="off">
        <button class="btn primary" id="shLogin">${t("shikimori.login")}</button></div>`;
    el.querySelector("#shOpen").onclick = async () => {
      openExternal(await shiki.authorizeUrl());
      toast(t("shikimori.allow_hint"), 4000);
    };
    el.querySelector("#shLogin").onclick = async () => {
      const code = el.querySelector("#shCode").value.trim();
      if (!code) return toast(t("shikimori.code_first"));
      try {
        const me = await shiki.login(code);
        toast(t("shikimori.logged_in", { name: me.nickname }));
        refresh();
      } catch (e) { toast(friendlyError(e, "shikimori.login_failed"), 4000); }
    };
    return;
  }
  const on = store.setting("shikiSync", true);
  const s = store.stats();
  el.innerHTML = `<div class="shk-row"><img class="shk-av" src="${esc(u.avatar || "")}" alt="">
      <div class="grow"><b>${esc(u.nickname)}</b><div class="muted">${t("shikimori.connected")}</div></div>
      <button class="chip${on ? " on" : ""}" id="shSync">${on ? fa("check") + " " : ""}${t("shikimori.sync")}</button></div>
    <div class="shk-stats" id="shStats"><span class="muted">${t("shikimori.stats_loading")}</span></div>
    <p class="muted">${t("shikimori.local_stats", { n: s.episodes, h: s.hours.toFixed(1) })}</p>
    <div class="shk-row"><button class="btn small" id="shPush">${t("shikimori.push_all")}</button>
      <button class="btn small" id="shPull">${t("shikimori.pull_list")}</button>
      <button class="btn small" id="shOut">${t("shikimori.logout")}</button></div>`;
  shiki.stats().then((st) => {
    const box = el.querySelector("#shStats");
    if (!box) return;
    const items = Object.entries(st || {}).filter(([, v]) => v).map(([k, v]) =>
      `<span class="shk-stat"><b>${v}</b> ${esc(t(`shikimori.statuses.${k}`))}</span>`).join("");
    box.innerHTML = items || `<span class="muted">${t("shikimori.stats_empty")}</span>`;
  }).catch((e) => { const box = el.querySelector("#shStats"); if (box) box.innerHTML = `<span class="muted">${esc(friendlyError(e, "shikimori.stats_failed"))}</span>`; });
  el.querySelector("#shSync").onclick = () => { store.setSetting("shikiSync", !on); refresh(); };
  el.querySelector("#shOut").onclick = () => { shiki.logout(); toast(t("shikimori.logged_out")); refresh(); };
  el.querySelector("#shPush").onclick = async (ev) => {
    const b = ev.currentTarget;
    b.disabled = true;
    try {
      const n = await shiki.pushAll((i, total) => (b.textContent = t("shikimori.pushing", { i, n: total })));
      toast(t("shikimori.pushed", { n }));
    } catch (e) { toast(friendlyError(e, "shikimori.push_failed")); }
    b.disabled = false; b.textContent = t("shikimori.push_all");
  };
  el.querySelector("#shPull").onclick = async (ev) => {
    ev.currentTarget.disabled = true;
    const btn = ev.currentTarget;
    try { toast(t("shikimori.pulled_list", { n: await shiki.importList(src.shikiItem) })); refresh(); }
    catch (e) { toast(friendlyError(e, "shikimori.pull_failed")); btn.disabled = false; }
  };
}
