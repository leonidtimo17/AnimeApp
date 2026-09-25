import datetime as dt

from anime_app.domain import taste
from anime_app.domain.dubs import alternative_dub, choose_dub, menu_groups, representatives, sort_dubs
from anime_app.domain.episodes import (EpisodeUnion, anilibria_episodes, episode_ranges, parse_ordinal,
                                       progress_fraction, resume_target)
from anime_app.domain.franchise import merge_franchise
from anime_app.domain.ids import is_animelib_id, is_external_id, is_shiki_id, shiki_id
from anime_app.domain.library import is_watched, watched_count
from anime_app.domain.shikimori import comment_body, rate_update, render_body
from anime_app.domain.sleep_timer import SleepTimer
from anime_app.domain.titles import same_dub, search_queries, title_key
from anime_app.domain.upcoming import upcoming_episodes


def ep(key, **kw):
    return {"key": str(key), "ordinal": float(key), **kw}


# ---------------------------------------------------------------- названия и id
def test_title_key_matches_variants():
    assert title_key("Mushoku Tensei III") == title_key("Mushoku Tensei 3")
    assert title_key("Реинкарнация безработного (третий сезон)") == title_key("Реинкарнация безработного 3")
    assert title_key("Часть 2") == title_key("Part 2")


def test_search_queries_short_variants():
    q = search_queries({"name": {"english": "Frieren: Beyond Journey's End", "main": "Провожающая"}})
    assert q[0] == "Frieren: Beyond Journey's End" and "Frieren" in q
    assert search_queries({"name": {"english": "One Piece Film Red"}}, full_first=False) == ["One Piece Film Red",
                                                                                               "One Piece"]


def test_same_dub():
    assert same_dub("Дублированный", "Дублированная")
    assert same_dub("2x2", "2×2")
    assert not same_dub("AniDUB", "AniStar")


def test_ids():
    assert is_shiki_id(200_000_005) and not is_shiki_id(5)
    assert is_animelib_id(100_000_001) and not is_animelib_id(200_000_001)
    assert is_external_id(100_000_001)
    assert shiki_id({"shikimori": {"id": 7}}) == 7 and shiki_id({"shikimori": None}) is None


# ---------------------------------------------------------------- серии
def test_parse_ordinal():
    assert parse_ordinal("12", 1) == 12.0
    assert parse_ordinal("Серия 12,5", 1) == 12.5
    assert parse_ordinal(None, 3) == 3.0


def test_anilibria_episodes_parsing():
    rel = {"episodes": [
        {"ordinal": 1, "name": "Начало", "hls_1080": "u1080", "hls_720": "u720",
         "preview": {"optimized": {"preview": "/p/1.webp"}}},
        {"ordinal": 2, "hls_480": None},                           # без потоков — пропускается
        {"ordinal": 2.5, "name_english": "Special", "hls_480": "u480"},
    ]}
    eps = anilibria_episodes(rel, "https://media")
    assert [e["key"] for e in eps] == ["1", "2.5"]
    assert eps[0]["streams"] == {"1080": "u1080", "720": "u720"}
    assert eps[0]["preview"] == "https://media/p/1.webp"
    assert eps[1]["name"] == "Special"


def test_resume_target():
    eps = [ep(1), ep(2), ep(3)]
    # истории нет — первая непросмотренная
    assert resume_target(eps, {"1": {"watched": 1, "position": 0}}, None) == (1, 0)
    # последняя серия не досмотрена — с её места
    last = {"episode_id": "2", "watched": 0, "position": 60_000}
    assert resume_target(eps, {}, last) == (1, 60_000)
    # последняя досмотрена — следующая непросмотренная
    last = {"episode_id": "2", "watched": 1, "position": 0}
    assert resume_target(eps, {"2": {"watched": 1}}, last) == (2, 0)
    # всё просмотрено — остаёмся на последней
    last = {"episode_id": "3", "watched": 1, "position": 0}
    assert resume_target(eps, {}, last) == (2, 0)
    assert resume_target([], {}, None) == (0, 0)


def test_progress_fraction():
    assert progress_fraction({"watched": 1}) == 1.0
    assert progress_fraction({"position": 30, "duration": 120}) == 0.25
    assert progress_fraction(None) == 0.0


def test_episode_union_and_ranges():
    u = EpisodeUnion()
    u.add("anilibria", [ep(1, preview="p1"), ep(2)])
    u.add("kodik", [ep(2), ep(3)])
    own = [ep(1)]
    assert [e["key"] for e in u.shown(own)] == ["1", "2", "3"]
    assert u.groups("2") == {"anilibria", "kodik"} and u.preview("1") == "p1"
    eps = [ep(i) for i in range(1, 251)]
    assert episode_ranges(eps) == [("1", "100"), ("101", "200"), ("201", "250")]
    assert episode_ranges(eps[:50]) == []


