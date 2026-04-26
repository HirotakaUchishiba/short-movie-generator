import os
from unittest.mock import MagicMock

import pytest

import scene_gen


@pytest.fixture
def temp_dir(tmp_path) -> str:
    return str(tmp_path)


def test_silent_mode_copies_trim_as_final(temp_dir, monkeypatch) -> None:
    trim = os.path.join(temp_dir, "scene_000.trim.mp4")
    open(trim, "wb").write(b"t")

    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 5.0)
    lipsync_spy = MagicMock()
    monkeypatch.setattr(scene_gen.lipsync_client, "apply", lipsync_spy)

    scene = {"duration": 4.0, "background_prompt": "bg",
             "lines": [{"text": "セーフ", "start": 0.5}]}
    result = scene_gen._scene_video_for_scene(
        0, scene, {"audio_mode": "silent"}, temp_dir,
    )

    assert result == os.path.join(temp_dir, "scene_000.mp4")
    assert os.path.exists(result)
    lipsync_spy.assert_not_called()


def test_silent_mode_without_lines(temp_dir, monkeypatch) -> None:
    trim = os.path.join(temp_dir, "scene_000.trim.mp4")
    open(trim, "wb").write(b"t")

    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 5.0)

    result = scene_gen._scene_video_for_scene(
        0,
        {"duration": 3.0, "background_prompt": "bg", "lines": []},
        {"audio_mode": "silent"}, temp_dir,
    )

    assert os.path.exists(result)
