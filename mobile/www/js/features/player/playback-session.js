// Сессии загрузки: каждая попытка открыть серию (или сменить озвучку/источник) — новая сессия.
// Новая сессия отменяет запросы прошлой (AbortController), а поздние ответы прошлой проверяют active() и ничего
// не меняют: если серия 1 догрузилась после того, как выбрали серию 2, плеер останется на серии 2.

/** @typedef {{id: number, signal: AbortSignal, active: () => boolean}} PlaybackSession */

export function createSessions() {
  let current = null, seq = 0;
  return {
    /** @returns {PlaybackSession} */
    begin() {
      current?.controller.abort();
      const controller = new AbortController();
      const s = { id: ++seq, signal: controller.signal, controller, active: () => current === s && !controller.signal.aborted };
      current = s;
      return s;
    },
    /** Закрыли плеер — всё, что ещё грузится, больше не нужно. */
    cancel() { current?.controller.abort(); current = null; },
    get current() { return current; },
  };
}
