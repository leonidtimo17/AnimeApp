// Связь с Shikimori (по желанию пользователя):
// - вход через OAuth: браузер → пользователь разрешает доступ → копирует код → вставляет в приложение;
// - прогресс и списки отправляются в список пользователя на Shikimori (там строится его статистика);
// - обсуждения серий — это комментарии Shikimori: читать может каждый, писать — после входа.
// Ключи OAuth-приложения лежат в shiki_config.js (не хранится в git, см. shiki_config.example.js).
import * as api from "./api.js";
import * as store from "./store.js";
import { SHIKI_OFFSET } from "./sources.js";

const SHIKI = "https://shikimori.io";
const REDIRECT = "urn:ietf:wg:oauth:2.0:oob";
const SCOPE = "user_rates comments";
// Наши статусы → статусы Shikimori и обратно
const TO_SHIKI = { planned: "planned", watching: "watching", completed: "completed", postponed: "on_hold", dropped: "dropped" };
const FROM_SHIKI = { planned: "planned", watching: "watching", rewatching: "watching", completed: "completed", on_hold: "postponed", dropped: "dropped" };

let cfgPromise = null;
/** {clientId, clientSecret, appName} или null, если приложение не зарегистрировано на Shikimori. */
export function config() {
  cfgPromise ||= import("./shiki_config.js").then((m) => (m.default?.clientId ? m.default : null)).catch(() => null);
  return cfgPromise;
}

const auth = () => store.setting("shikiAuth", null);          // {access, refresh, expires, user: {id, nickname, avatar}}
export const user = () => auth()?.user || null;
export const loggedIn = () => !!auth()?.access;
export const syncOn = () => loggedIn() && store.setting("shikiSync", true);

export async function authorizeUrl() {
  const c = await config();
  if (!c) return null;
  return `${SHIKI}/oauth/authorize?client_id=${encodeURIComponent(c.clientId)}&redirect_uri=${encodeURIComponent(REDIRECT)}`
    + `&response_type=code&scope=${encodeURIComponent(SCOPE)}`;
}

async function tokenRequest(form) {
  const c = await config();
  const d = await api.request(`${SHIKI}/oauth/token`, {
    form: { client_id: c.clientId, client_secret: c.clientSecret, redirect_uri: REDIRECT, ...form },
    headers: { "User-Agent": c.appName || "AnimeApp" },
  });
  if (!d?.access_token) throw new Error("Shikimori не выдал доступ");
  return { access: d.access_token, refresh: d.refresh_token, expires: Date.now() + (d.expires_in || 86400) * 1000 };
}

/** Вход по коду со страницы Shikimori. */
export async function login(code) {
  const t = await tokenRequest({ grant_type: "authorization_code", code: code.trim() });
  store.setSetting("shikiAuth", t);
  const me = await call("/api/users/whoami");
  store.setSetting("shikiAuth", { ...t, user: { id: me.id, nickname: me.nickname, avatar: me.avatar } });
  return user();
}
export function logout() { store.setSetting("shikiAuth", null); }

/** Запрос к API от имени пользователя; токен обновляется сам. */
async function call(path, opts = {}) {
  const c = await config();
  let a = auth();
  if (!a?.access) throw new Error("Вы не вошли в Shikimori");
  if (a.expires - 60_000 < Date.now()) {
    try {
      a = { ...a, ...(await tokenRequest({ grant_type: "refresh_token", refresh_token: a.refresh })) };
      store.setSetting("shikiAuth", a);
    } catch (e) {
      if (String(e.message).startsWith("HTTP 4")) logout();  // доступ отозван — выходим
      throw e;
    }
  }
  return api.request(`${SHIKI}${path}`, {
    ...opts, headers: { ...(opts.headers || {}), Authorization: `Bearer ${a.access}`, "User-Agent": c.appName || "AnimeApp" },
  });
}

// ------------------------------------------------------------------ списки и прогресс
/** id тайтла на Shikimori для нашего id. */
export function sidOf(id) {
  if (id >= SHIKI_OFFSET) return id - SHIKI_OFFSET;
  return store.anime(id)?.shikimori || null;
}
/** Сколько серий подряд просмотрено (для счётчика на Shikimori): наибольший номер просмотренной целой серии. */
function watchedCount(id) {
  let n = 0;
  for (const p of Object.values(store.progress(id))) if (p.watched && Number.isInteger(+p.ordinal)) n = Math.max(n, +p.ordinal);
  return n;
}

const pending = {};
/** Отправить на Shikimori статус, оценку и число серий тайтла (с задержкой, чтобы не слать на каждое действие). */
export function push(id, now = false) {
  if (!syncOn() || !sidOf(id)) return Promise.resolve(false);
  clearTimeout(pending[id]);
  return new Promise((resolve) => {
    pending[id] = setTimeout(() => pushNow(id).then(resolve, () => resolve(false)), now ? 0 : 2500);
  });
}
async function pushNow(id) {
  const sid = sidOf(id), me = user();
  if (!sid || !me) return false;
  const e = store.entry(id);
  const eps = watchedCount(id);
  const [rate] = await call("/api/v2/user_rates", { params: { user_id: me.id, target_id: sid, target_type: "Anime" } });
  if (!rate && !e.status && !eps && !e.score) return false;
  const body = {
    // Число серий не уменьшаем: на Shikimori могли отметить больше, чем посмотрено здесь
    episodes: Math.max(rate?.episodes || 0, eps),
    status: TO_SHIKI[e.status] || rate?.status || (eps ? "watching" : "planned"),
  };
  if (e.score) body.score = e.score;
  if (rate) await call(`/api/v2/user_rates/${rate.id}`, { method: "PATCH", json: { user_rate: body } });
  else await call("/api/v2/user_rates", { json: { user_rate: { ...body, user_id: me.id, target_id: sid, target_type: "Anime" } } });
  return true;
}