# ---------------------------------------------------------------- озвучки
DUBS = [
    {"id": "kodik:2", "name": "AniStar", "kind": "voice", "native": False},
    {"id": "kodik:9", "name": "Crunchyroll", "kind": "sub", "native": False},
    {"id": "animevost", "name": "AnimeVost", "kind": "voice", "native": True},
    {"id": "anilibria", "name": "AniLibria", "kind": "voice", "native": True},
]


def test_sort_and_choose_dub():
    ordered = sort_dubs(DUBS)
    assert [d["id"] for d in ordered] == ["anilibria", "animevost", "kodik:2", "kodik:9"]
    assert choose_dub(ordered, "kodik:2", None)["id"] == "kodik:2"          # сохранённая для тайтла
    assert choose_dub(ordered, None, "AniStar")["id"] == "kodik:2"          # любимая
    assert choose_dub(ordered, "нет такой", "")["id"] == "anilibria"        # по умолчанию
    assert choose_dub([], None, None) is None


def test_dub_groups_and_alternatives():
    groups = dict(menu_groups(DUBS))
    assert len(groups["Встроенный плеер"]) == 2 and len(groups["Плеер Kodik — субтитры"]) == 1
    assert [d["id"] for d in representatives(sort_dubs(DUBS))] == ["anilibria", "animevost", "kodik:2"]
    assert alternative_dub(DUBS, {"animevost"}, lambda k: k[0])["id"] == "animevost"
    assert alternative_dub(DUBS, {"kodik"}, lambda k: k[-1])["id"] == "kodik:9"
    assert alternative_dub(DUBS, {"yani"}, lambda k: k[0]) is None


# ---------------------------------------------------------------- библиотека
def test_watched_rule():
    assert is_watched(22 * 60_000, 24 * 60_000)                   # осталось 2 минуты
    assert not is_watched(10 * 60_000, 24 * 60_000)
    assert is_watched(21 * 60_000, 24 * 60_000, ending_start_ms=20 * 60_000)   # досмотрели до титров
    assert is_watched(95_000, 100_000)                             # короткое видео: 10%
    assert not is_watched(0, 0)
    assert watched_count({"1": {"watched": 1, "ordinal": 1}, "3": {"watched": 1, "ordinal": 3.0},
                          "3.5": {"watched": 1, "ordinal": 3.5}, "4": {"watched": 0, "ordinal": 4}}) == 3


# ---------------------------------------------------------------- Shikimori
def test_rate_update_never_decreases_episodes():
    body = rate_update({"status": "watching", "score": 8}, 3, {"episodes": 5, "status": "watching"})
    assert body == {"episodes": 5, "status": "watching", "score": 8}
    assert rate_update({"status": None, "score": None}, 0, None) is None
    assert rate_update({"status": "postponed"}, 0, None)["status"] == "on_hold"
    assert rate_update({}, 2, None)["status"] == "watching"


def test_comment_markup_is_safe():
    html_out = render_body('<script>x</script> [b]жирно[/b] [spoiler]тайна[/spoiler] на 12:34')
    assert "<script>" not in html_out and "&lt;script&gt;" in html_out
    assert "<b>жирно</b>" in html_out
    assert 'href="t:754"' in html_out
    assert comment_body("текст", episode_label="3 серия", moment="1:02", spoiler=True) == \
        "[b]3 серия, 1:02[/b] [spoiler]текст[/spoiler]"
    assert comment_body("текст", episode_label=None, moment=None, spoiler=False) == "текст"


# ---------------------------------------------------------------- предстоящие серии, франшиза
def test_upcoming_dub_and_release_dates():
    info = {"status": "ongoing", "episodes": 12, "episodes_aired": 6, "next_episode_at": "2026-09-30T15:00:00Z"}
    items = upcoming_episodes({"episodes_total": 12}, info, ["1", "2", "3", "4"], dub_weekday=3,
                              today=dt.date(2026, 9, 25))
    states = [(i["ordinal"], i["state"]) for i in items]
    assert states[:2] == [(5, "dub"), (6, "dub")]
    assert states[2][1] == "upcoming" and states[-1][0] == 12
    assert items[0]["date"].date() == dt.date(2026, 9, 30)      # ближайшая среда


def test_upcoming_released_title_without_dub():
    items = upcoming_episodes({}, {"status": "released", "episodes": 3}, ["1"])
    assert [(i["ordinal"], i["state"]) for i in items] == [(2, "no_dub"), (3, "no_dub")]


def test_franchise_merge():
    release = {"id": 10, "shikimori": {"id": 100}}
    nodes = [{"id": 101, "kind": "Фильм", "year": 2022, "name": "Movie", "image_url": "/x.jpg"},
             {"id": 100, "kind": "TV Сериал", "year": 2020, "name": "S1"},
             {"id": 102, "kind": "TV Сериал", "year": 2023, "name": "S2", "image_url": "missing"},
             {"id": 103, "kind": "Клип", "year": 2021, "name": "PV"}]
    al = [{"id": 10, "shikimori": {"id": 100}, "name": {"main": "Сезон 1"}}]
    entries = merge_franchise(release, nodes, al, lambda r: f"poster:{r['id']}", "https://shiki")
    assert [e["label"] for e in entries] == ["1 сезон", "Фильм", "2 сезон"]
    assert entries[0]["current"] and entries[0]["release_id"] == 10 and entries[0]["poster"] == "poster:10"
    assert entries[1]["poster"] == "https://shiki/system/animes/original/101.jpg"
    assert entries[2]["poster"] is None
    assert merge_franchise(release, [nodes[1]], [], lambda r: None, "") == []


