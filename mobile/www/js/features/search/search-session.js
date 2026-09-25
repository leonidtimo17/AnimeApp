// Поиск по названию сразу в двух каталогах, постранично: сначала страницы AniLibria,
// потом — полный каталог Shikimori (там есть все аниме; дубли уже найденного отсеиваются).
import { norm } from "../../domain/titles.js";

/**
 * @param {string} text
 * @param {{catalog: (f:object, signal?:AbortSignal) => Promise<any>, shikiSearch: (q:string, page:number, signal?:AbortSignal) => Promise<any[]>,
 *   fromRelease: (r:object) => object, fromShiki: (x:object) => object}} deps
 */
export function createSearchSession(text, deps) {
  let alPage = 0, alTotal = 1, shPage = 0, shDone = false, found = 0, extras = 0;
  const seenSid = new Set(), seenNames = new Set();

  return {
    get found() { return found; },
    get extras() { return extras; },
    get exhausted() { return alPage >= alTotal && shDone; },

    /** Следующая порция карточек (пустая, если дальше ничего нет). */
    async next(signal) {
      if (alPage < alTotal) {
        const d = await deps.catalog({ search: text, page: alPage + 1, limit: 30 }, signal);
        alPage = d?.meta?.pagination?.current_page || alPage + 1;
        alTotal = d?.meta?.pagination?.total_pages || alPage;
        found = d?.meta?.pagination?.total ?? found;
        const items = [];
        for (const r of d?.data || []) {
          if (r.shikimori?.id) seenSid.add(r.shikimori.id);
          for (const n of [norm(r.name?.main), norm(r.name?.english)]) if (n) seenNames.add(n);
          items.push(deps.fromRelease(r));
        }
        return items;
      }
      if (shDone) return [];
      const list = await deps.shikiSearch(text, shPage + 1, signal);
      shPage++;
      shDone = !list.hasMore;
      // Пустое название не считается совпадением (раньше из-за этого терялись тайтлы без русского названия)
      const fresh = list.filter((x) => !seenSid.has(x.id) && ![norm(x.russian), norm(x.name)].some((n) => n && seenNames.has(n)));
      fresh.forEach((x) => seenSid.add(x.id));
      extras += fresh.length;
      return fresh.map(deps.fromShiki);
    },
  };
}
