"""auto_animation_prompt モジュールの検証 (LLM 呼出はモック)。"""

import json
import os
from unittest.mock import MagicMock

import pytest

import auto_animation_prompt as aap


def _scene(**kw) -> dict:
    base = {
        "duration": 5.0,
        "background_prompt": "デスクに向かう女性",
        "lines": [
            {
                "text": "やったー",
                "emotion": "喜び",
                "delivery": "弾むような声",
                "acoustic": {"pitch_trend": "rising", "rms_peak": 0.4, "wpm": 200},
                "start": 0.0,
            }
        ],
    }
    base.update(kw)
    return base


def _mock_anthropic_response(json_payload: dict, monkeypatch) -> MagicMock:
    """anthropic.Anthropic().messages.create() の戻り値を mock する。"""
    fake_response = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(json_payload, ensure_ascii=False)
    fake_response.content = [block]

    fake_messages = MagicMock()
    fake_messages.create = MagicMock(return_value=fake_response)

    fake_client = MagicMock()
    fake_client.messages = fake_messages

    fake_anthropic_module = MagicMock()
    fake_anthropic_module.Anthropic = MagicMock(return_value=fake_client)

    import sys
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic_module)
    monkeypatch.setattr(aap.config, "ANTHROPIC_API_KEY", "test-key")
    return fake_messages


# ─────────── _input_signature / _input_hash ───────────


def test_input_hash_stable_for_same_input() -> None:
    s1 = _scene()
    s2 = _scene()
    h1 = aap._input_hash(aap._input_signature(s1, None))
    h2 = aap._input_hash(aap._input_signature(s2, None))
    assert h1 == h2


def test_input_hash_changes_when_text_changes() -> None:
    s1 = _scene()
    s2 = _scene(lines=[{"text": "違う", "emotion": "中立", "start": 0}])
    h1 = aap._input_hash(aap._input_signature(s1, None))
    h2 = aap._input_hash(aap._input_signature(s2, None))
    assert h1 != h2


def test_input_hash_changes_when_emotion_changes() -> None:
    base = _scene()
    other = _scene(lines=[{**base["lines"][0], "emotion": "焦り"}])
    h1 = aap._input_hash(aap._input_signature(base, None))
    h2 = aap._input_hash(aap._input_signature(other, None))
    assert h1 != h2


def test_input_hash_changes_when_acoustic_changes() -> None:
    base = _scene()
    line = base["lines"][0]
    other = _scene(lines=[{**line, "acoustic": {"pitch_trend": "falling"}}])
    h1 = aap._input_hash(aap._input_signature(base, None))
    h2 = aap._input_hash(aap._input_signature(other, None))
    assert h1 != h2


# ─────────── 出力検証 ───────────


def test_validate_structured_accepts_clean_output() -> None:
    aap._validate_structured({
        "subject": "Young woman",
        "action_sequence": "leans forward and exhales",
        "camera": "subtle zoom",
        "mood": "relief",
    })


def test_validate_structured_rejects_missing_field() -> None:
    with pytest.raises(ValueError):
        aap._validate_structured({
            "subject": "X",
            "action_sequence": "Y",
            # camera 抜け
            "mood": "Z",
        })


def test_validate_structured_rejects_empty_string() -> None:
    with pytest.raises(ValueError):
        aap._validate_structured({
            "subject": "X",
            "action_sequence": "",
            "camera": "Z",
            "mood": "W",
        })


def test_validate_structured_rejects_ui_words() -> None:
    """UI 誘発語が含まれていたら拒否する。"""
    with pytest.raises(ValueError, match="UI 誘発語"):
        aap._validate_structured({
            "subject": "Young woman",
            "action_sequence": "looks at chat bubble appearing on screen",
            "camera": "zoom",
            "mood": "happy",
        })


def test_compose_prompt_concatenates_fields() -> None:
    out = aap._compose_prompt({
        "subject": "Young woman in glasses",
        "action_sequence": "leans forward and exhales",
        "camera": "subtle zoom-in",
        "mood": "relief",
    })
    assert "Young woman in glasses" in out
    assert "leans forward" in out
    assert "subtle zoom-in" in out
    assert "relief" in out


