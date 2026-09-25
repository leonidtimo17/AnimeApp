// Озвучки: порядок, выбор по умолчанию, группы для меню.
// Озвучка: {id: "anilibria"|"animevost"|"kodik:<team>"|"yani:<имя>", name, kind: "voice"|"sub", native: bool}
import { norm } from "./titles.js";

export function sortDubs(dubs) {
  return [...dubs].sort((a, b) => (a.native === b.native ? 0 : a.native ? -1 : 1) || (a.kind === "sub") - (b.kind === "sub")
    || a.name.localeCompare(b.name));
}

/** Сохранённая озвучка тайтла → любимая озвучка пользователя → первая (встроенный плеер). */
export function chooseDub(dubs, savedId, preferredName) {
  if (!dubs.length) return null;
  const s = dubs.find((d) => d.id === savedId);
  if (s) return s;
  const pref = norm(preferredName || "");
  if (pref) {
    const p = dubs.find((d) => norm(d.name).startsWith(pref) || pref.startsWith(norm(d.name)));
    if (p) return p;
  }
  return dubs[0];
}

/** Группы меню озвучек: [ключ перевода заголовка, озвучки]. */
export function menuGroups(dubs) {
  return [
    ["dubs.native", dubs.filter((d) => d.native)],
    ["dubs.kodik_voice", dubs.filter((d) => !d.native && d.kind === "voice")],
    ["dubs.kodik_sub", dubs.filter((d) => !d.native && d.kind === "sub")],
  ].filter(([, items]) => items.length);
}