# ---------------------------------------------------------------- рекомендации
def rel(i, genres, year=2020, typ="ТВ", rating=8.0):
    return {"id": i, "name": {"main": f"T{i}"}, "genres": [{"name": g} for g in genres], "year": year,
            "type": {"description": typ}, "shikimori": {"rating": rating}}


def test_taste_profile_and_scoring():
    library = [{"anime_id": 1, "status": "completed", "favorite": 1, "score": 10},
               {"anime_id": 2, "status": "dropped", "favorite": 0, "score": None}]
    releases = {1: rel(1, ["Экшен", "Фэнтези"]), 2: rel(2, ["Романтика"], year=2005)}
    p = taste.build_profile(library, [{"anime_id": 1, "eps": 12, "ms": 12 * 24 * 60_000}], releases)
    assert not p.empty and list(p.genres)[:2] == ["Экшен", "Фэнтези"]
    assert "Романтика" in p.disliked_genres
    assert p.episodes == 12 and round(p.hours) == 5
    scored = taste.score(p, [rel(3, ["Экшен", "Фэнтези"]), rel(4, ["Романтика"]), rel(5, ["Экшен"], rating=5)])
    assert [r["id"] for _, r, _ in scored] == [3, 5]          # нелюбимый жанр отсеян
    assert "похоже на «T1»" in scored[0][2]
    assert "Вам больше всего заходят" in p.describe()


def test_candidate_queries():
    p = taste.TasteProfile()
    p.genres = {"Экшен": 1.0, "Драма": 0.5, "Спорт": 0.2}
    q = taste.candidate_queries(p, {"Экшен": 1, "Драма": 2})
    assert {"genres": [1, 2], "sorting": "RATING_DESC", "limit": 30} in q
    assert q[-1]["sorting"] == "FRESH_AT_DESC"


def test_parse_ai_answer():
    pool = [rel(1, ["Экшен"]), rel(2, ["Драма"])]
    good = '{"choices":[{"message":{"content":"{\\"analysis\\":\\"Вам нравится экшен\\",\\"picks\\":[{\\"n\\":2,\\"reason\\":\\"драма\\"}]}"}}]}'
    analysis, picks = taste.parse_ai_answer(good, pool)
    assert analysis == "Вам нравится экшен" and picks[0][0]["id"] == 2
    assert isinstance(taste.parse_ai_answer("not json", pool), str)
    english = '{"analysis": "I think the user likes action", "picks": [{"n": 1}]}'
    assert isinstance(taste.parse_ai_answer(english, pool), str)       # рассуждения по-английски — брак


# ---------------------------------------------------------------- таймер сна
def test_sleep_timer():
    now = [1000.0]
    t = SleepTimer(clock=lambda: now[0])
    changes = []
    t.subscribe(lambda: changes.append(1))
    assert t.set(30) == "Таймер сна: остановлю через 30 мин" and t.active
    assert t.minutes_left() == 31          # как раньше: округление вверх
    assert not t.due()
    now[0] += 30 * 60
    assert t.due() and not t.active
    assert t.set(0, after_episode=True).startswith("Остановлю") and t.episode_ended() and not t.episode_ended()
    job = t.to_job()
    t.from_job(5_000_000, 15, False)
    assert t.until == 5000 and job["episode"] is False
    assert len(changes) >= 4


# ---------------------------------------------------------------- Kodik
def test_kodik_url_normalized():
    from urllib.parse import parse_qs, urlsplit
    from anime_app.domain.kodik import kodik_url
    u = urlsplit(kodik_url("//kodikplayer.com/seria/1/abc/720p", 600.7))
    q = parse_qs(u.query)
    assert u.scheme == "https" and q["translations"] == ["false"] and q["start_from"] == ["600"]
    assert "start_from" not in kodik_url("https://kodikplayer.com/seria/1/abc/720p", 3)
    season = parse_qs(urlsplit(kodik_url("//kodikplayer.com/season/9/x/720p?episode=2&start_from=50")).query)
    assert season["only_episode"] == ["true"] and season["episode"] == ["2"] and "start_from" not in season


def test_pick_kodik_player():
    from anime_app.domain.kodik import pick_kodik_player
    players = [{"player": "Kodik", "src": "//a", "team": {"id": 1, "name": "A"}},
               {"player": "Kodik", "src": "//b", "team": {"id": 2, "name": "B"}}, {"player": "Other", "src": "//c"}]
    assert pick_kodik_player(players, "2") == {"src": "//b", "team": "B", "fallback": False}
    assert pick_kodik_player(players, 9) == {"src": "//a", "team": "A", "fallback": True}
    assert pick_kodik_player([{"player": "Other", "src": "//c"}], 1) is None
