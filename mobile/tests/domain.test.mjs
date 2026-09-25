import "./setup.mjs";
import assert from "node:assert/strict";
import { test } from "node:test";
import { chooseDub, menuGroups, sortDubs } from "../www/js/domain/dubs.js";
import { parseOrdinal, resumeTarget, shownEpisodes, unionEpisodes } from "../www/js/domain/episodes.js";
import { effectiveQuality, QualityPolicy, recommend } from "../www/js/domain/quality.js";
import { aiPrompt, becauseOf, parseAi, profile, score, summary } from "../www/js/domain/taste.js";
import { sameDub, searchQueries, titleKey } from "../www/js/domain/titles.js";
import { upcoming } from "../www/js/domain/upcoming.js";
import { createSearchSession } from "../www/js/features/search/search-session.js";
import * as store from "../www/js/core/state/store.js";
import { kodikTeams, mergeFranchise, parseSkipTimes, sortShikiResults, vostEpisodes, yaniGroups } from "../www/js/services/sources.js";

const ep = (k, extra = {}) => ({ key: String(k), ordinal: k, ...extra });

test("названия: одинаковые тайтлы в разных каталогах", () => {
  assert.equal(titleKey("Mushoku Tensei III"), titleKey("Mushoku Tensei 3"));
  assert.equal(titleKey("Магия (третий сезон)"), titleKey("Магия 3"));
  assert.ok(sameDub("Дублированный", "Дублированная") && sameDub("2x2", "2×2"));
  assert.deepEqual(searchQueries({ name: { english: "One Piece Film Red" } }, false), ["One Piece Film Red", "One Piece"]);
});

test("серии: продолжение просмотра и объединение источников", () => {
  const eps = [ep(1), ep(2), ep(3)];
  assert.deepEqual(resumeTarget(eps, { 1: { watched: true } }, null), [1, 0]);
  assert.deepEqual(resumeTarget(eps, {}, { key: "2", watched: false, pos: 60 }), [1, 60]);
  assert.deepEqual(resumeTarget(eps, { 2: { watched: true } }, { key: "2", watched: true }), [2, 0]);
  assert.equal(parseOrdinal("Серия 12,5", 1), 12.5);
  const union = unionEpisodes([["anilibria", [ep(1, { preview: "p" }), ep(2)]], ["kodik", [ep(2), ep(3)]]]);
  assert.deepEqual(shownEpisodes([ep(1)], union).map((e) => e.key), ["1", "2", "3"]);
  assert.deepEqual([...union.get("2").groups], ["anilibria", "kodik"]);
});

test("озвучки: порядок и выбор по умолчанию", () => {
  const dubs = sortDubs([{ id: "kodik:1", name: "AniStar", kind: "voice", native: false },
    { id: "kodik:2", name: "Subs", kind: "sub", native: false }, { id: "anilibria", name: "AniLibria", kind: "voice", native: true }]);
  assert.deepEqual(dubs.map((d) => d.id), ["anilibria", "kodik:1", "kodik:2"]);
  assert.equal(chooseDub(dubs, "kodik:2", "").id, "kodik:2");
  assert.equal(chooseDub(dubs, null, "anistar").id, "kodik:1");
  assert.equal(chooseDub(dubs, null, "").id, "anilibria");
  assert.equal(menuGroups(dubs).length, 3);
});

test("качество: по скорости из замера при запуске; понижение при подгрузках", () => {
  assert.equal(recommend(50, ["1080", "720"]), "1080");
  assert.equal(recommend(null, ["1080", "720", "480"]), "720");
  assert.equal(effectiveQuality(["720", "480"], "1080"), "720");
  let reads = 0;
  const p = new QualityPolicy("auto", () => { reads++; return 50; });
  const avail = ["1080", "720", "480"];
  assert.equal(p.choose(avail), "1080");
  assert.equal(p.stalled(avail, "1080", 0), null);
  assert.equal(p.stalled(avail, "1080", 10), null);
  assert.equal(p.stalled(avail, "1080", 20), "720");
  assert.equal(p.choose(avail), "720", "потолок держится");
  p.reset();
  assert.equal(p.choose(avail), "1080");
  assert.equal(reads, 3, "политика только читает сохранённое значение");
});

test("предстоящие серии: ждём озвучку и новые серии", () => {
  const items = upcoming({ episodes_total: 12 }, { status: "ongoing", episodes: 12, episodes_aired: 6, next_episode_at: "2026-09-30T15:00:00Z" },
    ["1", "2", "3", "4"], 3, new Date(2026, 8, 25));
  assert.deepEqual(items.slice(0, 2).map((i) => [i.n, i.state]), [[5, "dub"], [6, "dub"]]);
  assert.equal(items.at(-1).n, 12);
  assert.equal(items[0].date.getDate(), 30);
});

