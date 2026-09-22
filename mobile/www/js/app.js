// AnimeApp для планшета: экраны и навигация.
import * as api from "./api.js";
import * as player from "./player.js";
import { qualityName } from "./player.js";
import * as shiki from "./shiki.js";
import * as src from "./sources.js";
import * as store from "./store.js";
import * as taste from "./taste.js";
import { I, card, closeSheet, episodeTile, esc, fa, fillCards, fmtDate, sheet, toast } from "./ui.js";

const view = document.getElementById("view");
const tabs = document.getElementById("tabs");
const history = [];
let current = null;

// ------------------------------------------------------------------ навигация
function show(name, arg, push = true) {
  if (push && current) history.push(current);
  current = { name, arg };
  tabs.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  view.scrollTop = 0;
  (VIEWS[name] || VIEWS.home)(arg);
}
function back() {
  if (closeSheet()) return true;
  if (player.isOpen()) { player.close(); return true; }
  const prev = history.pop();
  if (!prev) return false;
  show(prev.name, prev.arg, false);
  return true;
}
tabs.onclick = (e) => { const b = e.target.closest("[data-tab]"); if (b) { history.length = 0; show(b.dataset.tab); } };
// Клавиатура (планшет с клавиатурой): Esc — назад, Ctrl+F или / — поиск. Клавиши плеера — в player.js.
// Esc на Android может прийти ещё и как системная «Назад» — второе срабатывание подряд пропускаем.
let lastEsc = 0;
window.Capacitor?.Plugins?.App?.addListener("backButton", () => {
  if (Date.now() - lastEsc < 400) return;
  if (!back()) window.Capacitor.Plugins.App.exitApp();
});
document.addEventListener("keydown", (e) => {
  const typing = e.target.closest?.("input, textarea, select");
  if (e.key === "Escape") {
    e.preventDefault();
    lastEsc = Date.now();
    if (typing) e.target.blur();
    else back();
    return;
  }
  if (typing || player.isOpen()) return;
  if ((e.ctrlKey && e.code === "KeyF") || e.key === "/") {
    e.preventDefault();
    if (current?.name !== "search") show("search");
    setTimeout(() => view.querySelector("#q")?.focus(), 50);
  }
});

// ------------------------------------------------------------------ Shikimori: вход, статистика, список
async function shikiBox(el, refresh) {
  const cfg = await shiki.config();
  const u = shiki.user();
  if (!cfg) {
    el.innerHTML = `<b>${fa("link")} Shikimori</b><p class="muted">Вход через Shikimori не настроен в этой сборке приложения.</p>`;
    return;
  }
  if (!u) {
    el.innerHTML = `<b>${fa("link")} Shikimori</b>
      <p class="muted">Войдите, и приложение будет отмечать просмотренные серии, статусы и оценки в вашем списке на Shikimori —
        там строится ваша статистика. А в плеере можно обсуждать серии.</p>
      <div class="shk-row"><button class="btn" id="shOpen">1. Открыть страницу входа</button>
        <input class="input" id="shCode" placeholder="2. Вставьте код с Shikimori" autocomplete="off">
        <button class="btn primary" id="shLogin">Войти</button></div>`;
    el.querySelector("#shOpen").onclick = async () => {
      const url = await shiki.authorizeUrl();
      const P = window.Capacitor?.Plugins?.PlayerScreen;
      if (P?.openUrl) P.openUrl({ url }).catch(() => window.open(url, "_blank"));
      else window.open(url, "_blank");
      toast("Разрешите доступ на Shikimori, скопируйте код и вставьте его сюда", 4000);
    };
    el.querySelector("#shLogin").onclick = async () => {
      const code = el.querySelector("#shCode").value.trim();
      if (!code) return toast("Сначала вставьте код со страницы Shikimori");
      try {
        const me = await shiki.login(code);
        toast(`Вы вошли как ${me.nickname}`);
        refresh();
      } catch (e) { toast(`Не удалось войти: ${e.message}. Попробуйте получить код ещё раз.`, 4000); }
    };
    return;
  }
  const on = store.setting("shikiSync", true);
  el.innerHTML = `<div class="shk-row"><img class="shk-av" src="${esc(u.avatar || "")}" alt="">
      <div style="flex:1;min-width:0"><b>${esc(u.nickname)}</b><div class="muted">Shikimori подключён</div></div>
      <button class="chip${on ? " on" : ""}" id="shSync">${on ? fa("check") + " " : ""}Отправлять прогресс</button></div>
    <div class="shk-row"><button class="btn small" id="shPush">Отправить весь список</button>
      <button class="btn small" id="shPull">Загрузить список с Shikimori</button>
      <button class="btn small" id="shOut">Выйти</button></div>`;
  el.querySelector("#shSync").onclick = () => { store.setSetting("shikiSync", !on); refresh(); };
  el.querySelector("#shOut").onclick = () => { shiki.logout(); toast("Вы вышли из Shikimori"); refresh(); };
  el.querySelector("#shPush").onclick = async (ev) => {
    const b = ev.currentTarget;
    b.disabled = true;
    try {
      const n = await shiki.pushAll((i, t) => (b.textContent = `Отправляем… ${i} из ${t}`));
      toast(`Отправлено на Shikimori: ${n}`);
    } catch (e) { toast(`Ошибка: ${e.message}`); }
    b.disabled = false; b.textContent = "Отправить весь список";
  };
  el.querySelector("#shPull").onclick = async (ev) => {
    ev.currentTarget.disabled = true;
    try { toast(`Загружено с Shikimori: ${await shiki.importList(src.shikiItem)}`); refresh(); }
    catch (e) { toast(`Ошибка: ${e.message}`); ev.currentTarget.disabled = false; }
  };
}

