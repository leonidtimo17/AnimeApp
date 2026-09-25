// Окружение браузера, которого нет в Node: localStorage в памяти.
class MemoryStorage {
  constructor() { this.m = new Map(); }
  get length() { return this.m.size; }
  key(i) { return [...this.m.keys()][i] ?? null; }
  getItem(k) { return this.m.has(k) ? this.m.get(k) : null; }
  setItem(k, v) { this.m.set(k, String(v)); }
  removeItem(k) { this.m.delete(k); }
  clear() { this.m.clear(); }
}
globalThis.localStorage = new MemoryStorage();
// Язык тестов — русский (в Node 22 navigator.language = en-US, и автоопределение выбрало бы английский)
localStorage.setItem("animeapp:v1", JSON.stringify({ settings: { language: "ru" } }));
