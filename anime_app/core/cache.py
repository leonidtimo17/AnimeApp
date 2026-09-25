"""Кэш в памяти: LRU с ограничением по числу записей и/или «весу» (байтам) и сроком жизни записи."""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Callable, Generic, Hashable, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")
_MISSING = object()


class TTLCache(Generic[K, V]):
    """Не растёт бесконечно: при переполнении вытесняются давно не использованные записи.

    ttl=None — запись живёт, пока её не вытеснят. weigher — «вес» значения (например, размер в байтах)
    для ограничения max_weight.
    """

    def __init__(self, max_size: int = 256, default_ttl: float | None = None, *,
                 max_weight: int | None = None, weigher: Callable[[V], int] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.max_weight = max_weight
        self._weigher = weigher or (lambda _v: 1)
        self._clock = clock
        self._data: OrderedDict[K, tuple[V, float | None, int]] = OrderedDict()
        self._weight = 0

    def get(self, key: K, default=None):
        item = self._data.get(key, _MISSING)
        if item is _MISSING:
            return default
        value, expires, _w = item
        if expires is not None and self._clock() >= expires:
            self.pop(key)
            return default
        self._data.move_to_end(key)
        return value

    def set(self, key: K, value: V, ttl: float | None = _MISSING) -> None:  # type: ignore[assignment]
        ttl = self.default_ttl if ttl is _MISSING else ttl
        self.pop(key)
        weight = self._weigher(value)
        if self.max_weight is not None and weight > self.max_weight:
            return   # одна запись больше всего кэша — не храним
        expires = None if ttl is None else self._clock() + ttl
        self._data[key] = (value, expires, weight)
        self._weight += weight
        self._evict()

    def pop(self, key: K, default=None):
        item = self._data.pop(key, _MISSING)
        if item is _MISSING:
            return default
        self._weight -= item[2]
        return item[0]

    def discard_where(self, predicate: Callable[[K], bool]) -> None:
        for key in [k for k in self._data if predicate(k)]:
            self.pop(key)

    def clear(self) -> None:
        self._data.clear()
        self._weight = 0

    def _evict(self) -> None:
        while self._data and (len(self._data) > self.max_size
                              or (self.max_weight is not None and self._weight > self.max_weight)):
            _key, (_v, _e, w) = self._data.popitem(last=False)
            self._weight -= w

    def __contains__(self, key: K) -> bool:
        return self.get(key, _MISSING) is not _MISSING

    def __len__(self) -> int:
        return len(self._data)

    @property
    def weight(self) -> int:
        return self._weight