const openAnime = (item) => {
  if (item.release) store.remember(item.release, { poster: item.poster, subtitle: item.subtitle });
  show("details", item.id);
};
const itemFromRelease = (rel) => ({
  id: rel.id, title: src.title(rel), poster: api.posterUrl(rel), release: rel, badge: rel.is_ongoing ? "Онгоинг" : null,
  subtitle: [rel.year, rel.type?.description, rel.episodes_total ? `${rel.episodes_total} эп.` : ""].filter(Boolean).join(" · "),
});
const itemFromStored = (a, extra = {}) => ({ id: a.id, title: a.title, poster: a.poster, subtitle: a.subtitle, ...extra });

function section(title, id) { return `<h2>${title}</h2><div class="strip" id="${id}"><div class="muted">Загрузка…</div></div>`; }
function fail(el, e) { if (el) el.innerHTML = `<div class="muted">Не удалось загрузить: ${esc(e.message || e)}</div>`; }

// ------------------------------------------------------------------ экраны
const VIEWS = {
  home() {
    view.innerHTML = `<div class="row-head"><h1>Главная</h1><button class="btn small" id="sched">${fa("calendar")} Расписание</button></div>
      <div id="cont"></div>${section("Выходит сегодня", "today")}${section("Новые серии", "latest")}
      <div id="wish"></div>${section("Популярное", "top")}`;
    view.querySelector("#sched").onclick = () => show("schedule");
    const cont = store.continueWatching().map(({ anime, last }) => itemFromStored(anime, {
      progress: last.dur ? Math.min(1, last.pos / last.dur) : 0,
      subtitle: `${last.key} серия${last.watched ? " ✓ · далее следующая" : ""}`, play: true }));
    if (cont.length) {
      view.querySelector("#cont").innerHTML = `<h2>Продолжить просмотр</h2><div class="strip" id="contS"></div>`;
      fillCards(view.querySelector("#contS"), cont, (it) => play(it.id));
    }
    const wish = store.library("planned").slice(0, 20).map((a) => itemFromStored(a));
    if (wish.length) {
      view.querySelector("#wish").innerHTML = `<h2>Хочу посмотреть</h2><div class="strip" id="wishS"></div>`;
      fillCards(view.querySelector("#wishS"), wish, openAnime);
    }
    api.latest().then((d) => fillCards(view.querySelector("#latest"), d.map(itemFromRelease), openAnime)).catch((e) => fail(view.querySelector("#latest"), e));
    api.catalog({ sorting: "RATING_DESC", limit: 24 }).then((d) => fillCards(view.querySelector("#top"), d.data.map(itemFromRelease), openAnime)).catch((e) => fail(view.querySelector("#top"), e));
    api.schedule().then((d) => {
      const today = ((new Date().getDay() + 6) % 7) + 1;
      const items = d.filter((x) => x.release?.publish_day?.value === today).map((x) => ({ ...itemFromRelease(x.release),
        subtitle: x.next_release_episode_number ? `Ожидается ${x.next_release_episode_number} серия · сегодня` : "" }));
      fillCards(view.querySelector("#today"), items, openAnime, "Сегодня ничего не выходит");
    }).catch((e) => fail(view.querySelector("#today"), e));
  },

  schedule() {
    const names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"];
    const today = ((new Date().getDay() + 6) % 7) + 1;
    const order = [...Array(7)].map((_, i) => ((today - 1 + i) % 7) + 1);
    view.innerHTML = `<h1>Расписание</h1>` + order.map((d, i) => {
      const date = new Date(Date.now() + i * 86400_000);
      return `<h2>${names[d - 1]}, ${fmtDate(date, false).split(",")[0]}${i === 0 ? " — сегодня" : ""}</h2><div class="strip" id="d${d}"></div>`;
    }).join("");
    api.schedule().then((data) => {
      for (const d of order) {
        const items = data.filter((x) => x.release?.publish_day?.value === d).map((x) => ({ ...itemFromRelease(x.release),
          subtitle: x.next_release_episode_number ? `Ожидается ${x.next_release_episode_number} серия` : "" }));
        fillCards(view.querySelector(`#d${d}`), items, openAnime, "В этот день ничего не выходит");
      }
    }).catch((e) => fail(view.querySelector(`#d${today}`), e));
  },

  search() {
    view.innerHTML = `<h1>Поиск</h1><input class="input" id="q" placeholder="Название на русском, английском или японском…" autocomplete="off">
      <p class="muted" id="cnt"></p><div class="grid" id="res"></div>`;
    const q = view.querySelector("#q"), res = view.querySelector("#res"), cnt = view.querySelector("#cnt");
    q.value = store.setting("lastSearch", "");
    let timer, token = 0;
    const run = async () => {
      const text = q.value.trim();
      store.setSetting("lastSearch", text);
      if (!text) { res.innerHTML = ""; cnt.textContent = ""; return; }
      const my = ++token;
      cnt.textContent = "Ищем…";
      const [alR, shR] = await Promise.all([api.searchAL(text).catch(() => []), src.shikiSearch(text).catch(() => [])]);
      if (my !== token) return;
      const seenSid = new Set(alR.map((r) => r.shikimori?.id).filter(Boolean));
      const seenNames = new Set(alR.flatMap((r) => [src.norm(r.name?.main), src.norm(r.name?.english)]));
      const extra = shR.filter((x) => !seenSid.has(x.id) && !seenNames.has(src.norm(x.russian)) && !seenNames.has(src.norm(x.name))).map(src.shikiItem);
      cnt.textContent = `Найдено: ${alR.length}${extra.length ? ` + ${extra.length} из полного каталога` : ""}`;
      fillCards(res, [...alR.map(itemFromRelease), ...extra], openAnime, "Ничего не найдено");
    };
    q.oninput = () => { clearTimeout(timer); timer = setTimeout(run, 450); };
    run();
  },

  catalog() {
    const f = { sorting: "RATING_DESC", types: [], genres: [], ongoing: null, season: null, yearFrom: null, yearTo: null,
      ...store.setting("catalogFilters", {}) };
    const TYPES = [["TV", "ТВ"], ["ONA", "ONA"], ["WEB", "WEB"], ["OVA", "OVA"], ["MOVIE", "Фильм"], ["SPECIAL", "Спешл"]];
    const SORTS = [["RATING_DESC", "По рейтингу"], ["FRESH_AT_DESC", "Недавно обновлённые"], ["YEAR_DESC", "Сначала новые"], ["YEAR_ASC", "Сначала старые"]];
    const SEASONS = [["winter", "Зима"], ["spring", "Весна"], ["summer", "Лето"], ["autumn", "Осень"]];
    view.innerHTML = `<div class="row-head"><h1>Каталог</h1><button class="btn small" id="tog">${fa("filter")} Фильтры</button></div>
      <div class="filters" id="fl" hidden></div><p class="muted" id="cnt"></p><div class="grid" id="res"></div>
      <div style="text-align:center;margin:18px"><button class="btn" id="more" hidden>Показать ещё</button></div>`;
    const fl = view.querySelector("#fl"), res = view.querySelector("#res"), cnt = view.querySelector("#cnt"), more = view.querySelector("#more");
    view.querySelector("#tog").onclick = () => (fl.hidden = !fl.hidden);
    let page = 0, pages = 1, genres = [];
    const chip = (on, text, attrs) => `<button class="chip${on ? " on" : ""}" ${attrs}>${esc(text)}</button>`;
    function renderFilters() {
      fl.innerHTML = `
        <div class="label">Сортировка</div><select class="select" id="sort">${SORTS.map(([v, n]) => `<option value="${v}" ${f.sorting === v ? "selected" : ""}>${n}</option>`).join("")}</select>
        <div class="label">Статус</div><div class="chips">${[[null, "Все"], [true, "Выходит"], [false, "Вышло"]].map(([v, n]) => chip(f.ongoing === v, n, `data-st="${v}"`)).join("")}</div>
        <div class="label">Тип</div><div class="chips">${TYPES.map(([v, n]) => chip(f.types.includes(v), n, `data-ty="${v}"`)).join("")}</div>
        <div class="label">Сезон</div><div class="chips">${[[null, "Любой"], ...SEASONS].map(([v, n]) => chip(f.season === v, n, `data-se="${v}"`)).join("")}</div>
        <div class="label">Годы</div><div class="chips"><input class="select" id="yf" type="number" placeholder="от" value="${f.yearFrom || ""}" style="width:100px">
          <input class="select" id="yt" type="number" placeholder="до" value="${f.yearTo || ""}" style="width:100px"></div>
        <div class="label">Жанры ${f.genres.length > 1 ? "(все выбранные сразу)" : ""}</div><div class="chips">${genres.map((g) => chip(f.genres.includes(g.id), g.name, `data-ge="${g.id}"`)).join("")}</div>
        <div style="margin-top:12px"><button class="btn small" id="reset">Сбросить</button></div>`;
    }
    function changed() { store.setSetting("catalogFilters", f); renderFilters(); reload(); }
    fl.onclick = (e) => {
      const b = e.target.closest("button"); if (!b) return;
      if (b.id === "reset") { Object.assign(f, { types: [], genres: [], ongoing: null, season: null, yearFrom: null, yearTo: null }); return changed(); }
      if ("st" in b.dataset) f.ongoing = b.dataset.st === "null" ? null : b.dataset.st === "true";
      if ("se" in b.dataset) f.season = b.dataset.se === "null" ? null : b.dataset.se;
      if ("ty" in b.dataset) f.types = f.types.includes(b.dataset.ty) ? f.types.filter((x) => x !== b.dataset.ty) : [...f.types, b.dataset.ty];
      if ("ge" in b.dataset) { const g = +b.dataset.ge; f.genres = f.genres.includes(g) ? f.genres.filter((x) => x !== g) : [...f.genres, g]; }
      changed();
    };
    fl.onchange = (e) => {
      if (e.target.id === "sort") f.sorting = e.target.value;
      if (e.target.id === "yf") f.yearFrom = +e.target.value || null;
      if (e.target.id === "yt") f.yearTo = +e.target.value || null;
      changed();
    };
    async function load() {
      more.hidden = true;
      try {
        const d = await api.catalog({ ...f, page: page + 1 });
        page = d.meta.pagination.current_page; pages = d.meta.pagination.total_pages;
        cnt.textContent = `Найдено: ${d.meta.pagination.total}`;
        for (const r of d.data) res.appendChild(card(itemFromRelease(r), { onOpen: openAnime }));
        more.hidden = page >= pages;
        if (!d.data.length) res.innerHTML = `<div class="muted">Под такие фильтры ничего не нашлось.</div>`;
      } catch (e) { fail(res, e); }
    }
    function reload() { page = 0; res.innerHTML = ""; load(); }
    more.onclick = load;
    api.genres().then((g) => { genres = g.sort((a, b) => a.name.localeCompare(b.name)); renderFilters(); }).catch(() => renderFilters());
    reload();
  },

  library(tab = "watching") {
    const tabsDef = [...Object.entries(store.STATUSES), ["favorite", "Избранное"], ["history", "История"]];
    const s = store.stats();
    view.innerHTML = `<h1>Моё</h1><p class="muted">Просмотрено серий: ${s.episodes} · ${s.hours.toFixed(1)} ч</p>
      <div class="shiki-box" id="shk"></div>
      <div class="tabs2">${tabsDef.map(([k, n]) => `<button class="chip${k === tab ? " on" : ""}" data-t="${k}">${n}</button>`).join("")}</div><div id="lb"></div>`;
    view.querySelector(".tabs2").onclick = (e) => { const b = e.target.closest("[data-t]"); if (b) { current.arg = b.dataset.t; VIEWS.library(b.dataset.t); } };
    shikiBox(view.querySelector("#shk"), () => VIEWS.library(tab));
    const lb = view.querySelector("#lb");
    if (tab === "history") {
      const rows = store.history();
      lb.innerHTML = rows.length ? `<div style="text-align:right"><button class="btn small" id="clr">${fa("trash")} Очистить историю</button></div>` : `<p class="muted">Здесь появятся серии, которые вы смотрели.</p>`;
      for (const r of rows) {
        const d = document.createElement("div");
        d.className = "hist";
        d.innerHTML = `<div class="poster" style="background-image:url('${esc(r.anime.poster || "")}')"></div>
          <div style="flex:1;min-width:0"><b>${esc(r.anime.title)}</b><div class="muted">${r.key} серия · ${r.watched ? "просмотрено" : `${Math.floor(r.pos / 60)} из ${Math.floor(r.dur / 60)} мин`}</div>
          <div class="bar"><i style="width:${r.watched ? 100 : Math.round((r.pos / (r.dur || 1)) * 100)}%"></i></div></div>`;
        d.onclick = () => play(r.anime.id, r.key);
        lb.appendChild(d);
      }
      lb.querySelector("#clr")?.addEventListener("click", () => { store.clearHistory(); VIEWS.library("history"); });
      return;
    }
    const grid = document.createElement("div");
    grid.className = "grid";
    lb.appendChild(grid);
    fillCards(grid, store.library(tab).map((a) => itemFromStored(a)), openAnime, "Пока пусто. Добавляйте аниме кнопками на карточках.");
    const tools = document.createElement("div");
    tools.style.margin = "24px 0";
    tools.innerHTML = `<button class="btn small" id="cc">${fa("trash")} Очистить кэш</button>`;
    tools.querySelector("#cc").onclick = () => { api.clearCache(); toast("Кэш очищен. Списки и история сохранены."); };
    lb.appendChild(tools);
  },

  async recs() {
    view.innerHTML = `<div class="row-head"><h1>Для вас</h1><button class="btn small primary" id="ai">${fa("magic")} ИИ-разбор</button></div>
      <p class="muted" id="st">Анализируем ваши списки…</p><div id="taste"></div><div id="aiBox"></div>
      <h2>Рекомендуем вам</h2><div class="strip" id="main"></div><div id="because"></div>`;
    const p = taste.profile();
    const $ = (s) => view.querySelector(s);
    if (!p.empty) {
      const s = store.stats();
      $("#taste").innerHTML = `<div class="panel"><h2 style="margin-top:0">Ваш вкус</h2>
        <div class="stats"><div class="stat"><b>${s.inLists}</b><span class="muted">в списках</span></div>
        <div class="stat"><b>${s.episodes}</b><span class="muted">серий просмотрено</span></div>
        <div class="stat"><b>${Math.round(s.hours)} ч</b><span class="muted">за просмотром</span></div>
        <div class="stat"><b>${esc(Object.keys(p.types)[0] || "—")}</b><span class="muted">любимый формат</span></div></div>
        <p class="desc">${esc(taste.describe(p))}</p>
        ${Object.entries(p.genres).slice(0, 8).map(([g, v]) => `<div class="gbar"><span style="text-align:right">${esc(g)}</span>
          <div class="track"><i style="width:${Math.round(v * 100)}%"></i></div><span class="muted">${Math.round(v * 100)}%</span></div>`).join("")}</div>`;
    }
    const scored = taste.score(p, await taste.candidates(p));
    if (current?.name !== "recs") return;
    $("#st").textContent = p.empty ? "Пока мало данных — добавьте аниме в «Избранное», «Просмотрено» или «Смотрю». А пока — популярное."
      : `Проанализировано тайтлов: ${p.titles.length}.`;
    fillCards($("#main"), scored.slice(0, 30).map((x) => ({ ...itemFromRelease(x.rel),
      subtitle: p.empty ? itemFromRelease(x.rel).subtitle : `${Math.round(x.score * 100)}% · ${x.reason}` })), openAnime, "Не удалось подобрать");
    for (const liked of p.liked.slice(0, 3)) {
      const lg = new Set(liked.genres);
      if (lg.size < 2) continue;
      const picks = scored.filter((x) => (x.rel.genres || []).filter((g) => lg.has(g.name)).length >= Math.min(3, lg.size) - 1).slice(0, 12);
      if (picks.length < 4) continue;
      const wrap = document.createElement("div");
      wrap.innerHTML = `<h2>Потому что вам понравилось «${esc(liked.title)}»</h2><div class="strip"></div>`;
      fillCards(wrap.querySelector(".strip"), picks.map((x) => itemFromRelease(x.rel)), openAnime);
      $("#because").appendChild(wrap);
    }
    $("#ai").onclick = async () => {
      const box = $("#aiBox");
      box.innerHTML = `<div class="panel"><h2 style="margin-top:0">Разбор от ИИ</h2><p class="muted">ИИ думает… (Pollinations, бесплатно)</p></div>`;
      try {
        const r = await taste.ai(p, scored);
        box.innerHTML = `<div class="panel"><h2 style="margin-top:0">Разбор от ИИ</h2><p class="desc">${esc(r.analysis)}</p>
          <h2>ИИ советует</h2><div class="strip"></div></div>`;
        fillCards(box.querySelector(".strip"), r.picks.map(([rel, why]) => ({ ...itemFromRelease(rel), subtitle: why })), openAnime);
      } catch (e) {
        box.innerHTML = `<div class="panel"><p class="muted">${esc(e.message)}. Рекомендации ниже работают и без ИИ.</p></div>`;
      }
    };
  },

  async details(id) {
    view.innerHTML = `<button class="btn flat" id="bk">${fa("back")} Назад</button><div id="dt"><p class="muted">Загрузка…</p></div>`;
    view.querySelector("#bk").onclick = back;
    let rel;
    try { rel = await src.loadRelease(id); } catch (e) { return fail(view.querySelector("#dt"), e); }
    if (current?.name !== "details" || current.arg !== id) return;
    const poster = api.posterUrl(rel);
    store.remember(rel, { poster, subtitle: [rel.year, rel.type?.description].filter(Boolean).join(" · ") });
    const e = store.entry(id);
    const rating = [["shikimori", "Shikimori"], ["mal", "MyAnimeList"]].filter(([k]) => rel[k]?.rating)
      .map(([k, n]) => `<span><i class="fa" style="color:#ffc83d">${I.star}</i> <b>${(+rel[k].rating).toFixed(2)}</b> <span class="muted">${n}</span></span>`).join(" &nbsp; ");
    const meta = [["Тип", rel.type?.description], ["Год", rel.year], ["Эпизоды", rel.episodes_total], ["Возраст", rel.age_rating?.label],
      ["Статус", rel.is_ongoing ? "Выходит" : "Завершён"]].filter(([, v]) => v);
    view.querySelector("#dt").innerHTML = `
      <div class="hero"><div class="poster" style="background-image:url('${esc(poster || "")}')"></div>
        <div class="info"><h1>${esc(src.title(rel))}</h1><div class="muted">${esc([rel.name?.english, rel.name?.alternative].filter(Boolean).join(" / "))}</div>
          <div style="margin-top:8px">${rating}</div>
          <div class="meta">${meta.map(([k, v]) => `<span class="muted">${k}</span><span>${esc(v)}</span>`).join("")}</div>
          <div class="chips">${(rel.genres || []).map((g) => `<span class="chip">${esc(g.name)}</span>`).join("")}</div>
          <div class="actions">
            <button class="btn primary" id="play">${fa("play")} Смотреть</button>
            <button class="btn" id="status">${e.status ? fa("check") + " " + store.STATUSES[e.status] : fa("plus") + " В список"}</button>
            <button class="btn${e.favorite ? " on" : ""}" id="fav">${e.favorite ? fa("heart") + " В избранном" : fa("heart", "far") + " В избранное"}</button>
          </div></div></div>
      <p class="desc">${esc(rel.description || "")}</p>
      <div class="row-head"><h2 id="epT">Серии</h2><span class="sp"></span><span class="muted" id="qnote"></span>
        <button class="btn small" id="dub">${fa("mic")} Озвучка: ищем…</button></div>
      <div class="ranges" id="ranges"></div><div class="eps" id="eps"><p class="muted">Ищем серии во всех источниках…</p></div>
      <div id="soon"></div>
      <div id="seasons"></div>`;
    const $ = (s) => view.querySelector(s);
    $("#status").onclick = () => sheet([{ title: "Список", items: [...Object.entries(store.STATUSES).map(([k, n]) => ({ label: n, on: e.status === k,
      action: () => { store.setStatus(id, k); VIEWS.details(id); } })), ...(e.status ? [{ label: "Убрать из списков", action: () => { store.setStatus(id, null); VIEWS.details(id); } }] : [])] }]);
    $("#fav").onclick = () => { store.setFavorite(id, !e.favorite); VIEWS.details(id); };

    // сезоны и фильмы
    src.franchise(rel).then((entries) => {
      if (!entries.length || current?.arg !== id) return;
      $("#seasons").innerHTML = `<h2>Сезоны и фильмы</h2><div class="strip">${entries.map((x, i) => `<div class="season${x.current ? " cur" : ""}" data-i="${i}">
        <div class="poster" style="${x.poster ? `background-image:url('${esc(x.poster)}')` : ""}"></div>
        <div class="l">${esc(x.label)} · ${x.year || "анонс"}</div><div class="nm">${esc(x.name)}</div></div>`).join("")}</div>`;
      $("#seasons .strip").onclick = (ev) => { const s = ev.target.closest("[data-i]"); const x = s && entries[+s.dataset.i]; if (x && !x.current) show("details", x.releaseId); };
      // Прокручиваем только ленту (scrollIntoView дёргал бы и всю страницу)
      const cur = $("#seasons .cur"), strip = $("#seasons .strip");
      if (cur) strip.scrollLeft = cur.offsetLeft - strip.clientWidth / 2 + cur.clientWidth / 2;
    });

    // озвучки и серии
    const { dubs } = await src.findDubs(rel);
    if (current?.arg !== id) return;
    let dub = src.chooseDub(rel, dubs, store);
    const union = new Map();
    await Promise.all(dubs.filter((d, i, a) => a.findIndex((x) => (x.native ? x.id : "kodik") === (d.native ? d.id : "kodik")) === i)
      .map(async (d) => { for (const ep of await src.episodes(rel, d).catch(() => [])) {
        const slot = union.get(ep.key) || { ep, groups: new Set(), preview: null };
        slot.groups.add(d.native ? d.id : "kodik");
        slot.preview = slot.preview || ep.preview || null;
        union.set(ep.key, slot); } }));
    if (current?.arg !== id) return;
    let range = null;
    async function renderEps() {
      $("#dub").innerHTML = dub ? `${fa("mic")} ${esc(dub.name)}` : "Озвучки не найдены";
      const own = dub ? await src.episodes(rel, dub) : [];
      const ownKeys = new Set(own.map((x) => x.key));
      const top = Math.max(0, ...own.flatMap((x) => Object.keys(x.streams || {}).filter((q) => x.streams[q]).map(Number)));
      $("#qnote").textContent = top ? `до ${top}p (${qualityName(top)})` : (dub && !dub.native ? "плеер Kodik" : "");
      const all = [...own, ...[...union.values()].filter((s) => !ownKeys.has(s.ep.key)).map((s) => s.ep)].sort((a, b) => a.ordinal - b.ordinal);
      const prog = store.progress(id), last = store.lastProgress(id);
      $("#epT").textContent = all.length ? `Серии ${all.length}` : "Серии";
      if (!all.length) $("#eps").innerHTML = `<p class="muted">Серии не найдены ни в одном источнике. Добавьте в «Хочу посмотреть», чтобы не потерять.</p>`;
      const pages = Math.ceil(all.length / 100);
      if (range == null) { const [ri] = store.resumeTarget(id, own); range = Math.floor(Math.max(0, all.findIndex((x) => x.key === own[ri]?.key)) / 100); }
      $("#ranges").innerHTML = pages > 1 ? [...Array(pages)].map((_, i) => `<button class="chip${i === range ? " on" : ""}" data-r="${i}">${all[i * 100].key}–${all[Math.min(all.length, (i + 1) * 100) - 1].key}</button>`).join("") : "";
      const names = { anilibria: "AniLibria", animevost: "AnimeVost", kodik: "Kodik" };
      $("#eps").innerHTML = all.slice(range * 100, range * 100 + 100).map((x) => {
        const missing = !ownKeys.has(x.key);
        const p = prog[x.key];
        const note = missing ? "есть в: " + [...(union.get(x.key)?.groups || [])].map((g) => names[g] || g).join(", ") : (x.name || "");
        return episodeTile({ key: x.key, name: x.name, note, missing, current: last?.key === x.key,
          preview: x.preview || union.get(x.key)?.preview, poster,
          watched: !!p?.watched, progress: p?.dur ? p.pos / p.dur : 0 });
      }).join("") || $("#eps").innerHTML;
      $("#play").innerHTML = `${fa("play")} ${last ? "Продолжить" : "Смотреть"}`;
    }
    $("#ranges").onclick = (ev) => { const b = ev.target.closest("[data-r]"); if (b) { range = +b.dataset.r; renderEps(); } };
    $("#eps").onclick = (ev) => {
      const t = ev.target.closest("[data-k]"); if (!t) return;
      const slot = union.get(t.dataset.k);
      const inOwn = dub && slot?.groups.has(dub.native ? dub.id : "kodik");
      if (!inOwn && slot) {
        const alt = dubs.find((d) => d.native && slot.groups.has(d.id)) || (slot.groups.has("kodik") ? src.chooseDub(rel, dubs.filter((d) => !d.native), store) : null);
        if (alt) { dub = alt; store.setSetting(`dub:${id}`, alt.id); }
      }
      play(id, t.dataset.k, rel, dub);
    };
    $("#dub").onclick = () => dubs.length && sheet([
      ["Встроенный плеер", dubs.filter((d) => d.native)], ["Плеер Kodik — озвучка", dubs.filter((d) => !d.native && d.kind === "voice")],
      ["Плеер Kodik — субтитры", dubs.filter((d) => !d.native && d.kind === "sub")]].filter(([, x]) => x.length)
      .map(([title, items]) => ({ title, items: items.map((d) => ({ label: d.name, on: d.id === dub?.id,
        action: () => { dub = d; store.setSetting(`dub:${id}`, d.id); store.setSetting("preferredDub", d.name); renderEps(); } })) })));
    $("#play").onclick = () => play(id, "", rel, dub);
    await renderEps();

    // предстоящие серии
    const info = rel.shikimori?.id ? await src.shikiInfo(rel.shikimori.id) : null;
    const own = dub ? await src.episodes(rel, dub) : [];
    const dubbing = rel.is_ongoing || (rel.episodes_total && dub?.id === "anilibria" && own.length && own.length < rel.episodes_total);
    const keys = dub?.id === "anilibria" && dubbing ? own.map((x) => x.key) : [...union.keys()];
    const soon = src.upcoming(rel, info, keys, dubbing ? rel.publish_day?.value : null);
    if (soon.length && current?.arg === id) {
      $("#soon").innerHTML = `<h2>Предстоящие серии${info?.episodes ? ` · всего ${info.episodes}` : ""}</h2><div class="eps">${soon.map((s) => `
        <div class="ep soon"><div class="n"><span>${s.n} серия</span><i class="fa" style="color:${s.state === "upcoming" ? "var(--muted)" : "var(--accent)"}">${s.state === "upcoming" ? I.calendar : I.mic}</i></div>
        <div class="nm">${s.state === "dub" ? "озвучка ≈ " + fmtDate(s.date) : s.state === "no_dub" ? "вышла, ждём озвучку" : fmtDate(s.date)}</div></div>`).join("")}</div>`;
    }
  },
};

