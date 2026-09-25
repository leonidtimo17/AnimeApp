// Состояние плеера: одна понятная модель для встроенного плеера и Kodik.
//
//   idle → loading → ready → playing ⇄ paused
//                              ↕
//                          buffering
//   любое → ended | error;  load — начать заново (новая серия, повтор)
//
// Интерфейс (PlayerOverlay, кнопка play) рисует то, что здесь, а не свои флаги.
import { createEmitter } from "../../core/events.js";

export const Status = Object.freeze({
  IDLE: "idle", LOADING: "loading", READY: "ready", PLAYING: "playing", PAUSED: "paused",
  BUFFERING: "buffering", ENDED: "ended", ERROR: "error",
});

/** Виды ошибок, которые понятны пользователю (текст — player.errors.<kind>). */
export const ErrorKind = Object.freeze({ NETWORK: "network", OFFLINE: "offline", SOURCE: "source", NO_SOURCE: "no_source", PLAYBACK: "playback" });

/** Переход по событию плеера. Неподходящие события состояние не меняют. */
export function nextStatus(status, event) {
  const S = Status;
  switch (event) {
    case "load": return S.LOADING;
    case "reset": return S.IDLE;
    case "error": return S.ERROR;
    case "ended": return status === S.ERROR ? status : S.ENDED;
    case "ready": return status === S.LOADING ? S.READY : status;
    case "play": case "playing": return status === S.ERROR ? status : S.PLAYING;
    case "pause": return [S.ENDED, S.ERROR, S.LOADING].includes(status) ? status : S.PAUSED;
    case "waiting": return [S.PLAYING, S.READY, S.BUFFERING].includes(status) ? S.BUFFERING : status;
    default: return status;
  }
}

export function createPlayerState() {
  const changes = createEmitter();
  let state = { status: Status.IDLE, error: null };
  return {
    get: () => state,
    get status() { return state.status; },
    /** error: {kind, detail} — detail только для журнала разработчика, пользователю показывается текст по kind. */
    dispatch(event, error = null) {
      const status = nextStatus(state.status, event);
      const next = { status, error: status === Status.ERROR ? error || state.error || { kind: ErrorKind.PLAYBACK } : null };
      if (next.status === state.status && next.error === state.error) return;
      if (next.error?.detail) console.warn("[AnimeApp] плеер:", next.error.kind, next.error.detail);
      state = next;
      changes.emit(state);
    },
    subscribe: changes.subscribe,
  };
}
