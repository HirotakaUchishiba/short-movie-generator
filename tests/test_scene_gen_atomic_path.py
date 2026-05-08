"""Phase X-2a: scene_gen の action_id 経路テスト。

action_id があるシーンで _get_animation_prompt / _build_background_prompt が
atomic SSOT 経由で prompt を組み立てることを確認する。
旧経路 (= action_id 無し) で挙動が変わらないことも regression test として確認。
"""
from __future__ import annotations

from scene_gen import _build_background_prompt, _get_animation_prompt


# ───────────── _get_animation_prompt ─────────────


def test_get_animation_prompt_uses_action_motion_when_no_explicit_prompt():
    scene = {
        "action_id": "surprise_pc",
        # animation_prompt なし
    }
    out = _get_animation_prompt(scene)
    # actions/surprise_pc.json の animation_motion から派生する文字列が含まれる
    assert "leans forward" in out or "eyes widen" in out, out


def test_get_animation_prompt_explicit_overrides_action():
    """scene.animation_prompt があれば action_id より優先される (= 旧経路維持)。"""
    scene = {
        "action_id": "surprise_pc",
        "animation_prompt": "OVERRIDE_MOTION_TOKEN",
    }
    out = _get_animation_prompt(scene)
    assert "OVERRIDE_MOTION_TOKEN" in out


def test_get_animation_prompt_unknown_action_falls_back_to_bg():
    """unknown action_id でも crash せず background_prompt fallback で動作。"""
    scene = {
        "action_id": "nonexistent_action_xyz",
        "background_prompt": "FALLBACK_BG_TOKEN",
    }
    out = _get_animation_prompt(scene)
    assert "FALLBACK_BG_TOKEN" in out


def test_get_animation_prompt_no_action_no_explicit_uses_bg_fallback():
    """旧来の挙動 (= action_id も animation_prompt も無し)。"""
    scene = {
        "background_prompt": "OLD_BG_TOKEN",
    }
    out = _get_animation_prompt(scene)
    assert "OLD_BG_TOKEN" in out


# ───────────── _build_background_prompt ─────────────


def test_build_background_prompt_uses_subject_state_when_no_bg_prompt():
    scene = {
        "action_id": "surprise_pc",
        # background_prompt なし
    }
    out = _build_background_prompt(scene)
    # actions/surprise_pc.json の subject_state から派生する文字列が含まれる
    assert "leaning forward" in out or "eyes wide" in out, out


def test_build_background_prompt_explicit_overrides_action():
    """scene.background_prompt があれば action より優先 (= 旧経路維持)。"""
    scene = {
        "action_id": "surprise_pc",
        "background_prompt": "EXPLICIT_BG_TOKEN",
    }
    out = _build_background_prompt(scene)
    assert "EXPLICIT_BG_TOKEN" in out


def test_build_background_prompt_no_action_uses_bg_prompt():
    """旧来の挙動 (= action_id 無し)。"""
    scene = {
        "background_prompt": "OLD_BG_PROMPT_TOKEN",
    }
    out = _build_background_prompt(scene)
    assert "OLD_BG_PROMPT_TOKEN" in out


def test_build_background_prompt_unknown_action_returns_empty_subject():
    """unknown action_id でも crash しない (= warning ログのみで継続)。"""
    scene = {
        "action_id": "nonexistent_action_xyz",
        # background_prompt なし
    }
    # 例外を出さずに動作することだけ確認
    out = _build_background_prompt(scene)
    assert isinstance(out, str)
