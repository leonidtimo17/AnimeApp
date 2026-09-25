// Связь с Shikimori (по желанию пользователя):
// - вход через OAuth: браузер → пользователь разрешает доступ → копирует код → вставляет в приложение;
// - прогресс и списки отправляются в список пользователя на Shikimori (там строится его статистика);
// - обсуждения серий — это комментарии Shikimori: читать может каждый, писать — после входа.
// Ключи OAuth-приложения лежат в js/shiki_config.js (не хранится в git, см. shiki_config.example.js).
import { request } from "../core/api/http.js";
import { MemoryCache } from "../core/cache/memory.js";
import { AuthenticationError } from "../core/errors.js";
import * as store from "../core/state/store.js";
import { SHIKI_OFFSET, shikiAnime } from "./sources.js";
import { t } from "../i18n/index.js";

const SHIKI = "https://shikimori.io";
const SCOPE = "user_rates comments";
// Наши статусы → статусы Shikimori и обратно
const TO_SHIKI = { planned: "planned", watching: "watching", completed: "completed", postponed: "on_hold", dropped: "dropped" };
const FROM_SHIKI = { planned: "planned", watching: "watching", rewatching: "watching", completed: "completed", on_hold: "postponed", dropped: "dropped" };

let cfgPromise = null;
/** {clientId, clientSecret, appName} или null, если приложение не зарегистрировано на Shikimori. */
export function config() {
  cfgPromise ||= import("../shiki_config.js")
    // redirect должен в точности совпадать с Redirect URI приложения на Shikimori
    .then((m) => (m.default?.clientId ? { redirect: "urn:ietf:wg:oauth:2.0:oob", ...m.default } : null))
    .catch(() => null);
  return cfgPromise;
}

const auth = () => store.setting("shikiAuth", null);          // {access, refresh, expires, user: {id, nickname, avatar}}
export const user = () => auth()?.user || null;
export const loggedIn = () => !!auth()?.access;
export const syncOn = () => loggedIn() && store.setting("shikiSync", true);

export async function authorizeUrl() {
  const c = await config();
  if (!c) return null;
  return `${SHIKI}/oauth/authorize?client_id=${encodeURIComponent(c.clientId)}&redirect_uri=${encodeURIComponent(c.redirect)}`
    + `&response_type=code&scope=${encodeURIComponent(SCOPE)}`;
}

async function tokenRequest(form) {
  const c = await config();
  const d = await request(`${SHIKI}/oauth/token`, {
    form: { client_id: c.clientId, client_secret: c.clientSecret, redirect_uri: c.redirect, ...form },
    headers: { "User-Agent": c.appName || "AnimeApp" },
  });
  if (!d?.access_token) throw new AuthenticationError("Shikimori не выдал доступ");
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
  if (!a?.access) throw new AuthenticationError("Вы не вошли в Shikimori");
  if (a.expires - 60_000 < Date.now()) {
    try {
      a = { ...a, ...(await tokenRequest({ grant_type: "refresh_token", refresh_token: a.refresh })) };
      store.setSetting("shikiAuth", a);
    } catch (e) {
      if (e.isClientError) logout();  // доступ отозван — выходим
      throw e;
    }
  }
  return request(`${SHIKI}${path}`, {
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

/** Моя запись об этом тайтле на Shikimori: {episodes, status, score} или null. */
export async function rate(sid) {
  const me = user();
  if (!sid || !me) return null;
  const [r] = await call("/api/v2/user_rates", { params: { user_id: me.id, target_id: sid, target_type: "Anime" } });
  return r || null;
}

/** Статистика профиля: сколько тайтлов в каждом статусе. */
export async function stats() {
  const me = user();
  if (!me) return null;
  const u = await request(`${SHIKI}/api/users/${me.id}`, { ttl: 300 });
  const list = u?.stats?.statuses?.anime || [];
  return Object.fromEntries(list.map((s) => [s.name, s.size]));
}

/** Серии, отмеченные на Shikimori, но не отмеченные здесь: докатываем прогресс. onMark(key, ordinal). */
export async function pullProgress(id, eps) {
  if (!syncOn()) return 0;
  const sid = sidOf(id);
  const r = await rate(sid).catch(() => null);
  const seen = r?.episodes || 0;
  if (!seen) return 0;
  const prog = store.progress(id);
  let n = 0;
  for (const e of eps) {
    if (Number.isInteger(+e.ordinal) && +e.ordinal <= seen && !prog[e.key]?.watched) {
      store.setWatchedQuiet(id, e.key, e.ordinal, true);
      n++;
    }
  }
  return n;
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

/** Автоотправка на Shikimori при изменениях списка и прогресса. Возвращает функцию отключения. */
export const startSync = () => store.onChange((kind, id) => { if (syncOn()) push(id); });

// ------------------------------------------------------------------ обсуждения (комментарии Shikimori)
const topicCache = new MemoryCache({ maxSize: 200, ttl: 3600 });
/** Тема обсуждения: {id, episode: true} — отдельная тема серии, {id, episode: false} — общая тема тайтла. */
export async function topic(sid, ordinal) {
  const key = `${sid}|${ordinal}`;
  if (topicCache.has(key)) return topicCache.get(key) || null;
  let res = null;
  if (Number.isInteger(+ordinal)) {
    const t = await request(`${SHIKI}/api/animes/${sid}/topics`, { params: { kind: "episode", episode: +ordinal, limit: 1 }, ttl: 3600 })
      .catch(() => []);
    if (t?.[0]?.id && +t[0].episode === +ordinal) res = { id: t[0].id, episode: true };
  }
  if (!res) res = await animeTopic(sid);
  topicCache.set(key, res ?? false);
  return res;
}
export async function animeTopic(sid) {
  const a = await shikiAnime(sid);
  return a?.topic_id ? { id: a.topic_id, episode: false } : null;
}

/** Комментарии темы, новые сверху. */
export const comments = (topicId, page = 1, signal) => request(`${SHIKI}/api/comments`, {
  params: { commentable_id: topicId, commentable_type: "Topic", page, limit: 30, desc: 1 }, signal,
});

export async function postComment(topicId, body) {
  return call("/api/comments", { json: { comment: { body, commentable_id: topicId, commentable_type: "Topic" } } });
}

/** Безопасный показ BBCode комментария: только текст и простое оформление, без чужого HTML. */
export function renderBody(body, esc) {
  let s = esc(body || "");
  s = s.replace(/\[(b|i|u|s)\]([\s\S]*?)\[\/\1\]/gi, "<$1>$2</$1>");
  s = s.replace(/\[spoiler(?:=[^\]]*)?\]([\s\S]*?)\[\/spoiler\]/gi, `<span class="spoiler" title="${t("comments.spoiler_hint")}">$1</span>`);
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
