// Настройки: язык интерфейса и проверка соединения (единственный ручной способ заново измерить скорость).
import { network } from "../app/network.js";
import { fa } from "../components/Icons.js";
import { formatAgo, i18n, t } from "../i18n/index.js";
import * as api from "../core/api/anilibria.js";
import { esc } from "../utils/dom.js";

function networkHtml(st) {
  const speed = st.bandwidthMbps ? t("network.mbps", { n: Math.round(st.bandwidthMbps) }) : t("network.unknown");
  const when = st.checkedAt ? ` · ${t("network.checked", { when: formatAgo(new Date(st.checkedAt).toISOString()) })}` : "";
  return `<p><b>${t(st.isOnline ? "network.online" : "network.offline")}</b></p>
    <p class="muted">${t("network.speed")}: ${esc(speed)}${esc(when)}</p>
    <button class="btn small" id="check" ${st.measuring ? "disabled" : ""}>${fa("gauge")} ${t(st.measuring ? "network.checking" : "network.check_connection")}</button>
    <p class="muted small">${t("network.check_hint")}</p>`;
}

export default function settings(view, _arg, nav) {
  view.innerHTML = `<button class="btn flat" id="bk">${fa("back")} ${t("common.back")}</button>
    <h1>${t("settings.title")}</h1>
    <section class="panel" aria-labelledby="langT"><h2 class="panel-title" id="langT">${t("settings.language")}</h2>
      <div class="chips" role="radiogroup" aria-labelledby="langT">${i18n.available.map((l) =>
        `<button class="chip${l.code === i18n.locale ? " on" : ""}" role="radio" aria-checked="${l.code === i18n.locale}" data-lang="${l.code}" lang="${l.code}">${esc(l.name)}</button>`).join("")}</div>
      ${i18n.locale === "sah" ? `<p class="muted small">${t("settings.sah_partial")}</p>` : ""}
    </section>
    <section class="panel" aria-labelledby="netT"><h2 class="panel-title" id="netT">${t("settings.connection")}</h2><div id="net"></div></section>`;
  view.querySelector("#bk").onclick = () => nav.back();
  view.querySelector("[role=radiogroup]").onclick = (e) => {
    const b = e.target.closest("[data-lang]");
    if (b) i18n.setLocale(b.dataset.lang);          // интерфейс перерисуется сам (подписка в bootstrap)
  };
  const net = view.querySelector("#net");
  const render = (st) => {
    net.innerHTML = networkHtml(st);
    net.querySelector("#check").onclick = () =>
      network.measureNow(async () => api.sampleStream(await api.latest()));   // только по нажатию
  };
  render(network.state);
  nav.onCleanup(network.subscribe(render));
}
