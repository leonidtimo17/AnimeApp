"""Состояние сети приложения.

Скорость интернета меряется ОДИН раз — при запуске приложения — и хранится в NetworkState.
Больше приложение само её не меряет: ни по таймеру, ни перед серией, ни во время просмотра,
ни при смене сети. Повторный замер — только по кнопке «Проверить скорость».

«Есть ли интернет» узнаём без замеров: из событий ОС (QNetworkInformation) и по результатам
настоящих запросов приложения (HttpClient сообщает об удачах и сетевых ошибках).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Callable

from PySide6.QtCore import QObject, Signal

from ...core.logging import get_logger

log = get_logger("network")

SETTING_KEY = "network_bandwidth"   # последний замер: {"mbps", "checked_at"} — пока идёт новый и если он не удался


@dataclass(frozen=True)
class NetworkState:
    is_online: bool = True
    bandwidth_mbps: float | None = None
    checked_at: float | None = None      # time.time() последнего удачного замера
    measuring: bool = False


class NetworkService(QObject):
    state_changed = Signal(object)       # NetworkState
    connection_changed = Signal()        # ОС сообщила о смене сети (Wi-Fi ↔ мобильная, VPN)

    def __init__(self, probe, settings=None, parent=None, clock: Callable[[], float] = time.time):
        super().__init__(parent)
        self._probe = probe
        self._settings = settings
        self._clock = clock
        self._state = NetworkState()
        self._started = False
        self._os_info = None
        self.measurements = 0            # сколько замеров сделано за сеанс (для проверки и журнала)
        saved = (settings.get(SETTING_KEY) if settings else None) or {}
        if saved.get("mbps"):
            self._state = replace(self._state, bandwidth_mbps=float(saved["mbps"]), checked_at=saved.get("checked_at"))

    @property
    def state(self) -> NetworkState:
        return self._state

    # ------------------------------------------------------------------ запуск
    def start(self, sample_url_provider: Callable[[Callable[[str | None], None]], None]) -> bool:
        """Запуск приложения: подписка на события ОС и один замер скорости.
        sample_url_provider(cb) — найти видео для замера и вызвать cb(url | None).
        Повторный вызов ничего не делает (False)."""
        if self._started:
            return False
        self._started = True
        self._watch_os()
        self._measure(sample_url_provider, None)
        return True

    def measure_now(self, sample_url_provider: Callable[[Callable[[str | None], None]], None],
                    on_done: Callable[[NetworkState], None] | None = None) -> None:
        """Явная проверка скорости (кнопка в меню качества)."""
        self._measure(sample_url_provider, on_done)

    def _measure(self, provider, on_done) -> None:
        if self._state.measuring:
            return
        self._set(measuring=True)

        def with_url(url):
            if not url:
                self._finish(None, on_done)
                return
            self._probe.measure(url, lambda mbps: self._finish(mbps, on_done))
        provider(with_url)

    def _finish(self, mbps, on_done) -> None:
        self.measurements += 1
        if mbps:
            now = self._clock()
            log.info("Скорость интернета: %.1f Мбит/с", mbps)
            self._set(bandwidth_mbps=mbps, checked_at=now, measuring=False, is_online=True)
            if self._settings is not None:
                self._settings.set(SETTING_KEY, {"mbps": round(mbps, 2), "checked_at": now})
        else:
            log.info("Скорость измерить не удалось — используем прошлый результат: %s", self._state.bandwidth_mbps)
            self._set(measuring=False)
        if on_done:
            on_done(self._state)

    # ------------------------------------------------------------------ есть ли интернет
    def report_request(self, ok: bool) -> None:
        """Итог настоящего запроса приложения (без отдельных проверок)."""
        if ok != self._state.is_online:
            self._set(is_online=ok)

    def _watch_os(self) -> None:
        try:
            from PySide6.QtNetwork import QNetworkInformation
        except ImportError:
            return
        if not QNetworkInformation.loadDefaultBackend():
            log.info("ОС не сообщает о смене сети — узнаём о ней по ошибкам запросов")
            return
        info = QNetworkInformation.instance()
        self._os_info = info
        info.reachabilityChanged.connect(self._reachability_changed)
        if hasattr(info, "transportMediumChanged"):
            info.transportMediumChanged.connect(lambda *_: self.connection_changed.emit())
        self._reachability_changed(info.reachability())

    def _reachability_changed(self, reachability) -> None:
        from PySide6.QtNetwork import QNetworkInformation
        R = QNetworkInformation.Reachability
        if reachability == R.Unknown:
            return
        online = reachability in (R.Online, R.Site)
        changed = online != self._state.is_online
        self._set(is_online=online)
        if changed:
            self.connection_changed.emit()

    def _set(self, **changes) -> None:
        new = replace(self._state, **changes)
        if new != self._state:
            self._state = new
            self.state_changed.emit(new)
