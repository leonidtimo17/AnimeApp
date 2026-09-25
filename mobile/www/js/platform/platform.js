// Платформа: всё, что зависит от устройства, — здесь, а не в компонентах.
//
// Сейчас: Android (Capacitor + свой плагин PlayerScreen) и обычный браузер. Для iPhone/iPad (Capacitor iOS) и macOS
// достаточно добавить ветки сюда: компоненты вызывают platform.fullscreen(), platform.onBack() и т. д.
// и не знают, на чём запущены.

const cap = () => globalThis.Capacitor;
const plugin = (name) => cap()?.Plugins?.[name];

/** "android" | "ios" | "web" */
export function os() {
  const p = cap()?.getPlatform?.();
  if (p && p !== "web") return p;
  return "web";
}

export const isNative = () => os() !== "web";

/** Основной ввод — пальцем (телефон, планшет). На ПК/Mac с мышью — false. */
export const touchFirst = () => !!globalThis.matchMedia?.("(pointer: coarse)").matches;

/**
 * Полный экран плеера. Android — нативный плагин (прячет системные панели, экран не гаснет);
 * браузер, iPad, Mac — Fullscreen API, если он есть (иначе остаётся режим «только видео» в окне).
 */
export function fullscreen(on, element = globalThis.document?.documentElement) {
  const P = plugin("PlayerScreen");
  if (P?.fullscreen) return P.fullscreen({ on }).catch((e) => console.warn("[AnimeApp] полный экран", e));
  const doc = globalThis.document;
  try {
    if (on && !doc.fullscreenElement) return element?.requestFullscreen?.()?.catch(() => {});
    if (!on && doc.fullscreenElement) return doc.exitFullscreen?.()?.catch(() => {});
  } catch (e) { console.warn("[AnimeApp] полный экран", e); }
  return Promise.resolve();
}

/** Блокировка рекламы в плеере Kodik (есть только в приложении Android — нативный фильтр запросов). */
export const adblock = (on) => plugin("PlayerScreen")?.adblock?.({ on }).catch((e) => console.warn("[AnimeApp] adblock", e));
export const hasAdblock = () => !!plugin("PlayerScreen")?.adblock;

/** Открыть ссылку во внешнем браузере. */
export function openExternal(url) {
  const P = plugin("PlayerScreen");
  if (P?.openUrl) return P.openUrl({ url }).catch(() => globalThis.open(url, "_blank"));
  globalThis.open(url, "_blank");
  return Promise.resolve();
}

/** Системная кнопка «Назад» (Android). fn() → true, если обработано; иначе приложение закрывается. */
export function onBack(fn) {
  const App = plugin("App");
  if (!App?.addListener) return () => {};
  const handle = App.addListener("backButton", () => { if (!fn()) App.exitApp?.(); });
  return () => handle?.remove?.();
}

/** Нативный HTTP (без ограничений CORS) — если приложение запущено на устройстве. */
export const nativeHttp = () => plugin("CapacitorHttp") || null;
