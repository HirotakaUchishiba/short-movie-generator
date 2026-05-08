"""Phase X-2a: screenplay validator の atomic 関連拡張テスト。"""
from __future__ import annotations

from screenplay_validator import validate_screenplay


def _minimal_screenplay():
    return {
        "caption": "test",
        "scenes": [
            {
                "background_prompt": "test bg",
                "animation_prompt": "test motion",
            }
        ],
    }


def test_action_id_field_accepted_in_scene():
    sp = _minimal_screenplay()
    sp["scenes"][0]["action_id"] = "surprise_pc"
    errors = validate_screenplay(sp, strict=False, require_composed=False)
    assert errors == [], errors


def test_hook_id_field_accepted_in_root():
    sp = _minimal_screenplay()
    sp["hook_id"] = "paradox_q"
    errors = validate_screenplay(sp, strict=False, require_composed=False)
    assert errors == [], errors


def test_arc_id_field_accepted_in_root():
    sp = _minimal_screenplay()
    sp["arc_id"] = "low_to_high"
    errors = validate_screenplay(sp, strict=False, require_composed=False)
    assert errors == [], errors


def test_unknown_action_id_rejected():
    sp = _minimal_screenplay()
    sp["scenes"][0]["action_id"] = "nonexistent_action_xyz"
    errors = validate_screenplay(sp, strict=False, require_composed=False)
    assert any("action_id" in e and "未定義" in e for e in errors), errors


def test_unknown_hook_id_rejected():
    sp = _minimal_screenplay()
    sp["hook_id"] = "nonexistent_hook_xyz"
    errors = validate_screenplay(sp, strict=False, require_composed=False)
    assert any("hook_id" in e and "未定義" in e for e in errors), errors


def test_unknown_arc_id_rejected():
    sp = _minimal_screenplay()
    sp["arc_id"] = "nonexistent_arc_xyz"
    errors = validate_screenplay(sp, strict=False, require_composed=False)
    assert any("arc_id" in e and "未定義" in e for e in errors), errors


def test_action_id_relaxes_composed_required():
    """action_id があれば background_prompt が無くても require_composed を通る。"""
    sp = {
        "caption": "test",
        "scenes": [
            {
                "action_id": "surprise_pc",
            }
        ],
    }
    errors = validate_screenplay(sp, strict=False, require_composed=True)
    assert all("background_prompt" not in e for e in errors), errors


def test_no_action_id_still_requires_background_prompt():
    """action_id 無しなら旧来通り background_prompt 必須 (= 互換維持)。"""
    sp = {
        "caption": "test",
        "scenes": [
            {
                # action_id 無し、background_prompt 無し
            }
        ],
    }
    errors = validate_screenplay(sp, strict=False, require_composed=True)
    assert any("background_prompt" in e for e in errors), errors


def test_existing_screenplay_without_atomic_fields_still_validates():
    """既存 screenplay (= atomic フィールド一切無し) はそのまま通る。"""
    sp = _minimal_screenplay()
    errors = validate_screenplay(sp, strict=False, require_composed=True)
    assert errors == [], errors
