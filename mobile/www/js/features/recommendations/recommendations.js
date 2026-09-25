// «Для вас»: кандидаты из каталога по любимым жанрам и необязательный ИИ-разбор (Pollinations, бесплатно).
import * as api from "../../core/api/anilibria.js";
import { request } from "../../core/api/http.js";
import * as store from "../../core/state/store.js";
import { aiPrompt, candidateQueries, parseAi } from "../../domain/taste.js";

/** Кандидаты (параллельно по всем запросам), без того, что уже есть в списках и истории. */
export async function candidates(p, signal) {
  const known = new Set([...store.libraryIds(), ...Object.keys(store.progressAll()).map(Number)]);
  const gl = await api.genres().catch(() => []);
  const byName = Object.fromEntries(gl.map((x) => [x.name, x.id]));
  const pool = new Map();
  const results = await Promise.all(candidateQueries(p, byName).map((q) => api.catalog(q, signal).catch(() => ({ data: [] }))));
  for (const r of results) for (const rel of r.data || []) if (!known.has(rel.id)) pool.set(rel.id, rel);
  return [...pool.values()];
}

const SYSTEM = { ru: "Отвечай только валидным JSON на русском языке, без рассуждений и markdown.",
  en: "Answer only with valid JSON in English, without reasoning or markdown." };

/**
 * {analysis, picks: [[rel, reason]]}; у бесплатной модели бывают неудачные ответы — до трёх попыток.
 * Ошибка — Error с кодом в message: "format" | "unclear" | "unavailable".
 */
export async function ai(p, scored, lang = "ru") {
  const pool = scored.slice(0, 45).map((x) => x.rel);
  const aiLang = lang === "en" ? "en" : "ru";
  const prompt = aiPrompt(p, pool, aiLang);
  let lastErr = "unavailable";
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const text = await request("https://text.pollinations.ai/", { raw: true, timeout: 90000,
        json: { model: "openai", jsonMode: true, private: true, seed: attempt * 17,
          messages: [{ role: "system", content: SYSTEM[aiLang] }, { role: "user", content: prompt }] } });
      const res = parseAi(text, pool, aiLang);
      if (typeof res === "string") { lastErr = res; continue; }
      return res;
    } catch (e) { console.warn("[AnimeApp] ИИ", e); lastErr = "unavailable"; }
  }
  throw new Error(lastErr);
}
