// Форматирование чисел и времени (не зависит от языка). Даты с названиями месяцев — в i18n/index.js.

/** Номер серии: 12 → «12», 12.5 → «12.5». */
export const fmtOrd = (v) => (Number.isInteger(+v) ? String(+v) : String(v));

/** 75 → «1:15», 3725 → «1:02:05». */
export function fmtTime(s) {
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}

/** День недели 1..7 (пн = 1), как у AniLibria. */
export const isoWeekday = (d = new Date()) => ((d.getDay() + 6) % 7) + 1;
