from anime_app.domain.quality import (QualityPolicy, effective_quality, lower_quality, quality_name, recommend,
                                      required_mbps)

EP = {"streams": {"1080": "u1", "720": "u2", "480": "u3"}}


def test_recommend_by_speed():
    assert recommend(50) == "1080"
    assert recommend(6) == "720"
    assert recommend(2) == "480"
    assert recommend(None) == "720"                       # скорость неизвестна — до 720p
    assert recommend(None, ("1080",)) == "1080"
    assert recommend(1, ()) is None
    assert required_mbps("1080") == 9.0 and quality_name(1080) == "Full HD" and quality_name(2160) == "4K"


def test_effective_quality():
    assert effective_quality(["1080", "720", "480"], "1080") == "1080"
    assert effective_quality(["720", "480"], "1080") == "720"          # нужного нет — ближайшее ниже
    assert effective_quality(["1080", "720"], "480") == "720"          # ниже нет — самое низкое
    assert effective_quality(["1080", "720"], "1080", bad={"1080"}) == "720"
    assert effective_quality(["1080", "720", "480"], "1080", cap="720") == "720"
    assert effective_quality([], "720") is None
    assert lower_quality(["1080", "720", "480"], "1080", bad={"720"}) == "480"


def test_policy_uses_startup_bandwidth_only():
    calls = []

    def bandwidth():
        calls.append(1)
        return 5.0
    policy = QualityPolicy("auto", bandwidth)
    assert policy.choose(EP) == "720"
    # сколько бы серий ни открыли, политика только читает сохранённое значение, а не меряет
    for _ in range(5):
        policy.new_episode()
        policy.choose(EP)
    assert len(calls) == 7


def test_policy_manual_mode_and_labels():
    policy = QualityPolicy("480", lambda: 100)
    assert policy.choose(EP) == "480"
    policy.set_mode("auto")
    assert policy.choose(EP) == "1080"
    assert policy.seen_height("dub", "480", 360) and policy.label("dub", "480") == "360p · SD"
    assert not policy.seen_height("dub", "480", 360)


def test_policy_downgrades_on_stalls_and_resets_on_network_change():
    policy = QualityPolicy("auto", lambda: 100)
    policy.choose(EP)
    assert policy.stalled(EP, 0) is None and policy.stalled(EP, 10) is None
    assert policy.stalled(EP, 20) == "720"                  # третья подгрузка за минуту
    assert policy.choose(EP) == "720"                       # потолок держится на следующей серии
    policy.network_changed()
    assert policy.choose(EP) == "1080"
    manual = QualityPolicy("1080", lambda: 100)
    assert all(manual.stalled(EP, t) is None for t in (0, 1, 2))     # вручную выбранное не трогаем


def test_policy_failed_quality_falls_back():
    policy = QualityPolicy("1080", lambda: None)
    assert policy.failed(EP) == ("1080", "720")
    assert policy.effective(EP) == "720"
    policy.new_episode()
    assert policy.effective(EP) == "1080"
    only = {"streams": {"480": "u"}}
    assert policy.failed(only) == ("480", None)