def test_strip_json_fence_handles_markdown() -> None:
    fenced = '```json\n{"a":1}\n```'
    assert aap._strip_json_fence(fenced) == '{"a":1}'


def test_strip_json_fence_passthrough_for_plain_json() -> None:
    plain = '{"a":1}'
    assert aap._strip_json_fence(plain) == '{"a":1}'


# ─────────── キャッシュ ───────────


def test_cache_roundtrip(tmp_path) -> None:
    entry = {"composed": "x", "input_hash": "abc123", "structured": {}}
    aap._write_cache(str(tmp_path), 2, entry)
    got = aap._read_cache(str(tmp_path), 2, "abc123")
    assert got is not None
    assert got["composed"] == "x"


def test_cache_miss_on_hash_mismatch(tmp_path) -> None:
    aap._write_cache(str(tmp_path), 0, {"composed": "x", "input_hash": "old"})
    got = aap._read_cache(str(tmp_path), 0, "new")
    assert got is None


def test_cache_miss_when_file_absent(tmp_path) -> None:
    got = aap._read_cache(str(tmp_path), 99, "any")
    assert got is None


# ─────────── generate (LLM 呼出含む) ───────────


def test_generate_calls_llm_and_caches(tmp_path, monkeypatch) -> None:
    fake_messages = _mock_anthropic_response({
        "subject": "Young woman in glasses",
        "action_sequence": "leans toward laptop, eyes widen, then exhales",
        "camera": "subtle zoom-in",
        "mood": "tense relief",
    }, monkeypatch)

    scene = _scene()
    entry = aap.generate(scene, None, str(tmp_path), 0, force=False)

    fake_messages.create.assert_called_once()
    assert "Young woman" in entry["composed"]
    # キャッシュファイルが書かれている
    cache_file = aap._cache_path(str(tmp_path), 0)
    assert os.path.exists(cache_file)
    with open(cache_file) as f:
        cached = json.load(f)
    assert cached["composed"] == entry["composed"]


def test_generate_uses_cache_on_second_call(tmp_path, monkeypatch) -> None:
    fake_messages = _mock_anthropic_response({
        "subject": "S",
        "action_sequence": "A",
        "camera": "C",
        "mood": "M",
    }, monkeypatch)

    scene = _scene()
    aap.generate(scene, None, str(tmp_path), 0, force=False)
    aap.generate(scene, None, str(tmp_path), 0, force=False)
    # 2 回目はキャッシュ命中で LLM が呼ばれない
    assert fake_messages.create.call_count == 1


def test_generate_force_bypasses_cache(tmp_path, monkeypatch) -> None:
    fake_messages = _mock_anthropic_response({
        "subject": "S",
        "action_sequence": "A",
        "camera": "C",
        "mood": "M",
    }, monkeypatch)

    scene = _scene()
    aap.generate(scene, None, str(tmp_path), 0, force=False)
    aap.generate(scene, None, str(tmp_path), 0, force=True)
    # force=True で 2 回呼ばれる
    assert fake_messages.create.call_count == 2


def test_generate_ui_word_in_llm_output_raises(tmp_path, monkeypatch) -> None:
    """LLM が UI 語を返してきたら検証で失敗する。"""
    _mock_anthropic_response({
        "subject": "Young woman",
        "action_sequence": "checks the chat bubble that appears on her laptop",
        "camera": "zoom",
        "mood": "happy",
    }, monkeypatch)

    with pytest.raises(ValueError, match="UI 誘発語"):
        aap.generate(_scene(), None, str(tmp_path), 0, force=False)


def test_generate_no_api_key_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(aap.config, "ANTHROPIC_API_KEY", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        aap.generate(_scene(), None, str(tmp_path), 0, force=False)


def test_get_cached_returns_none_when_missing(tmp_path) -> None:
    assert aap.get_cached(str(tmp_path), 0, _scene(), None) is None


def test_get_cached_returns_entry_when_match(tmp_path, monkeypatch) -> None:
    _mock_anthropic_response({
        "subject": "S",
        "action_sequence": "A",
        "camera": "C",
        "mood": "M",
    }, monkeypatch)
    scene = _scene()
    aap.generate(scene, None, str(tmp_path), 0, force=False)
    got = aap.get_cached(str(tmp_path), 0, scene, None)
    assert got is not None
    assert got["composed"]
