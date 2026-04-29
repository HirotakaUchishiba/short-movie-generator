"""prompt_revise モジュールの検証 (LLM 呼出はモック)。"""

from unittest.mock import MagicMock

import pytest

import prompt_revise


def _mock_anthropic_response(text: str, monkeypatch) -> MagicMock:
    fake_response = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = text
    fake_response.content = [block]

    fake_messages = MagicMock()
    fake_messages.create = MagicMock(return_value=fake_response)
    fake_client = MagicMock()
    fake_client.messages = fake_messages

    fake_anthropic_module = MagicMock()
    fake_anthropic_module.Anthropic = MagicMock(return_value=fake_client)

    import sys
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic_module)
    monkeypatch.setattr(prompt_revise.config, "ANTHROPIC_API_KEY", "test-key")
    return fake_messages


# ─────────── _strip_wrappers ───────────


def test_strip_wrappers_removes_markdown_fence() -> None:
    assert prompt_revise._strip_wrappers("```\nhello world\n```") == "hello world"


def test_strip_wrappers_removes_text_fence() -> None:
    assert prompt_revise._strip_wrappers("```text\nfoo bar\n```") == "foo bar"


def test_strip_wrappers_removes_double_quotes() -> None:
    assert prompt_revise._strip_wrappers('"a young woman leans"') == "a young woman leans"


def test_strip_wrappers_passthrough_plain() -> None:
    assert prompt_revise._strip_wrappers("plain text") == "plain text"


# ─────────── _validate_revised ───────────


def test_validate_revised_accepts_clean() -> None:
    prompt_revise._validate_revised("a young woman leans toward laptop")


def test_validate_revised_rejects_empty() -> None:
    with pytest.raises(ValueError):
        prompt_revise._validate_revised("")


def test_validate_revised_rejects_ui_terms() -> None:
    with pytest.raises(ValueError, match="UI 誘発語"):
        prompt_revise._validate_revised(
            "young woman taps a chat bubble on her laptop"
        )


# ─────────── revise (LLM 呼出含む) ───────────


def test_revise_background_returns_revised_text(monkeypatch) -> None:
    fake_messages = _mock_anthropic_response(
        "デスクに駆け寄るエンジニア wide shot, cinematic lighting",
        monkeypatch,
    )

    out = prompt_revise.revise(
        current_prompt="デスクに駆け寄るエンジニア cinematic lighting",
        instruction_ja="カメラを引いて wide shot にして",
        field="background_prompt",
    )

    assert "wide shot" in out["revised"]
    assert out["field"] == "background_prompt"
    assert out["model"]
    fake_messages.create.assert_called_once()
    # システムプロンプトに background 用の文言が含まれる
    _, kwargs = fake_messages.create.call_args
    assert "Imagen" in kwargs["system"]


def test_revise_animation_uses_animation_system_prompt(monkeypatch) -> None:
    fake_messages = _mock_anthropic_response(
        "young woman leans forward then exhales, subtle zoom-in, relief",
        monkeypatch,
    )

    out = prompt_revise.revise(
        current_prompt="young woman taps keyboard, subtle zoom, tense",
        instruction_ja="深呼吸して安堵する流れに変えて",
        field="animation_prompt",
    )

    assert "exhales" in out["revised"]
    _, kwargs = fake_messages.create.call_args
    assert "Kling" in kwargs["system"]


def test_revise_strips_quotes_from_llm_output(monkeypatch) -> None:
    _mock_anthropic_response(
        '"young woman leans forward and exhales"',
        monkeypatch,
    )

    out = prompt_revise.revise(
        current_prompt="x",
        instruction_ja="深呼吸してから笑顔に",
        field="animation_prompt",
    )
    assert out["revised"] == "young woman leans forward and exhales"


def test_revise_rejects_unknown_field() -> None:
    with pytest.raises(ValueError, match="未知の field"):
        prompt_revise.revise(
            current_prompt="x",
            instruction_ja="変えて",
            field="weird_prompt",
        )


def test_revise_rejects_empty_instruction() -> None:
    with pytest.raises(ValueError, match="instruction_ja"):
        prompt_revise.revise(
            current_prompt="x",
            instruction_ja="   ",
            field="background_prompt",
        )


def test_revise_rejects_when_llm_returns_ui_words(monkeypatch) -> None:
    _mock_anthropic_response(
        "young woman watches a chat bubble appear on her laptop",
        monkeypatch,
    )

    with pytest.raises(ValueError, match="UI 誘発語"):
        prompt_revise.revise(
            current_prompt="x",
            instruction_ja="変えて",
            field="animation_prompt",
        )


def test_revise_no_api_key_raises(monkeypatch) -> None:
    monkeypatch.setattr(prompt_revise.config, "ANTHROPIC_API_KEY", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        prompt_revise.revise(
            current_prompt="x",
            instruction_ja="変えて",
            field="background_prompt",
        )
