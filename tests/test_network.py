"""Скорость интернета меряется один раз при запуске; дальше — только по явной просьбе."""
from PySide6.QtCore import QTimer

from anime_app.infrastructure.network.bandwidth import playlist_segments, speed_from_samples
from anime_app.infrastructure.network.service import SETTING_KEY, NetworkService
from tests.conftest import wait_until


class FakeProbe:
    def __init__(self, result=40.0):
        self.result = result
        self.urls = []

    def measure(self, url, on_done):
        self.urls.append(url)
        QTimer.singleShot(0, lambda: on_done(self.result))


class FakeSettings:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


def provider(url="https://cdn/master.m3u8"):
    return lambda cb: cb(url)


def test_measures_once_at_startup(qapp):
    probe, settings = FakeProbe(), FakeSettings()
    service = NetworkService(probe, settings)
    states = []
    service.state_changed.connect(states.append)
    assert service.start(provider())
    assert wait_until(qapp, lambda: service.measurements == 1)
    assert service.state.bandwidth_mbps == 40.0 and service.state.checked_at and not service.state.measuring
    assert settings.data[SETTING_KEY]["mbps"] == 40.0
    # повторный запуск и любые события ничего не меряют
    assert not service.start(provider())
    service.report_request(False)
    service.report_request(True)
    service.connection_changed.emit()
    wait_until(qapp, lambda: False, timeout=0.2)
    assert len(probe.urls) == 1 and service.measurements == 1
    assert any(s.measuring for s in states)


def test_explicit_recheck_is_allowed(qapp):
    probe = FakeProbe(10.0)
    service = NetworkService(probe, FakeSettings())
    service.start(provider())
    assert wait_until(qapp, lambda: service.measurements == 1)
    probe.result = 80.0
    done = []
    service.measure_now(provider("https://cdn/current.m3u8"), done.append)
    assert wait_until(qapp, lambda: done)
    assert done[0].bandwidth_mbps == 80.0 and probe.urls[-1] == "https://cdn/current.m3u8"


def test_failed_measurement_keeps_last_known_value(qapp):
    settings = FakeSettings({SETTING_KEY: {"mbps": 12.5, "checked_at": 1.0}})
    service = NetworkService(FakeProbe(None), settings)
    assert service.state.bandwidth_mbps == 12.5         # прошлый замер доступен сразу
    service.start(provider())
    assert wait_until(qapp, lambda: service.measurements == 1)
    assert service.state.bandwidth_mbps == 12.5


def test_no_sample_video_means_no_download(qapp):
    probe = FakeProbe()
    service = NetworkService(probe, FakeSettings())
    service.start(lambda cb: cb(None))
    assert wait_until(qapp, lambda: service.measurements == 1)
    assert probe.urls == [] and service.state.bandwidth_mbps is None


def test_online_state_from_real_requests(qapp):
    service = NetworkService(FakeProbe(), FakeSettings())
    service.report_request(False)
    assert not service.state.is_online
    service.report_request(True)
    assert service.state.is_online


def test_speed_calculation_skips_warmup():
    # 0.5 с разгона медленно, потом быстро: 8 МБ за 1 с после разгона = 64 Мбит/с
    samples = [(0, 100_000), (500, 200_000), (1000, 4_200_000), (1500, 8_200_000)]
    assert round(speed_from_samples(samples, 8_200_000)) == 64
    assert speed_from_samples([(0, 10)], 10) is None                  # слишком мало данных


def test_playlist_parsing():
    master = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\n720/index.m3u8\n"
    variant, segments = playlist_segments("https://cdn/a/master.m3u8", master)
    assert variant == "https://cdn/a/720/index.m3u8" and segments == []
    media = "#EXTM3U\n#EXTINF:4,\nseg1.ts\n#EXTINF:4,\nseg2.ts\n#EXTINF:4,\nseg3.ts\n"
    variant, segments = playlist_segments("https://cdn/a/720/index.m3u8", media)
    assert variant is None and segments == ["https://cdn/a/720/seg1.ts", "https://cdn/a/720/seg2.ts"]