test("рекомендации: профиль, оценка и разбор ИИ", () => {
  const s = { library: { 1: { status: "completed", favorite: true, score: 10 }, 2: { status: "dropped" } },
    progress: { 1: { 1: { watched: true } } },
    anime: { 1: { id: 1, title: "T1", genres: ["Экшен", "Фэнтези"], type: "ТВ", year: 2020 }, 2: { id: 2, title: "T2", genres: ["Романтика"] } } };
  const p = profile(s);
  assert.equal(p.empty, false);
  assert.ok(p.disliked.has("Романтика"));
  const rel = (id, gs) => ({ id, name: { main: `R${id}` }, genres: gs.map((name) => ({ name })), year: 2020, type: { description: "ТВ" } });
  const scored = score(p, [rel(3, ["Экшен", "Фэнтези"]), rel(4, ["Романтика"])]);
  assert.deepEqual(scored.map((x) => x.rel.id), [3]);
  assert.deepEqual(scored[0].reason, { genres: ["Экшен", "Фэнтези"], similar: "T1" }, "причина — данными, текст собирает интерфейс");
  assert.deepEqual(summary(p), { top: ["Экшен", "Фэнтези"], year: 2020, type: "ТВ", typeShare: 100 });
  assert.deepEqual(becauseOf(p, scored), []);
  const ok = parseAi('{"analysis":"Вам нравится экшен","picks":[{"n":1,"reason":"да"}]}', [rel(3, [])]);
  assert.equal(ok.picks[0][0].id, 3);
  assert.equal(parseAi("мусор", []), "format");
  assert.equal(parseAi('{"analysis":"I think","picks":[{"n":1}]}', [rel(3, [])], "ru"), "unclear");
  assert.equal(parseAi('{"analysis":"You like action","picks":[{"n":1}]}', [rel(3, [])], "en").analysis, "You like action");
  assert.match(aiPrompt(p, [], "en"), /in English/);
});

test("поиск: сначала AniLibria, потом Shikimori без дублей", async () => {
  const session = createSearchSession("q", {
    catalog: async (f) => ({ meta: { pagination: { current_page: f.page, total_pages: 1, total: 1 } },
      data: [{ id: 1, name: { main: "Аниме" }, shikimori: { id: 101 } }] }),
    shikiSearch: async () => Object.assign([{ id: 101, name: "x" }, { id: 5, russian: "Аниме" }, { id: 7, name: "New" }], { hasMore: false }),
    fromRelease: (r) => ({ id: r.id }), fromShiki: (x) => ({ id: 200_000_000 + x.id }),
  });
  assert.deepEqual(await session.next(), [{ id: 1 }]);
  assert.deepEqual(await session.next(), [{ id: 200_000_007 }]);
  assert.ok(session.exhausted);
  assert.equal(session.extras, 1);
});

test("хранилище: списки, прогресс, подписки с отпиской", () => {
  const events = [];
  const off = store.subscribe((kind, id) => events.push([kind, id]));
  const synced = [];
  const offSync = store.onChange((kind) => synced.push(kind));
  store.remember({ id: 7, name: { main: "Семь" }, genres: [{ name: "Драма" }], animelib: "7--slug" });
  store.setFavorite(7, true);
  store.setStatus(7, "planned");
  store.markWatching(7);
  assert.equal(store.entry(7).status, "watching");
  assert.equal(store.anime(7).animelib, "7--slug", "slug AnimeLib сохраняется между запусками");
  assert.equal(store.saveProgress(7, "1", 1, 1400, 1440), true);
  assert.deepEqual(store.resumeTarget(7, [ep(1), ep(2)]), [1, 0]);
  assert.deepEqual(synced, ["status", "status", "episode"], "избранное на Shikimori не уходит");
  off(); offSync();
  store.setScore(7, 9);
  assert.equal(events.filter(([k]) => k === "score").length, 0, "после отписки событий нет");
  store.flush();
  assert.ok(JSON.parse(localStorage.getItem("animeapp:v1")).library[7].score === 9);
});

test("источники: разбор ответов", () => {
  assert.deepEqual(vostEpisodes([{ name: "2 серия", hd: "h" }, { name: "1 серия", std: "s" }, { name: "x" }]).map((e) => e.key), ["1", "2"]);
  const g = yaniGroups([{ number: "1", iframe_url: "//k/1", data: { player: "Kodik", dubbing: "Озвучка AniStar" }, skips: { opening: { time: 30, length: 90 } } },
    { number: "1", iframe_url: "//a/1", data: { player: "Alloha", dubbing: "AniStar" } }]);
  assert.deepEqual(Object.keys(g), ["yani:AniStar"]);
  assert.deepEqual(g["yani:AniStar"].eps[0].opening, { start: 30, stop: 120 });
  assert.equal(kodikTeams([{ player: "Kodik", team: { id: 3, name: "AniDUB" }, translation_type: { id: 1 } }]).get(3).kind, "sub");
  assert.deepEqual(parseSkipTimes({ found: true, results: [{ skipType: "op", interval: { startTime: 1, endTime: 90 } }] }), { opening: { start: 1, stop: 90 } });
  assert.deepEqual(sortShikiResults("frieren", [{ id: 1, name: "Frieren Special", kind: "special" }, { id: 2, name: "Frieren", kind: "tv" }, { id: 3, kind: "pv" }]).map((x) => x.id), [2, 1]);
  const entries = mergeFranchise({ id: 10, shikimori: { id: 100 } },
    { nodes: [{ id: 101, kind: "Фильм", year: 2022, name: "M" }, { id: 100, kind: "TV Сериал", year: 2020, name: "S1" }] },
    [{ franchise_releases: [{ release: { id: 10, shikimori: { id: 100 }, name: { main: "С1" } } }] }]);
  assert.deepEqual(entries.map((e) => [e.label, e.releaseId, e.current]), [["1 сезон", 10, true], ["Фильм", 200_000_101, false]]);
});
