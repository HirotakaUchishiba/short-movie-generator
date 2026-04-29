"""scene_gen._get_animation_prompt が auto_animation_prompt を採用する経路の検証。"""

from unittest.mock import MagicMock

import pytest

import scene_gen


def _scene_with_lines(animation_prompt: str | None = None) -> dict:
    s = {
        "duration": 5.0,
        "background_prompt": "デスクに向かう女性",
        "lines": [
            {"text": "やったー", "emotion": "喜び", "start": 0.0,
             "delivery": "弾むような声"},
        ],
    }
    if animation_prompt is not None:
        s["animation_prompt"] = animation_prompt
    return s


def test_explicit_animation_prompt_skips_auto(monkeypatch) -> None:
    """手書き animation_prompt があれば LLM は呼ばれない。"""
    monkeypatch.setattr(scene_gen.config, "AUTO_ANIMATION_PROMPT_ENABLED", True)
    monkeypatch.setattr(scene_gen.config, "ANTHROPIC_API_KEY", "k")

    spy = MagicMock()
    monkeypatch.setattr("auto_animation_prompt.generate", spy)

    scene = _scene_with_lines("manual prompt")
    out = scene_gen._get_animation_prompt(scene, ts_path=None, s_idx=0)
    assert out.startswith("manual prompt")
    spy.assert_not_called()


def test_auto_used_when_no_explicit(monkeypatch, tmp_path) -> None:
    """手書きが無ければ auto_animation_prompt.generate が呼ばれる。"""
    monkeypatch.setattr(scene_gen.config, "AUTO_ANIMATION_PROMPT_ENABLED", True)
    monkeypatch.setattr(scene_gen.config, "ANTHROPIC_API_KEY", "k")

    fake = MagicMock(return_value={
        "composed": "AUTO subject leans forward, subtle zoom, relief",
        "structured": {"subject": "x", "action_sequence": "y", "camera": "z", "mood": "w"},
        "input_hash": "h",
    })
    monkeypatch.setattr("auto_animation_prompt.generate", fake)

    scene = _scene_with_lines(animation_prompt=None)
    out = scene_gen._get_animation_prompt(
        scene, ts_path=str(tmp_path), s_idx=0)
    fake.assert_called_once()
    assert "AUTO subject leans forward" in out
    # in-memory に animation_prompt_auto がセットされる
    assert scene["animation_prompt_auto"] == fake.return_value["composed"]


