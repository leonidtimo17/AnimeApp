// Простейший издатель событий: subscribe возвращает функцию отписки (слушателей всегда можно снять).

export function createEmitter() {
  const listeners = new Set();
  return {
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    emit(...args) {
      for (const fn of [...listeners]) {
        try { fn(...args); } catch (e) { console.error("[AnimeApp] listener failed", e); }
      }
    },
    get size() { return listeners.size; },
  };
}
