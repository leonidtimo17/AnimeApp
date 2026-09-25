"""Разбор ответов источников и поиск озвучек (с подменёнными API)."""
from anime_app.application.library import Preferences
from anime_app.application.search import SearchSession
from anime_app.application.sources import SourceResolver
from anime_app.infrastructure.api.anilibria import sample_stream
from anime_app.infrastructure.api.shikimori import shiki_item, shiki_release, sort_search_results
from anime_app.infrastructure.api.sources import (animelib_release, kodik_teams, parse_skip_times, vost_episodes,
                                                  vost_names, yani_dub_groups)


# ---------------------------------------------------------------- разбор ответов
def test_vost_parsing():
    assert vost_names("Атака титанов / Shingeki no Kyojin [1-25 из 25]") == ("Атака титанов", "Shingeki no Kyojin")
    eps = vost_episodes([{"name": "2 серия", "hd": "h2", "std": "s2"}, {"name": "1 серия", "std": "s1"},
                         {"name": "Трейлер"}])
    assert [e["key"] for e in eps] == ["1", "2"] and eps[1]["streams"] == {"720": "h2", "480": "s2"}


def test_yani_groups_only_kodik_and_dedup():
    videos = [
        {"number": "1", "iframe_url": "//kodik/1", "data": {"player": "Kodik", "dubbing": "Озвучка AniStar"},
         "skips": {"opening": {"time": 30, "length": 90}}},
        {"number": "1", "iframe_url": "//kodik/1b", "data": {"player": "Kodik", "dubbing": "Озвучка AniStar"}},
        {"number": "2", "iframe_url": "//alloha/2", "data": {"player": "Alloha", "dubbing": "AniStar"}},
        {"number": "1", "iframe_url": "https://kodik/s", "data": {"player": "kodik", "dubbing": "Субтитры"}},
    ]
    groups = yani_dub_groups(videos)
    assert set(groups) == {"yani:AniStar", "yani:Субтитры"}
    ani = groups["yani:AniStar"]["eps"]
    assert len(ani) == 1 and ani[0]["kodik"] == "https://kodik/1" and ani[0]["opening"] == {"start": 30, "stop": 120}
    assert groups["yani:Субтитры"]["kind"] == "sub"


def test_kodik_teams_and_skip_times():
    teams = kodik_teams([{"player": "Kodik", "team": {"id": 5, "name": "AniDUB"}, "translation_type": {"id": 2}},
                         {"player": "Kodik", "team": {"id": 6, "name": "Subs"}, "translation_type": {"id": 1}},
                         {"player": "Other", "team": {"id": 7, "name": "X"}}])
    assert teams[5]["id"] == "kodik:5" and teams[6]["kind"] == "sub" and 7 not in teams
    skips = parse_skip_times({"found": True, "results": [
        {"skipType": "op", "interval": {"startTime": 10, "endTime": 100}},
        {"skipType": "ed", "interval": {"startTime": 1300, "endTime": 1390}}]})
    assert skips == {"opening": {"start": 10, "stop": 100}, "ending": {"start": 1300, "stop": 1390}}
    assert parse_skip_times({"found": False}) is None


def test_shikimori_and_animelib_cards():
    x = {"id": 5, "name": "Frieren", "russian": "Фрирен", "kind": "tv", "episodes": 28, "aired_on": "2023-09-29",
         "status": "released", "score": "9.1", "image": {"original": "/system/5.jpg"}, "english": ["Frieren EN"],
         "genres": [{"russian": "Фэнтези"}], "rating": "pg_13", "description": "[b]Эльфийка[/b] путешествует"}
    item = shiki_item(x)
    assert item["id"] == 200_000_005 and item["subtitle"] == "2023 · ТВ · 28 эп." and item["badge"] is None
    rel = shiki_release(x)
    assert rel["description"] == "Эльфийка путешествует" and rel["age_rating"]["label"] == "13+"
    ordered = sort_search_results("frieren", [
        {"id": 1, "name": "Frieren Special", "kind": "special", "aired_on": "2020"},
        {"id": 2, "name": "Frieren", "kind": "tv", "aired_on": "2023"},
        {"id": 3, "name": "Frieren PV", "kind": "pv"}])
    assert [i["id"] for i in ordered] == [2, 1]
    al = animelib_release({"id": 7, "slug_url": "7--x", "rus_name": "Икс", "releaseDateString": "осень 2019",
                           "shikimori_href": "https://shikimori.one/animes/z123-x", "shiki_rate": 8.2},
                          {"summary": {"content": [{"content": [{"text": "Строка"}]}]}})
    assert al["id"] == 100_000_007 and al["year"] == 2019 and al["shikimori"] == {"rating": 8.2, "id": 123}
    assert al["description"] == "Строка" and al["poster"]["src"].endswith("/123.jpg")


def test_sample_stream_for_bandwidth():
    assert sample_stream([{"latest_episode": None}, {"latest_episode": {"hls_720": "u720", "hls_1080": "u1080"}}]) \
        == "u1080"
    assert sample_stream([]) is None


# ---------------------------------------------------------------- поиск озвучек
class Prefs:
    def __init__(self):
        self.data = {}

    def get(self, k, d=None):
        return self.data.get(k, d)

    def set(self, k, v):
        self.data[k] = v


class FakeVost:
    def __init__(self):
        self.finds = 0

    def find(self, release, cb):
        self.finds += 1
        self.cb = cb          # отвечает позже — как настоящая сеть

    def episodes(self, vost_id, on_ok, on_err=None):
        on_ok([{"key": "1", "ordinal": 1.0, "streams": {"720": "v"}}])


