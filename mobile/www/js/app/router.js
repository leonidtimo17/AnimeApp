// Навигация между экранами и жизненный цикл страницы.
//
// Каждый показ страницы получает свою «сессию»: signal (передаётся в запросы) и onCleanup (снять таймеры и
// обработчики). При уходе со страницы сессия закрывается — запросы, нужные только ей, отменяются,
// а поздние ответы не рисуются в чужой экран.

/**
 * @typedef {{name: string, arg?: any}} Route
 * @typedef {{signal: AbortSignal, active: () => boolean, onCleanup: (fn: () => void) => void,
 *   show: (name: string, arg?: any) => void, replace: (arg: any) => void, back: () => boolean, route: Route}} PageNav
 * @typedef {(view: HTMLElement, arg: any, nav: PageNav) => (void|Promise<void>)} Page
 */

/** @param {{view: HTMLElement, pages: Record<string, Page>, fallback: string, onChange?: (r: Route) => void}} o */
export function createRouter({ view, pages, fallback, onChange }) {
  const history = [];
  let current = null;
  let session = null;

  function open(route) {
    session?.close();
    const controller = new AbortController();
    const cleanups = [];
    const s = {
      close() { controller.abort(); cleanups.splice(0).forEach((fn) => { try { fn(); } catch (e) { console.error(e); } }); },
    };
    session = s;
    current = route;
    onChange?.(route);
    view.scrollTop = 0;
    /** @type {PageNav} */
    const nav = {
      signal: controller.signal,
      active: () => session === s && !controller.signal.aborted,
      onCleanup: (fn) => cleanups.push(fn),
      show: (name, arg) => show(name, arg),
      replace: (arg) => open({ name: route.name, arg }),
      back: () => back(),
      route,
    };
    const page = pages[route.name] || pages[fallback];
    Promise.resolve(page(view, route.arg, nav)).catch((e) => {
      if (e?.name !== "AbortError") console.error("[AnimeApp] страница", route.name, e);
    });
  }

  function show(name, arg, push = true) {
    if (push && current) history.push(current);
    open({ name, arg });
  }

  /** Назад по истории; false — идти некуда. */
  function back() {
    const prev = history.pop();
    if (!prev) return false;
    open(prev);
    return true;
  }

  return {
    show,
    back,
    /** Нажали вкладку: история начинается заново («назад» вернёт на экран, с которого перешли). */
    reset(name) { history.length = 0; show(name); },
    /** Перерисовать текущую страницу (например, после закрытия плеера). */
    refresh() { if (current) open(current); },
    get current() { return current; },
  };
}
