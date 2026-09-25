// Замер скорости по кусочку настоящего видео (как у онлайн-кинотеатров).
// Качаем два куска параллельно до ~3.5 с и считаем скорость только после «разгона» соединения:
// короткая закачка почти целиком уходит на установку соединения и показывала в 5–10 раз меньше настоящей скорости.
// Сам замер ничего не кэширует и не повторяется — когда мерить, решает NetworkService.

export const PROBE_MS = 3500, PROBE_BYTES = 16_000_000, WARMUP_MS = 500, MIN_BYTES = 300_000;

/** Мбит/с по точкам [мс, всего байт]; окно после разгона, если всё скачалось мгновенно — по всей закачке. */
export function speedFromSamples(samples, total) {
  if (total < MIN_BYTES || samples.length < 2) return null;
  const t0 = samples[0][0], end = samples.at(-1);
  const warm = samples.find(([t]) => t - t0 >= WARMUP_MS);
  const [ta, ba] = warm && end[0] - warm[0] >= 300 ? warm : [t0, 0];
  const mbps = ((end[1] - ba) * 8) / ((end[0] - ta) / 1000) / 1e6;
  return Number.isFinite(mbps) && mbps > 0 ? mbps : null;
}

/** Разбор HLS-плейлиста: {variant} мастер-плейлиста или {segments} — первые два сегмента. */
export function playlistTargets(url, text) {
  const lines = text.split("\n").map((s) => s.trim()).filter((s) => s && !s.startsWith("#"));
  if (!lines.length) return { segments: [] };
  if (!text.includes("#EXTINF")) return { variant: new URL(lines[0], url).href };
  return { segments: lines.slice(0, 2).map((s) => new URL(s, url).href) };
}

/** Текст плейлиста; первое соединение с CDN иногда обрывается — повторяем (до двух раз, с паузой). */
async function fetchText(url, retries = 2) {
  for (let i = 0; ; i++) {
    try {
      return await (await fetch(url, { cache: "no-store" })).text();
    } catch (e) {
      if (i >= retries) throw e;
      await new Promise((r) => setTimeout(r, 1000 * (i + 1)));
    }
  }
}

/** Адреса для замера: первые сегменты HLS или два куска mp4. [[url, range|null], ...] */
async function probeTargets(url) {
  let media = url;
  for (let depth = 0; depth < 2 && media.split("?")[0].endsWith(".m3u8"); depth++) {
    const r = playlistTargets(media, await fetchText(media));
    if (r.variant) { media = r.variant; continue; }
    return r.segments.map((s) => [s, null]);
  }
  return [[media, "bytes=0-7999999"], [media, "bytes=8000000-15999999"]];
}

/** Мбит/с или null. */
export async function measure(url) {
  try {
    const targets = await probeTargets(url);
    if (!targets.length) return null;
    const ctrls = targets.map(() => new AbortController());
    const samples = [];
    let total = 0, t0 = 0;
    const stopAll = () => ctrls.forEach((c) => c.abort());
    const timer = setTimeout(stopAll, PROBE_MS);
    await Promise.all(targets.map(async ([u, range], i) => {
      try {
        const res = await fetch(u, { headers: range ? { Range: range } : {}, signal: ctrls[i].signal, cache: "no-store" });
        const reader = res.body.getReader();
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          const now = performance.now();
          if (!t0) t0 = now;
          total += value.length;
          samples.push([now, total]);
          if (total >= PROBE_BYTES) { stopAll(); break; }
        }
      } catch { /* закачку прервали по времени или объёму — это нормальное окончание замера */ }
    }));
    clearTimeout(timer);
    return speedFromSamples(samples, total);
  } catch (e) {
    console.warn("[AnimeApp] замер скорости не удался", e);
    return null;
  }
}
