// Сохранение позиции просмотра без лишних записей.
// Не на каждый timeupdate (4 раза в секунду), а: раз в intervalMs во время просмотра, на паузе, при смене серии,
// при уходе из приложения (свернули, закрыли) и в конце серии. Своих таймеров нет — tick() вызывает плеер.

/**
 * @param {{save: (snap: {ep: object, pos: number, dur: number}, reason: string) => void, intervalMs?: number,
 *   now?: () => number, doc?: Document, win?: Window}} o
 */
export function createProgressTracker({ save, intervalMs = 5000, now = () => Date.now(), doc = globalThis.document, win = globalThis }) {
  let snapshot = null;       // () => {ep, pos, dur} | null
  let last = now();
  let saves = 0;

  function flush(reason) {
    const s = snapshot?.();
    if (!s || !s.dur || s.pos < 5) return false;
    save(s, reason);
    saves++;
    last = now();
    return true;
  }
  const onVisibility = () => { if (doc?.visibilityState === "hidden") flush("hidden"); };
  const onPageHide = () => flush("leave");
  doc?.addEventListener?.("visibilitychange", onVisibility);
  win?.addEventListener?.("pagehide", onPageHide);

  return {
    /** Откуда брать текущую серию и позицию (сек). */
    track(fn) { snapshot = fn; last = now(); },
    /** Позиция изменилась — сохранить, если с прошлого раза прошло intervalMs. */
    tick() { if (now() - last >= intervalMs) flush("interval"); },
    flush,
    get saves() { return saves; },
    destroy() {
      flush("close");
      doc?.removeEventListener?.("visibilitychange", onVisibility);
      win?.removeEventListener?.("pagehide", onPageHide);
      snapshot = null;
    },
  };
}
