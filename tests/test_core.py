from anime_app.core.cache import TTLCache
from anime_app.core.errors import ApiError, AuthenticationError, NetworkError
from anime_app.core.formatting import fmt_duration, fmt_ms, fmt_ordinal, fmt_seconds


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_cache_ttl_expires():
    clock = Clock()
    c = TTLCache(max_size=10, default_ttl=5, clock=clock)
    c.set("a", 1)
    assert c.get("a") == 1
    clock.t = 6
    assert c.get("a") is None
    assert len(c) == 0


def test_cache_lru_eviction_by_size():
    c = TTLCache(max_size=2)
    c.set("a", 1)
    c.set("b", 2)
    c.get("a")          # «a» — недавно использованная
    c.set("c", 3)       # вытесняется «b»
    assert "a" in c and "c" in c and "b" not in c


def test_cache_eviction_by_weight_and_oversized_item():
    c = TTLCache(max_size=100, max_weight=10, weigher=len)
    c.set("a", "xxxx")
    c.set("b", "yyyy")
    c.set("c", "zzzz")          # 12 > 10 — вытесняется самая старая
    assert "a" not in c and c.weight == 8
    c.set("big", "x" * 50)      # больше всего кэша — не храним
    assert "big" not in c


def test_cache_none_value_and_discard_where():
    c = TTLCache()
    c.set(("t", 1), None)
    assert ("t", 1) in c
    c.set(("t", 2), 5)
    c.set(("u", 1), 6)
    c.discard_where(lambda k: k[0] == "t")
    assert len(c) == 1


def test_errors_are_readable_and_typed():
    err = ApiError("HTTP 404: not found", status=404)
    assert str(err) == "HTTP 404: not found" and err.is_client_error
    assert not ApiError("x", status=502).is_client_error
    assert isinstance(AuthenticationError("x"), ApiError)
    assert NetworkError("нет сети").transient


def test_formatting():
    assert fmt_ordinal(12.0) == "12" and fmt_ordinal(12.5) == "12.5" and fmt_ordinal("x") == "x"
    assert fmt_seconds(75) == "1:15" and fmt_seconds(3725) == "1:02:05"
    assert fmt_ms(75_000) == "1:15"
    assert fmt_duration(90 * 60) == "1 ч 30 мин" and fmt_duration(0) == ""
