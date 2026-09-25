// Названия: сопоставление между каталогами и поисковые запросы.

/** Название тайтла (у всех каталогов есть хотя бы одно; если нет — «—»). */
export const title = (rel) => rel?.name?.main || rel?.name?.english || "—";

export function norm(t) { return (t || "").toLowerCase().replace(/ё/g, "е").replace(/[^0-9a-zа-я]+/g, ""); }

const ROMAN = { ii: "2", iii: "3", iv: "4", v: "5", vi: "6", vii: "7", viii: "8" };
const ORD = { первый: "1", второй: "2", третий: "3", четвертый: "4", пятый: "5", шестой: "6",
  первая: "1", вторая: "2", третья: "3", четвертая: "4", пятая: "5" };

/** «Mushoku Tensei III» = «Mushoku Tensei 3», «(третий сезон)» = «3», «Часть 2» = «Part 2». */
export function titleKey(text) {
  let t = ` ${(text || "").toLowerCase().replace(/ё/g, "е")} `;
  t = t.replace(/[^0-9a-zа-я]+/g, " ");
  // (\b в JS не работает с кириллицей — разбираем по словам)
  const drop = new Set(["сезон", "season", "tv", "тв"]);
  t = t.split(" ").map((w) => (drop.has(w) ? "" : ROMAN[w] || ORD[w] || (w === "часть" || w === "part" ? "p" : w))).join(" ");
  return norm(t);
}

/** Варианты поискового запроса: полное название, часть до «:», первые слова. */
export function searchQueries(rel, fullFirst = true) {
  const out = [];
  for (const t of [rel.name?.english, rel.name?.main]) {
    if (!t) continue;
    const v = fullFirst ? [t] : [];
    const head = t.split(/[:.!?(\[]/)[0].trim();
    v.push(head);
    const words = head.replace(/[^\p{L}\p{N}\s]/gu, " ").split(/\s+/).filter(Boolean);
    if (words.length > 2) v.push(words.slice(0, 2).join(" "));
    for (const q of v) if (q && q.length >= 3 && !out.includes(q)) out.push(q);
  }
  return out;
}

export const matchKeys = (rel) => new Set([rel.name?.english, rel.name?.main, rel.name?.alternative].map(titleKey).filter(Boolean));

/** Одна и та же команда в разных каталогах пишется по-разному: «Дублированный» / «Дублированная», «2x2» / «2×2». */
export function sameDub(a, b) {
  const x = norm(a.replace(/×/g, "x")), y = norm(b.replace(/×/g, "x"));
  return x === y || (Math.min(x.length, y.length) >= 5 && (x.startsWith(y) || y.startsWith(x) || x.slice(0, 8) === y.slice(0, 8)));
}

export function stripBB(t) { return (t || "").replace(/\[(\w+)=[^\]]*\](.*?)\[\/\1\]/g, "$2").replace(/\[\/?[^\]]+\]/g, "").trim(); }
