// Картинка, которая грузится, только когда попадает на экран (или вот-вот попадёт).
// Пока грузится — видна подложка элемента; не загрузилась — картинка убирается и остаётся подложка.
// Удалённый из документа <img> браузер перестаёт качать сам, поэтому уход со страницы отменяет загрузки.
import { esc } from "../utils/dom.js";

/** eager — первая картинка экрана (постер тайтла): грузится сразу и с высоким приоритетом. */
export const lazyImg = (url, eager = false) => (url
  ? `<img class="lz" src="${esc(url)}" alt="" decoding="async" ${eager ? 'fetchpriority="high"' : 'loading="lazy"'} onload="this.classList.add('ok')" onerror="this.remove()">`
  : "");
