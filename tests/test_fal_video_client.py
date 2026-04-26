import fal_video_client


def test_pick_duration_short_snaps_to_5() -> None:
    assert fal_video_client._pick_duration(3.0) == 5
    assert fal_video_client._pick_duration(4.5) == 5
    assert fal_video_client._pick_duration(5.0) == 5


def test_pick_duration_long_snaps_to_10() -> None:
    assert fal_video_client._pick_duration(5.5) == 10
    assert fal_video_client._pick_duration(7.0) == 10
    assert fal_video_client._pick_duration(10.0) == 10


def test_pick_duration_very_long_capped_at_10() -> None:
    assert fal_video_client._pick_duration(15.0) == 10
    assert fal_video_client._pick_duration(30.0) == 10