// ------------------------------------------------------------------ запуск плеера
async function play(id, key = "", rel = null, dub = null, position = null) {
  toast("Загружаем серии…", 1500);
  try {
    // Всегда свежие ссылки на поток (после смены сети/VPN старые не работают)
    rel = await src.loadRelease(id, true).catch(() => rel);
    if (!rel) throw new Error("нет соединения");
    const { dubs } = await src.findDubs(rel);
    dub = dub || src.chooseDub(rel, dubs, store);
    if (!dub) return toast("Серии не нашлись ни в одном источнике");
    store.setSetting(`dub:${id}`, dub.id);
    let eps = await src.episodes(rel, dub);
    if (!eps.length) return toast("В этой озвучке пока нет серий");
    const pv = await src.previews(rel, dubs).catch(() => ({}));
    eps = eps.map((e) => ({ ...e, preview: e.preview || pv[e.key] || null }));
    const seasons = await src.franchise(rel).catch(() => []);
    player.open({
      rel, dub, dubs, eps, seasons, poster: api.posterUrl(rel), key: eps.some((e) => e.key === key) ? key : "", position,
      onDub: (d, k, pos) => { store.setSetting("preferredDub", d.name); play(id, k, rel, d, pos > 5 ? pos : null); },
      onSeason: (entry) => play(entry.releaseId, ""),
      onClose: () => { if (current) show(current.name, current.arg, false); },
      // Переподключение не помогло — получаем свежие ссылки и продолжаем с того же места
      onStale: (k, pos) => { src.invalidate(id); play(id, k, null, dub, pos > 5 ? pos : null); },
    });
  } catch (e) { toast(`Не удалось открыть: ${e.message}`); }
}

show("home");