/** Отправить весь список сразу. onStep(done, total). */
export async function pushAll(onStep) {
  const ids = [...new Set([...store.libraryIds(), ...Object.keys(store.progressAll()).map(Number)])].filter(sidOf);
  let ok = 0;
  for (let i = 0; i < ids.length; i++) {
    try { if (await pushNow(ids[i])) ok++; } catch { /* пропускаем */ }
    onStep?.(i + 1, ids.length);
  }
  return ok;
}

/** Загрузить список с Shikimori: статусы и оценки попадают в «Моё». Возвращает число тайтлов. */
export async function importList(shikiItem) {
  const me = user();
  const rates = await call(`/api/users/${me.id}/anime_rates`, { params: { limit: 5000 } });
  const bySid = new Map(Object.values(store.animeAll()).filter((a) => a.shikimori).map((a) => [a.shikimori, a.id]));
  let n = 0;
  for (const r of rates || []) {
    if (!r.anime?.id) continue;
    const item = shikiItem(r.anime);
    const id = bySid.get(r.anime.id) || item.id;
    if (!store.anime(id)) store.remember(item.release, { poster: item.poster, subtitle: item.subtitle });
    store.setEntryQuiet(id, { status: FROM_SHIKI[r.status] || null, score: r.score || null });
    n++;
  }
  return n;
}

// Автоотправка при изменениях
store.onChange((kind, id) => { if (syncOn()) push(id); });

// ------------------------------------------------------------------ обсуждения (комментарии Shikimori)
const topicCache = {};
/** Тема обсуждения: {id, episode: true} — отдельная тема серии, {id, episode: false} — общая тема тайтла. */
export async function topic(sid, ordinal) {
  const key = `${sid}|${ordinal}`;
  if (topicCache[key]) return topicCache[key];
  let res = null;
  if (Number.isInteger(+ordinal)) {
    const t = await api.request(`${SHIKI}/api/animes/${sid}/topics`, { params: { kind: "episode", episode: +ordinal, limit: 1 }, ttl: 3600 })
      .catch(() => []);
    if (t?.[0]?.id && +t[0].episode === +ordinal) res = { id: t[0].id, episode: true };
  }
  if (!res) {
    const a = await api.request(`${SHIKI}/api/animes/${sid}`, { ttl: 3600 });
    if (a?.topic_id) res = { id: a.topic_id, episode: false };
  }
  topicCache[key] = res;
  return res;
}
export async function animeTopic(sid) {
  const a = await api.request(`${SHIKI}/api/animes/${sid}`, { ttl: 3600 });
  return a?.topic_id ? { id: a.topic_id, episode: false } : null;
}

/** Комментарии темы, новые сверху. */
export const comments = (topicId, page = 1) => api.request(`${SHIKI}/api/comments`, {
  params: { commentable_id: topicId, commentable_type: "Topic", page, limit: 30, desc: 1 }, ttl: 0,
});

export async function postComment(topicId, body) {
  return call("/api/comments", { json: { comment: { body, commentable_id: topicId, commentable_type: "Topic" } } });
}

/** Безопасный показ BBCode комментария: только текст и простое оформление, без чужого HTML. */
export function renderBody(body, esc) {
  let s = esc(body || "");
  s = s.replace(/\[(b|i|u|s)\]([\s\S]*?)\[\/\1\]/gi, "<$1>$2</$1>");
  s = s.replace(/\[spoiler(?:=[^\]]*)?\]([\s\S]*?)\[\/spoiler\]/gi, '<span class="spoiler" title="Спойлер — нажмите, чтобы показать">$1</span>');
  s = s.replace(/\[quote(?:=[^\]]*)?\]([\s\S]*?)\[\/quote\]/gi, "<blockquote>$1</blockquote>");
  s = s.replace(/\[comment=[^\]]*\]([\s\S]*?)\[\/comment\]/gi, "@$1");
  s = s.replace(/\[(?:url|character|person|anime|manga|ranobe|user)=[^\]]*\]([\s\S]*?)\[\/(?:url|character|person|anime|manga|ranobe|user)\]/gi, "$1");
  s = s.replace(/\[(?:image|poster|img)[^\]]*\](?:[\s\S]*?\[\/(?:img|poster)\])?/gi, "🖼");
  s = s.replace(/\[replies=[^\]]*\]/gi, "");
  s = s.replace(/\[\/?[a-z_]+(?:=[^\]]*)?\]/gi, "");
  // Время вида 12:34 — нажатие перематывает видео
  s = s.replace(/(^|[^\d:])(\d{1,2}:\d{2}(?::\d{2})?)(?![\d:])/g, (m, pre, t) => {
    const sec = t.split(":").reduce((a, x) => a * 60 + +x, 0);
    return `${pre}<a class="ts" data-t="${sec}">${t}</a>`;
  });
  return s.replace(/\n/g, "<br>");
}
