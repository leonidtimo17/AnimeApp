// Серия с кадром: плитка на странице тайтла и строка в списке серий плеера.
// Кадр из серии, иначе затемнённый постер с крупным номером; галочка «просмотрено», полоска прогресса.
import { esc } from "../utils/dom.js";
import { fa } from "./Icons.js";
import { lazyImg } from "./LazyImage.js";
import { t } from "../i18n/index.js";

/** o: {preview, poster, key, name, watched, progress (0..1), current, missing, note} */
function thumb(o, withNumber) {
  const img = o.preview || o.poster;
  return `<div class="thumb${o.preview ? "" : " fallback"}">${lazyImg(img)}
      ${o.preview ? (withNumber ? `<span class="num">${esc(o.key)}</span>` : "") : `<span class="big">${esc(o.key)}</span>`}
      ${withNumber && o.watched ? `<span class="ok">${fa("circleCheck")}</span>` : ""}
      ${withNumber && o.current && !o.watched ? `<span class="now">${fa("play")}</span>` : ""}
      <div class="tbar"><i style="width:${Math.round((o.watched ? 1 : o.progress || 0) * 100)}%"></i></div>
    </div>`;
}

/** Плитка серии на странице тайтла. */
export function episodeTile(o) {
  return `<div class="ep${o.missing ? " missing" : ""}${o.current ? " cur" : ""}" data-k="${esc(o.key)}">
    ${thumb(o, true)}
    <div class="ep-t">${esc(t("player.episode_n", { n: o.key }))}</div>
    <div class="nm">${esc(o.note || o.name || "")}</div>
  </div>`;
}

/** Строка серии для списка в плеере (картинка слева). */
export function episodeRow(o, i) {
  return `<div class="it${o.current ? " on" : ""}" data-i="${i}">
    ${thumb(o, false)}
    <div class="txt"><b>${esc(t("player.episode_n", { n: o.key }))}</b><small>${esc(o.name || "")}</small></div>
    ${o.watched ? `<span class="ok">${fa("circleCheck")}</span>` : ""}
  </div>`;
}
