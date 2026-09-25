// Выбор качества видео по скорости интернета — только правила, без сети.
// Скорость берётся из единственного замера при запуске приложения (NetworkService); плеер её не меряет.

export const requiredMbps = (q) => { const h = +q; return h >= 2000 ? 20 : h >= 1400 ? 12 : h >= 1000 ? 9 : h >= 700 ? 4 : 0; };
export const qualityName = (h) => (h >= 2000 ? "4K" : h >= 1400 ? "2K" : h >= 1000 ? "Full HD" : h >= 700 ? "HD" : "SD");
export const sortQ = (qs) => [...qs].sort((a, b) => +b - +a);
/** Примерный битрейт для общего плейлиста (hls.js сам уточнит по факту загрузки). */
export const bitrate = (q) => ({ 2160: 15e6, 1440: 9e6, 1080: 5e6, 720: 2.5e6, 480: 1.2e6 }[q] || Math.max(0.6e6, +q * 2500));

/** Лучшее качество из доступных, на которое хватает скорости (скорость неизвестна → до 720p). */
export function recommend(mbps, available) {
  const avail = sortQ(available);
  if (!avail.length) return null;
  if (mbps == null) return avail.find((q) => +q <= 720) || avail.at(-1);
  return avail.find((q) => requiredMbps(q) <= mbps) || avail.at(-1);
}

/** Качество, которое реально включить: нужное; иначе ближайшее ниже; иначе самое низкое. */
export function effectiveQuality(available, preferred, bad = new Set(), cap = null) {
  const avail = sortQ(available).filter((q) => !bad.has(q));
  if (!avail.length) return null;
  let pref = preferred;
  if (cap && pref && +pref > +cap) pref = cap;
  if (avail.includes(pref)) return pref;
  return avail.find((q) => +q < +pref) || avail.at(-1);
}

/**
 * Состояние выбора качества в плеере. mode: "auto" или "1080"/"720"/"480".
 * В «Авто» при частых подгрузках качество понижается (потолок); потолок снимается при смене сети
 * или после ручной проверки скорости — без фоновых замеров.
 */
export class QualityPolicy {
  constructor(mode, bandwidth) {
    this.mode = mode;
    this.bandwidth = bandwidth;          // () => Мбит/с из NetworkService | null
    this.bad = new Set();
    this.cap = null;
    this.stalls = [];
    this.recommended = null;
  }

  choose(available) {
    if (this.mode === "auto") this.recommended = recommend(this.bandwidth(), available);
    return this.effective(available);
  }

  effective(available) {
    const pref = this.mode === "auto" ? this.recommended : this.mode;
    return effectiveQuality(available, pref, this.bad, this.mode === "auto" ? this.cap : null);
  }

  /** Подгрузка видео; вернёт качество ниже, если их было 3 за минуту (только «Авто»). */
  stalled(available, current, now = Date.now()) {
    if (this.mode !== "auto") return null;
    this.stalls = this.stalls.filter((t) => now - t < 60_000).concat(now);
    const lower = sortQ(available).find((x) => +x < +(current || 0) && !this.bad.has(x));
    if (this.stalls.length >= 3 && lower) {
      this.stalls = [];
      this.cap = lower;
      return lower;
    }
    return null;
  }

  /** Сеть сменилась или скорость проверили заново — снять потолок. */
  reset() { this.cap = null; this.stalls = []; }
}
