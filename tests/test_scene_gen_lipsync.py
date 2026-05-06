import os
from unittest.mock import MagicMock

import pytest

import scene_gen


@pytest.fixture
def temp_dir(tmp_path) -> str:
    return str(tmp_path)


def _base_scene(lines: list[dict] | None = None) -> dict:
    return {
        "duration": 5.0,
        "background_prompt": "bg",
        "animation_prompt": "motion",
        "lines": lines if lines is not None else [
            {"text": "セリフ", "start": 0.0, "end": 3.0}
        ],
    }


def _prepare_trim_and_audio(temp_dir: str, scene_idx: int = 0,
                              with_audio: bool = True) -> str:
    trim = os.path.join(temp_dir, f"scene_{scene_idx:03d}.trim.mp4")
    open(trim, "wb").write(b"trim")
    if with_audio:
        audio = os.path.join(temp_dir, f"audio_{scene_idx:03d}.m4a")
        open(audio, "wb").write(b"audio")
    return trim


def test_lipsync_disabled_globally_skips_lipsync(temp_dir, monkeypatch) -> None:
    monkeypatch.setattr(scene_gen.config, "LIPSYNC_ENABLED", False)
    _prepare_trim_and_audio(temp_dir)

    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 5.0)
    replace_spy = MagicMock()
    monkeypatch.setattr(scene_gen, "_replace_audio", replace_spy)
    lipsync_spy = MagicMock()
    monkeypatch.setattr(scene_gen.lipsync_client, "apply", lipsync_spy)

    scene_gen._scene_video_for_scene(
        0, _base_scene(), {}, temp_dir,
    )

    lipsync_spy.assert_not_called()
    replace_spy.assert_called_once()


def test_lipsync_disabled_per_scene_skips_lipsync(temp_dir, monkeypatch) -> None:
    monkeypatch.setattr(scene_gen.config, "LIPSYNC_ENABLED", True)
    _prepare_trim_and_audio(temp_dir)

    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 5.0)
    replace_spy = MagicMock()
    monkeypatch.setattr(scene_gen, "_replace_audio", replace_spy)
    lipsync_spy = MagicMock()
    monkeypatch.setattr(scene_gen.lipsync_client, "apply", lipsync_spy)

    scene = _base_scene()
    scene["lipsync"] = False
    scene_gen._scene_video_for_scene(
        0, scene, {}, temp_dir,
    )

    lipsync_spy.assert_not_called()
    replace_spy.assert_called_once()


def test_lipsync_enabled_invokes_client(temp_dir, monkeypatch) -> None:
    monkeypatch.setattr(scene_gen.config, "LIPSYNC_ENABLED", True)
    monkeypatch.setattr(scene_gen.config, "LIPSYNC_PROVIDER", "fal-sync")
    trim = _prepare_trim_and_audio(temp_dir)

    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 5.0)

    def fake_apply(v, a, out):
        assert v == trim
        open(out, "wb").write(b"lipsynced")

    mock_apply = MagicMock(side_effect=fake_apply)
    monkeypatch.setattr(scene_gen.lipsync_client, "apply", mock_apply)

    result = scene_gen._scene_video_for_scene(
        0, _base_scene(), {}, temp_dir,
    )

    assert result == os.path.join(temp_dir, "scene_000.mp4")
    mock_apply.assert_called_once()


def test_scene_without_lines_skips_lipsync(temp_dir, monkeypatch) -> None:
    monkeypatch.setattr(scene_gen.config, "LIPSYNC_ENABLED", True)
    _prepare_trim_and_audio(temp_dir)

    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 5.0)
    replace_spy = MagicMock()
    monkeypatch.setattr(scene_gen, "_replace_audio", replace_spy)
    lipsync_spy = MagicMock()
    monkeypatch.setattr(scene_gen.lipsync_client, "apply", lipsync_spy)

    scene_gen._scene_video_for_scene(
        0, _base_scene(lines=[]), {}, temp_dir,
    )

    lipsync_spy.assert_not_called()
    replace_spy.assert_called_once()
