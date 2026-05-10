"""scene_gen の _override_* (= novel intent escape hatch) 動作検証。

mismatch audit doc 1-3 で「_override_* が unwired」と指摘した修正の単体テスト。
完全な Imagen / Kling 呼び出しは行わず、prompt builder の引数だけを検証する。
"""

from __future__ import annotations


import scene_gen


# ───────────── _build_background_prompt ─────────────


def test_override_background_prompt_returns_as_is() -> None:
    """_override_background_prompt が指定されたら location 注入や emotion cue を
    一切経由せず、そのまま返す。"""

    scene = {
        "_override_background_prompt": "subject teleports through walls",
        # 通常なら影響を与えるはずのフィールドが付いていてもすべて無視されることを確認
        "location_ref": "home_office",
        "background_prompt": "ignored",
        "lines": [{"text": "x", "start": 0, "end": 1, "emotion": "驚き"}],
    }
    result = scene_gen._build_background_prompt(scene)
    assert result == "subject teleports through walls"


def test_override_background_prompt_empty_string_is_ignored() -> None:
    """空文字 / 空白だけの override は採用されず、通常経路に fall-through。"""

    scene = {
        "_override_background_prompt": "   ",
        "background_prompt": "actually used",
        "lines": [],
    }
    result = scene_gen._build_background_prompt(scene)
    # location 注入 / dom_cue 等が空なので background_prompt がそのまま入る
    assert "actually used" in result
    assert "subject teleports" not in result


def test_override_background_prompt_strips_surrounding_whitespace() -> None:
    scene = {
        "_override_background_prompt": "  subject sits  \n",
        "background_prompt": "ignored",
        "lines": [],
    }
    assert scene_gen._build_background_prompt(scene) == "subject sits"


def test_override_background_prompt_non_string_is_ignored() -> None:
    scene = {
        "_override_background_prompt": None,
        "background_prompt": "actually used",
        "lines": [],
    }
    result = scene_gen._build_background_prompt(scene)
    assert "actually used" in result


# ───────────── _get_animation_prompt ─────────────


def test_override_animation_prompt_returns_as_is() -> None:
    """_override_animation_prompt が指定されたら emotion arc / dom_cues /
    audio_dynamics を一切付けず、そのまま返す (= _augment_animation_prompt の
    frontload と negative constraint だけは別段階で付く設計)。"""

    scene = {
        "_override_animation_prompt": "subject crystallizes into glass shards",
        "animation_prompt": "ignored",
        "lines": [{"text": "x", "start": 0, "end": 1, "emotion": "驚き"}],
    }
    result = scene_gen._get_animation_prompt(scene)
    assert result == "subject crystallizes into glass shards"


def test_override_animation_prompt_empty_falls_through_to_explicit() -> None:
    scene = {
        "_override_animation_prompt": "",
        "animation_prompt": "explicit prompt used",
        "lines": [],
    }
    result = scene_gen._get_animation_prompt(scene)
    # explicit prompt が base になり emotion arc / dom_cues などが付く可能性は
    # あるが、override が無効化されたため "crystallizes" は登場しない
    assert "explicit prompt used" in result
    assert "crystallizes" not in result


def test_override_animation_prompt_strips_whitespace() -> None:
    scene = {
        "_override_animation_prompt": "\n  subject runs uphill\n",
        "animation_prompt": "ignored",
        "lines": [],
    }
    assert (
        scene_gen._get_animation_prompt(scene)
        == "subject runs uphill"
    )


def test_override_animation_prompt_non_string_falls_through() -> None:
    scene = {
        "_override_animation_prompt": 42,  # int は str ではない → 無視
        "animation_prompt": "fallback used",
        "lines": [],
    }
    result = scene_gen._get_animation_prompt(scene)
    assert "fallback used" in result