def test_auto_disabled_falls_back_to_bg(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(scene_gen.config, "AUTO_ANIMATION_PROMPT_ENABLED", False)
    monkeypatch.setattr(scene_gen.config, "ANTHROPIC_API_KEY", "k")

    spy = MagicMock()
    monkeypatch.setattr("auto_animation_prompt.generate", spy)

    scene = _scene_with_lines(animation_prompt=None)
    out = scene_gen._get_animation_prompt(
        scene, ts_path=str(tmp_path), s_idx=0)
    spy.assert_not_called()
    assert "gentle cinematic motion" in out
    assert "デスクに向かう女性" in out


def test_auto_no_api_key_falls_back(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(scene_gen.config, "AUTO_ANIMATION_PROMPT_ENABLED", True)
    monkeypatch.setattr(scene_gen.config, "ANTHROPIC_API_KEY", None)

    spy = MagicMock()
    monkeypatch.setattr("auto_animation_prompt.generate", spy)

    scene = _scene_with_lines(animation_prompt=None)
    out = scene_gen._get_animation_prompt(
        scene, ts_path=str(tmp_path), s_idx=0)
    spy.assert_not_called()
    assert "gentle cinematic motion" in out


def test_auto_used_suppresses_emotion_arc_extras(monkeypatch, tmp_path) -> None:
    """auto 採用時は motion arc / facial arc / camera / tone の二重注入を抑止する。"""
    monkeypatch.setattr(scene_gen.config, "AUTO_ANIMATION_PROMPT_ENABLED", True)
    monkeypatch.setattr(scene_gen.config, "ANTHROPIC_API_KEY", "k")

    monkeypatch.setattr("auto_animation_prompt.generate", lambda *a, **kw: {
        "composed": "AUTO_PROMPT",
        "structured": {"subject": "x", "action_sequence": "y", "camera": "z", "mood": "w"},
        "input_hash": "h",
    })

    scene = _scene_with_lines(animation_prompt=None)
    out = scene_gen._get_animation_prompt(
        scene, ts_path=str(tmp_path), s_idx=0)
    assert "AUTO_PROMPT" in out
    # 既存の emotion arc / camera / tone の追加注入は出ない
    assert "motion arc:" not in out
    assert "facial arc:" not in out
    assert "camera:" not in out
    assert "tone:" not in out


def test_explicit_keeps_emotion_arc_extras(monkeypatch) -> None:
    """手書き採用時は従来通り emotion arc が付加される (互換性維持)。"""
    monkeypatch.setattr(scene_gen.config, "AUTO_ANIMATION_PROMPT_ENABLED", True)

    scene = _scene_with_lines("MANUAL_BASE")
    out = scene_gen._get_animation_prompt(scene, ts_path=None, s_idx=0)
    assert out.startswith("MANUAL_BASE")
    # 喜び の cue が付加されているはず
    assert "facial arc:" in out or "motion arc:" in out


def test_auto_failure_falls_back_silently(monkeypatch, tmp_path) -> None:
    """LLM が失敗した場合は警告ログを出して bg フォールバックする (クラッシュしない)。"""
    monkeypatch.setattr(scene_gen.config, "AUTO_ANIMATION_PROMPT_ENABLED", True)
    monkeypatch.setattr(scene_gen.config, "ANTHROPIC_API_KEY", "k")

    def boom(*a, **kw):
        raise RuntimeError("LLM boom")

    monkeypatch.setattr("auto_animation_prompt.generate", boom)

    scene = _scene_with_lines(animation_prompt=None)
    out = scene_gen._get_animation_prompt(
        scene, ts_path=str(tmp_path), s_idx=0)
    assert "gentle cinematic motion" in out


def test_auto_skipped_when_no_lines(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(scene_gen.config, "AUTO_ANIMATION_PROMPT_ENABLED", True)
    monkeypatch.setattr(scene_gen.config, "ANTHROPIC_API_KEY", "k")
    spy = MagicMock()
    monkeypatch.setattr("auto_animation_prompt.generate", spy)

    scene = {
        "duration": 5.0,
        "background_prompt": "屋外",
        "lines": [],
    }
    scene_gen._get_animation_prompt(scene, ts_path=str(tmp_path), s_idx=0)
    spy.assert_not_called()


def test_auto_passes_bg_path_when_bg_exists(monkeypatch, tmp_path) -> None:
    """Stage 3 完了後 = bg_<S>.png が存在すれば bg_path 引数で渡す。"""
    monkeypatch.setattr(scene_gen.config, "AUTO_ANIMATION_PROMPT_ENABLED", True)
    monkeypatch.setattr(scene_gen.config, "ANTHROPIC_API_KEY", "k")

    bg = tmp_path / "bg_000.png"
    bg.write_bytes(b"BG_DATA")

    captured = {}

    def fake_gen(*args, **kwargs):
        captured["bg_path"] = kwargs.get("bg_path")
        return {
            "composed": "AUTO_OUT",
            "structured": {"subject": "x", "action_sequence": "y",
                            "camera": "z", "mood": "w"},
            "input_hash": "h",
            "bg_used": True,
        }
    monkeypatch.setattr("auto_animation_prompt.generate", fake_gen)

    scene = _scene_with_lines(animation_prompt=None)
    scene_gen._get_animation_prompt(scene, ts_path=str(tmp_path), s_idx=0)
    assert captured["bg_path"] == str(bg)


def test_auto_passes_none_bg_when_bg_missing(monkeypatch, tmp_path) -> None:
    """Stage 3 未完了 = bg_<S>.png 無し → bg_path=None で渡す。"""
    monkeypatch.setattr(scene_gen.config, "AUTO_ANIMATION_PROMPT_ENABLED", True)
    monkeypatch.setattr(scene_gen.config, "ANTHROPIC_API_KEY", "k")

    captured = {}
    def fake_gen(*args, **kwargs):
        captured["bg_path"] = kwargs.get("bg_path")
        return {
            "composed": "AUTO_OUT",
            "structured": {"subject": "x", "action_sequence": "y",
                            "camera": "z", "mood": "w"},
            "input_hash": "h",
            "bg_used": False,
        }
    monkeypatch.setattr("auto_animation_prompt.generate", fake_gen)

    scene = _scene_with_lines(animation_prompt=None)
    scene_gen._get_animation_prompt(scene, ts_path=str(tmp_path), s_idx=0)
    assert captured["bg_path"] is None
