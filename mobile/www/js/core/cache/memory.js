// Кэш в памяти: LRU с ограничением по числу записей и «весу» (например, длине строки) и сроком жизни записи.

export class MemoryCache {
  /** @param {{maxSize?: number, maxWeight?: number, ttl?: number, weigh?: (v:any)=>number, now?: ()=>number}} o */
  constructor({ maxSize = 200, maxWeight = Infinity, ttl = null, weigh = () => 1, now = () => Date.now() } = {}) {
    Object.assign(this, { maxSize, maxWeight, ttl, weigh, now });
    this.map = new Map();   // key → {v, exp, w}; порядок вставки = порядок использования
    this.weight = 0;
  }

  get(key) {
    const e = this.map.get(key);
    if (!e) return undefined;
    if (e.exp != null && this.now() >= e.exp) { this.delete(key); return undefined; }
    this.map.delete(key);
    this.map.set(key, e);
    return e.v;
  }

  has(key) { return this.get(key) !== undefined; }

  /** ttl — секунды (null — пока не вытеснят). */
  set(key, v, ttl = this.ttl) {
    this.delete(key);
    const w = this.weigh(v);
    if (w > this.maxWeight) return;
    this.map.set(key, { v, w, exp: ttl == null ? null : this.now() + ttl * 1000 });
    this.weight += w;
    while (this.map.size > this.maxSize || this.weight > this.maxWeight) {
      const oldest = this.map.keys().next().value;
      this.delete(oldest);
    }
  }

  delete(key) {
    const e = this.map.get(key);
    if (!e) return;
    this.map.delete(key);
    this.weight -= e.w;
  }

  deleteWhere(pred) { for (const k of [...this.map.keys()]) if (pred(k)) this.delete(k); }
  clear() { this.map.clear(); this.weight = 0; }
  get size() { return this.map.size; }
}