class FakeAnimeLib:
    def find(self, release, cb):
        cb("slug")

    def episodes(self, slug, on_ok, on_err=None):
        on_ok([{"key": "1", "ordinal": 1.0, "animelib_id": 11}, {"key": "2", "ordinal": 2.0, "animelib_id": 12}])

    def episode_players(self, eid, on_ok, on_err=None):
        on_ok([{"player": "Kodik", "team": {"id": 3, "name": "AniDUB"}},
               {"player": "Kodik", "team": {"id": 4, "name": "AnimeVost"}}])   # дубль «родной» озвучки


class FakeYani:
    def find(self, release, cb):
        cb(99)

    def dubs(self, anime_id, cb):
        cb({"yani:AniDUB": {"name": "AniDUB", "kind": "voice", "eps": [{"key": "1"}]},
            "yani:Studio Band": {"name": "Studio Band", "kind": "voice", "eps": [{"key": "1"}]}})


def resolver():
    vost = FakeVost()
    return SourceResolver(FakeAnimeLib(), vost, FakeYani(), None, Preferences(Prefs())), vost


RELEASE = {"id": 1, "name": {"main": "Тест"}, "episodes": [{"ordinal": 1, "hls_720": "a"}]}


def test_find_dubs_merges_sources_without_duplicates():
    res, vost = resolver()
    calls = []
    res.find_dubs(RELEASE, lambda dubs, fin: calls.append(([d["id"] for d in dubs], fin)))
    res.find_dubs(RELEASE, lambda dubs, fin: calls.append(("second", fin)))       # поиск уже идёт — не дублируем
    assert vost.finds == 1
    vost.cb(42)                                                                   # AnimeVost ответил последним
    final = [c for c in calls if c[1]]
    assert len(final) == 2
    ids = final[0][0]
    assert ids[:2] == ["anilibria", "animevost"]
    assert "kodik:3" in ids and "kodik:4" not in ids              # «AnimeVost» из Kodik — дубль родной озвучки
    assert "yani:AniDUB" not in ids and "yani:Studio Band" in ids  # YummyAnime — только новые команды
    # второй раз — из кэша, без сети
    res.find_dubs(RELEASE, lambda dubs, fin: calls.append(("cached", fin)))
    assert vost.finds == 1 and calls[-1] == ("cached", True)


def test_episodes_by_dub_and_invalidate():
    res, vost = resolver()
    res.find_dubs(RELEASE, lambda *_: None)
    vost.cb(42)
    got = {}
    for dub_id in ("anilibria", "animevost", "kodik:3", "yani:Studio Band"):
        res.episodes(RELEASE, {"id": dub_id}, lambda eps, d=dub_id: got.setdefault(d, eps))
    assert got["anilibria"][0]["streams"] == {"720": "a"} and got["animevost"][0]["streams"] == {"720": "v"}
    assert [e["animelib_id"] for e in got["kodik:3"]] == [11, 12]
    res.invalidate(1)
    after = []
    res.episodes(RELEASE, {"id": "kodik:3"}, after.append)
    assert after == [[]]                                    # данные забыты — серии появятся после нового поиска


def test_choose_and_remember_dub():
    res, _ = resolver()
    dubs = [{"id": "anilibria", "name": "AniLibria"}, {"id": "kodik:3", "name": "AniDUB"}]
    assert res.choose(RELEASE, dubs)["id"] == "anilibria"
    res.remember_choice(RELEASE, dubs[1])
    assert res.choose(RELEASE, dubs)["id"] == "kodik:3"
    assert res.choose({"id": 2}, dubs)["id"] == "kodik:3"    # любимая озвучка подставляется в другие тайтлы


# ---------------------------------------------------------------- поиск по двум каталогам
class FakeAniLibria:
    def catalog(self, ok, fail, page=1, **kw):
        total = 2
        ok({"meta": {"pagination": {"total_pages": total, "current_page": page, "total": 3}},
            "data": [{"id": page, "name": {"main": f"Аниме {page}"}, "shikimori": {"id": 100 + page}}]})


class FakeShiki:
    def search(self, query, ok, fail, page=1, scope=None):
        ok([{"id": 101, "name": "dup by id"}, {"id": 5, "russian": "Аниме 1"}, {"id": 7, "name": "New"}], False)


class FakeReleases:
    def items(self, rels):
        return [{"id": r["id"]} for r in rels]

    def shiki_card(self, x):
        return {"id": 200_000_000 + x["id"]}


def test_search_session_pages_both_catalogs():
    session = SearchSession(FakeAniLibria(), FakeShiki(), FakeReleases(), "аниме")
    pages = []
    session.next_page(pages.append, pages.append)
    assert [p.source for p in pages] == ["anilibria"] and not session.exhausted
    session.next_page(pages.append, pages.append)          # последняя страница AniLibria → сразу Shikimori
    assert [p.source for p in pages] == ["anilibria", "anilibria", "shikimori"]
    assert [i["id"] for i in pages[-1].items] == [200_000_007]      # дубли по id и названию отсеяны
    assert pages[-1].finished and session.exhausted and pages[-1].extra == 1
    session.next_page(pages.append, pages.append)
    assert len(pages) == 3


def test_search_without_query_does_not_touch_shikimori():
    session = SearchSession(FakeAniLibria(), None, FakeReleases(), "")
    pages = []
    session.next_page(pages.append, pages.append)
    session.next_page(pages.append, pages.append)
    assert session.exhausted and len(pages) == 2
