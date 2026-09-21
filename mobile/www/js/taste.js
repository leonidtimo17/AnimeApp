// Анализ вкуса и рекомендации (тот же алгоритм, что в ПК-версии) + необязательный ИИ-разбор.
import * as api from "./api.js";
import * as store from "./store.js";
import { norm, title } from "./sources.js";

const W = { completed: 2, watching: 1.5, planned: 0.6, postponed: 0.3, dropped: -2 };

export function profile() {
  const s = store.raw();
  const weights = {};
  const counts = {};
  for (const [id, e] of Object.entries(s.library)) {
    let w = W[e.status] || 0;
    if (e.status) counts[e.status] = (counts[e.status] || 0) + 1;
    if (e.favorite) w += 3;
    if (e.score) w += (e.score - 5) / 2.5;
    weights[id] = (weights[id] || 0) + w;
  }
  for (const [id, eps] of Object.entries(s.progress)) {
    const watched = Object.values(eps).filter((v) => v.watched).length;
    weights[id] = (weights[id] || 0) + Math.min(watched, 12) / 8;
  }
  const g = {}, t = {};
  let ySum = 0, yW = 0;
  const titles = [];
  for (const [id, w] of Object.entries(weights)) {
    const a = s.anime[id];
    if (!a) continue;
    titles.push([a, w]);
    const gs = a.genres || [];
    for (const x of gs) g[x] = (g[x] || 0) + w / Math.sqrt(gs.length);
    if (a.type) t[a.type] = (t[a.type] || 0) + w;
    if (a.year && w > 0) { ySum += a.year * w; yW += w; }
  }
  const pos = Object.entries(g).filter(([, v]) => v > 0);
  const top = Math.max(1, ...pos.map(([, v]) => v));
  const genres = Object.fromEntries(pos.sort((a, b) => b[1] - a[1]).map(([k, v]) => [k, v / top]));
  const tpos = Object.entries(t).filter(([, v]) => v > 0);
  const tsum = tpos.reduce((a, [, v]) => a + v, 0) || 1;
  const types = Object.fromEntries(tpos.sort((a, b) => b[1] - a[1]).map(([k, v]) => [k, v / tsum]));
  const yearMean = yW ? ySum / yW : null;
  const liked = titles.filter(([, w]) => w >= 1.5).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([a]) => a);
  const disliked = new Set(Object.entries(g).filter(([, v]) => v < -1).map(([k]) => k));
  return { genres, types, yearMean, liked, disliked, counts, empty: !titles.some(([, w]) => w > 0), titles };
}

export async function candidates(p) {
  const known = new Set([...store.libraryIds(), ...Object.keys(store.raw().progress).map(Number)]);
  const gl = await api.genres().catch(() => []);
  const byName = Object.fromEntries(gl.map((x) => [x.name, x.id]));
  const top = Object.keys(p.genres).filter((x) => byName[x]).slice(0, 4);
  const queries = top.map((x) => ({ genres: [byName[x]], sorting: "RATING_DESC", limit: 40 }));
  if (top.length >= 2) queries.push({ genres: [byName[top[0]], byName[top[1]]], sorting: "RATING_DESC", limit: 30 });
  queries.push({ sorting: "RATING_DESC", limit: 40 }, { sorting: "FRESH_AT_DESC", limit: 30 });
  const pool = new Map();
  const results = await Promise.all(queries.map((q) => api.catalog(q).catch(() => ({ data: [] }))));
  for (const r of results) for (const rel of r.data || []) if (!known.has(rel.id)) pool.set(rel.id, rel);
  return [...pool.values()];
}

export function score(p, rels) {
  const likedSets = p.liked.map((a) => [a, new Set(a.genres)]);
  const out = [];
  for (const rel of rels) {
    const gs = (rel.genres || []).map((x) => x.name);
    if (!gs.length) continue;
    const bad = gs.filter((x) => p.disliked.has(x)).length;
    if (bad && bad >= gs.length / 2) continue;
    let gScore = gs.reduce((a, x) => a + (p.genres[x] || 0), 0) / Math.sqrt(gs.length);
    gScore = Math.min(1, gScore / 1.6);
    const rating = (rel.shikimori?.rating || rel.mal?.rating || 0) / 10;
    const tScore = p.types[rel.type?.description] || 0;
    const yScore = p.yearMean && rel.year ? Math.exp(-Math.abs(rel.year - p.yearMean) / 16) : 0.5;
    const total = 0.6 * gScore + 0.25 * rating + 0.1 * tScore + 0.05 * yScore;
    const common = gs.filter((x) => p.genres[x]).slice(0, 3);
    let best = null, bestN = 0;
    for (const [a, set] of likedSets) { const n = gs.filter((x) => set.has(x)).length; if (n > bestN) { best = a; bestN = n; } }
    let reason = common.length ? "жанры: " + common.join(", ") : "популярное";
    if (best && bestN >= 2) reason += ` · похоже на «${best.title}»`;
    out.push({ score: total, rel, reason });
  }
  return out.sort((a, b) => b.score - a.score);
}

