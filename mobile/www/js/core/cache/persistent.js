// Постоянный кэш ответов серверов в IndexedDB — для офлайна и быстрого запуска.
// Раньше ответы лежали в localStorage рядом со списками пользователя и занимали его квоту (~5 МБ):
// при переполнении терялись сами списки. IndexedDB — отдельное и гораздо большее хранилище, работает асинхронно.

const DB_NAME = "animeapp-cache";
const STORE = "http";
const MAX_ENTRIES = 600;
const LEGACY_PREFIX = "http:";   // старый кэш в localStorage (до 1.8)

let dbPromise = null;
let puts = 0;

function open() {
  if (dbPromise) return dbPromise;
  const idb = globalThis.indexedDB;
  if (!idb) return (dbPromise = Promise.resolve(null));
  dbPromise = new Promise((resolve) => {
    const req = idb.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "k" }).createIndex("t", "t");
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => { console.warn("[AnimeApp] IndexedDB недоступен — кэш только в памяти", req.error); resolve(null); };
  });
  return dbPromise;
}

function tx(db, mode, fn) {
  return new Promise((resolve) => {
    try {
      const t = db.transaction(STORE, mode);
      const result = fn(t.objectStore(STORE));
      t.oncomplete = () => resolve(result?.result ?? null);
      t.onerror = t.onabort = () => resolve(null);
    } catch (e) {
      console.warn("[AnimeApp] кэш", e);
      resolve(null);
    }
  });
}

/** Тело ответа, если оно свежее ttl секунд (ttl = null — любой давности). */
export async function get(key, ttl) {
  const db = await open();
  if (!db) return null;
  const row = await tx(db, "readonly", (s) => s.get(key));
  if (!row || (ttl != null && Date.now() - row.t > ttl * 1000)) return null;
  return row.d;
}

export async function put(key, text) {
  const db = await open();
  if (!db) return;
  await tx(db, "readwrite", (s) => s.put({ k: key, t: Date.now(), d: text }));
  if (++puts % 25 === 0) prune();
}

/** Оставить не больше MAX_ENTRIES самых свежих ответов. */
export async function prune(max = MAX_ENTRIES) {
  const db = await open();
  if (!db) return;
  const count = await tx(db, "readonly", (s) => s.count());
  if (!count || count <= max) return;
  let extra = count - Math.floor(max * 0.8);
  await tx(db, "readwrite", (s) => {
    const cur = s.index("t").openCursor();
    cur.onsuccess = () => {
      const c = cur.result;
      if (c && extra-- > 0) { c.delete(); c.continue(); }
    };
    return cur;
  });
}

export async function clear() {
  const db = await open();
  if (db) await tx(db, "readwrite", (s) => s.clear());
  clearLegacy();
}

/** Однократно убрать старый кэш из localStorage — освобождает место для списков пользователя. */
export function clearLegacy() {
  const ls = globalThis.localStorage;
  if (!ls) return;
  try {
    Object.keys(ls).filter((k) => k.startsWith(LEGACY_PREFIX)).forEach((k) => ls.removeItem(k));
  } catch (e) { console.warn("[AnimeApp] не удалось очистить старый кэш", e); }
}
