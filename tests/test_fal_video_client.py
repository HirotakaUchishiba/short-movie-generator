import config
import fal_video_client


def test_pick_duration_short_snaps_to_5() -> None:
    assert fal_video_client._pick_duration(3.0) == 5
    assert fal_video_client._pick_duration(4.5) == 5
    assert fal_video_client._pick_duration(5.0) == 5


def test_pick_duration_within_tolerance_stays_at_5() -> None:
    """5.0 を僅かに超えても tolerance 内なら 5s クリップを選ぶ
    (slow_mo で吸収してコスト最適化)。"""
    assert fal_video_client._pick_duration(5.01) == 5
    assert fal_video_client._pick_duration(5.5) == 5
    # 境界: 5.0 * 1.2 = 6.0
    assert fal_video_client._pick_duration(6.0) == 5


def test_pick_duration_above_tolerance_snaps_to_10() -> None:
    assert fal_video_client._pick_duration(6.01) == 10
    assert fal_video_client._pick_duration(7.0) == 10
    assert fal_video_client._pick_duration(10.0) == 10


def test_pick_duration_very_long_capped_at_10() -> None:
    assert fal_video_client._pick_duration(15.0) == 10
    assert fal_video_client._pick_duration(30.0) == 10


def test_pick_duration_respects_config_tolerance(monkeypatch) -> None:
    """tolerance を変えれば境界も変わることを担保する。"""
    monkeypatch.setattr(config, "KLING_DURATION_TOLERANCE_RATIO", 1.0)
    assert fal_video_client._pick_duration(5.0) == 5
    assert fal_video_client._pick_duration(5.01) == 10

    monkeypatch.setattr(config, "KLING_DURATION_TOLERANCE_RATIO", 1.4)
    assert fal_video_client._pick_duration(7.0) == 5
    assert fal_video_client._pick_duration(7.01) == 10