export function describe(p) {
  if (p.empty) return "";
  const g = Object.keys(p.genres);
  const parts = [];
  if (g.length >= 2) parts.push(`Вам больше всего заходят ${g[0].toLowerCase()} и ${g[1].toLowerCase()}${g[2] ? `, часто — ${g[2].toLowerCase()}` : ""}.`);
  if (p.yearMean) parts.push(`В среднем смотрите аниме около ${Math.round(p.yearMean)} года.`);
  const [t, v] = Object.entries(p.types)[0] || [];
  if (t) parts.push(`Формат: чаще ${t.toLowerCase()} (${Math.round(v * 100)}%).`);
  return parts.join(" ");
}

// ------------------------------------------------------------------ ИИ (бесплатно, без ключа)
function extractJson(text) {
  text = String(text || "").trim();
  const cands = [text, ...(text.match(/\{[\s\S]*\}/g) || [])];
  for (const c of cands) {
    try {
      const d = JSON.parse(c);
      if (d?.choices) return extractJson(d.choices[0]?.message?.content);
      if (d && typeof d === "object") return d;
    } catch { /* пробуем дальше */ }
  }
  return null;
}

export async function ai(p, scored) {
  const pool = scored.slice(0, 45).map((x) => x.rel);
  const liked = p.liked.slice(0, 15).map((a) => `${a.title} (${a.year || "?"}; ${(a.genres || []).slice(0, 4).join(", ")})`);
  const cands = pool.map((r, i) => `${i + 1}. ${title(r)} (${r.year || "?"}; ${(r.genres || []).map((x) => x.name).slice(0, 4).join(", ")})`);
  const prompt = "Ты эксперт по аниме. Сделай короткий разбор вкуса пользователя (4–6 предложений, по-русски, дружелюбно) "
    + "и выбери из СПИСКА КАНДИДАТОВ 8 аниме, которые ему понравятся, с причиной до 12 слов.\n\n"
    + `Любимые жанры: ${Object.entries(p.genres).slice(0, 8).map(([k, v]) => `${k} (${Math.round(v * 100)}%)`).join(", ")}\n`
    + `Понравилось: ${liked.join("; ") || "мало данных"}\n\nСПИСОК КАНДИДАТОВ:\n${cands.join("\n")}\n\n`
    + 'Ответь ТОЛЬКО JSON: {"analysis": "...", "picks": [{"n": номер, "reason": "..."}]}';
  const system = "Отвечай только валидным JSON на русском языке, без рассуждений и markdown.";
  let lastErr = "ИИ недоступен";
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const text = await api.request("https://text.pollinations.ai/", { raw: true, timeout: 90000,
        json: { model: "openai", jsonMode: true, private: true, seed: attempt * 17,
          messages: [{ role: "system", content: system }, { role: "user", content: prompt }] } });
      const d = extractJson(text);
      if (!d) { lastErr = "ИИ ответил не по формату"; continue; }
      const analysis = String(d.analysis || d["разбор"] || "");
      const picks = [];
      for (const x of d.picks || []) {
        let n = parseInt(x.n ?? x.id, 10) - 1;
        if (!(n >= 0 && n < pool.length)) n = pool.findIndex((r) => norm(title(r)) === norm(x.title));
        if (n >= 0 && n < pool.length && !picks.some(([r]) => r === pool[n])) picks.push([pool[n], x.reason || ""]);
      }
      const cyr = (analysis.match(/[а-яё]/gi) || []).length;
      if (!picks.length || cyr < analysis.length * 0.3) { lastErr = "ИИ ответил непонятно"; continue; }
      return { analysis, picks };
    } catch (e) { lastErr = `ИИ недоступен: ${e.message}`; }
  }
  throw new Error(lastErr);
}
