// Плеер Kodik во встроенном окне (iframe) и его публичный API (postMessage).
// Интерфейс работает с нормализованными событиями, а не с сырыми сообщениями Kodik.
//
// Каждая загрузка серии — новый iframe: после смены src старый документ ещё успевает прислать пару
// сообщений (время, длительность), и раньше они записывались в прогресс новой серии. Теперь сообщения
// принимаются только от текущего окна (ev.source), старое окно удаляется вместе со своей памятью.

/**
 * @typedef {{type: "rendered"|"duration"|"time"|"play"|"pause"|"ended"|"seek"|"ad-start"|"ad-end"|"episode", value?: any}} KodikEvent
 */

/** Сырое сообщение Kodik → событие приложения (или null, если оно нам не нужно). */
export function normalizeKodikMessage(d) {
  if (!d || typeof d !== "object") return null;
  switch (d.key) {
    case "kodik_player_duration_update": return { type: "duration", value: +d.value || 0 };
    case "kodik_player_time_update": return { type: "time", value: +d.value || 0 };
    case "kodik_player_play": return { type: "play" };
    case "kodik_player_pause": return { type: "pause" };
    case "kodik_player_video_ended": return { type: "ended" };
    case "kodik_player_seek": return { type: "seek", value: d.value?.time ?? d.value };
    case "kodik_player_advert_started": return { type: "ad-start" };
    case "kodik_player_advert_ended": return { type: "ad-end" };
    case "kodik_player_current_episode": return { type: "episode", value: d.value };
    case "player-rendered": return { type: "rendered" };
    default: break;
  }
  if (d.event === "inited") return { type: "rendered" };
  if (d.event === "adShown" || d.title === "vastStarted") return { type: "ad-start" };
  if (d.title === "currentVastEnded") return { type: "ad-end" };
  return null;
}

/**
 * @param {HTMLElement} container — куда вставлять iframe (первым элементом)
 * @param {(e: KodikEvent) => void} onEvent
 */
export function createKodikFrame(container, onEvent) {
  let frame = null;
  const onMessage = (ev) => {
    if (!frame || ev.source !== frame.contentWindow) return;   // только текущее окно Kodik
    const e = normalizeKodikMessage(ev.data);
    if (e) onEvent(e);
  };
  window.addEventListener("message", onMessage);

  function remove() {
    if (!frame) return;
    frame.src = "about:blank";
    frame.remove();
    frame = null;
  }

  return {
    /** Загрузить серию в новое окно (старое удаляется). */
    load(url) {
      remove();
      frame = document.createElement("iframe");
      frame.className = "kodik";
      frame.allow = "autoplay; fullscreen; picture-in-picture";
      frame.setAttribute("allowfullscreen", "");
      const f = frame;
      f.addEventListener("load", () => { if (f === frame && f.src !== "about:blank") onEvent({ type: "loaded" }); });
      f.src = url;
      container.prepend(f);
      return frame;
    },
    /** Команда плееру: play, pause, seek {seconds}, volume {volume}, mute, unmute. */
    send(method, extra = {}) { frame?.contentWindow?.postMessage({ key: "kodik_player_api", value: { method, ...extra } }, "*"); },
    get element() { return frame; },
    unload: remove,
    destroy() { window.removeEventListener("message", onMessage); remove(); },
  };
}
