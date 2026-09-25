// Состояние сети приложения: NetworkState {isOnline, bandwidthMbps, checkedAt, measuring}.
//
// Скорость интернета меряется ОДИН раз — при запуске приложения — и хранится здесь.
// Больше приложение само её не меряет: ни по таймеру, ни перед серией, ни во время просмотра, ни при смене сети.
// Повторный замер — только по кнопке «Проверить скорость».
// «Есть ли интернет» узнаём без замеров: из событий online/offline и по результатам настоящих запросов.
import { createEmitter } from "../events.js";

const SETTING = "networkBandwidth";

/**
 * @param {{measure: (url:string)=>Promise<number|null>, settings?: {get(k,d?):any, set(k,v):void}, events?: EventTarget}} deps
 */
export function createNetworkService({ measure, settings = null, events = globalThis }) {
  const changed = createEmitter();
  const connection = createEmitter();
  const saved = settings?.get(SETTING, null);
  let state = { isOnline: globalThis.navigator?.onLine ?? true, bandwidthMbps: saved?.mbps ?? null,
    checkedAt: saved?.checkedAt ?? null, measuring: false };
  let started = false;
  let measurements = 0;

  const set = (patch) => {
    const next = { ...state, ...patch };
    if (Object.keys(next).every((k) => next[k] === state[k])) return;
    state = next;
    changed.emit(state);
  };

  async function run(getUrl) {
    if (state.measuring) return state;
    set({ measuring: true });
    let mbps = null;
    try {
      const url = await getUrl();
      if (url) mbps = await measure(url);
    } catch (e) {
      console.warn("[AnimeApp] не нашли видео для замера скорости", e);
    }
    measurements++;
    if (mbps) {
      const checkedAt = Date.now();
      set({ bandwidthMbps: mbps, checkedAt, measuring: false, isOnline: true });
      settings?.set(SETTING, { mbps: Math.round(mbps * 100) / 100, checkedAt });
    } else {
      set({ measuring: false });
    }
    return state;
  }

  const onOnline = () => { set({ isOnline: true }); connection.emit("online"); };
  const onOffline = () => { set({ isOnline: false }); connection.emit("offline"); };
  const onChange = () => connection.emit("change");

  return {
    get state() { return state; },
    get measurements() { return measurements; },
    subscribe: changed.subscribe,
    /** Смена сети по событию ОС/браузера (без замеров). fn(kind): "online" | "offline" | "change". */
    onConnectionChange: connection.subscribe,

    /** Запуск приложения: подписка на события и один замер. getUrl() → видео для замера. Второй вызов — ничего. */
    start(getUrl) {
      if (started) return false;
      started = true;
      events?.addEventListener?.("online", onOnline);
      events?.addEventListener?.("offline", onOffline);
      globalThis.navigator?.connection?.addEventListener?.("change", onChange);
      run(getUrl);
      return true;
    },
    /** Проверка скорости по просьбе пользователя. */
    measureNow: (getUrl) => run(getUrl),
    /** Итог настоящего запроса приложения. */
    reportRequest(ok) { if (ok !== state.isOnline) set({ isOnline: ok }); },
    stop() {
      events?.removeEventListener?.("online", onOnline);
      events?.removeEventListener?.("offline", onOffline);
      globalThis.navigator?.connection?.removeEventListener?.("change", onChange);
    },
  };
}
