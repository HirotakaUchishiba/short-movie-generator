import shot_detector


def test_shots_within_clips_correctly() -> None:
    shots = [
        {"start": 0.0, "end": 2.0, "duration": 2.0},
        {"start": 2.0, "end": 5.0, "duration": 3.0},
        {"start": 5.0, "end": 7.0, "duration": 2.0},
        {"start": 7.0, "end": 10.0, "duration": 3.0},
    ]
    result = shot_detector.shots_within(shots, 1.0, 6.0)
    assert len(result) == 3
    assert result[0]["start"] == 0.0
    assert result[0]["duration"] == 1.0
    assert result[1]["start"] == 1.0
    assert result[1]["duration"] == 3.0
    assert result[2]["start"] == 4.0
    assert result[2]["duration"] == 1.0


def test_shots_within_filters_out_short() -> None:
    shots = [
        {"start": 0.0, "end": 5.0, "duration": 5.0},
        {"start": 5.0, "end": 5.1, "duration": 0.1},
    ]
    result = shot_detector.shots_within(shots, 0, 6)
    assert len(result) == 1


def test_shots_within_no_overlap() -> None:
    shots = [{"start": 10.0, "end": 12.0, "duration": 2.0}]
    assert shot_detector.shots_within(shots, 0, 5) == []
