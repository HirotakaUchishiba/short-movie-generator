import json
from unittest.mock import MagicMock, patch

import pytest

from analytics import auto_tag


def _mock_response(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def _sample_screenplay() -> dict:
    return {
        "caption": "転職のリアル",
        "title_overlay": "ITエンジニア",
        "audio_mode": "voiced",
        "scenes": [{
            "time": "9:00",
            "label": "始業",
            "duration": 5,
            "lines": [{"text": "やばい", "emotion": "驚き"}],
        }],
    }


def test_classify_screenplay_parses_tags() -> None:
    tags = {
        "hook_type": "timeline",
        "tone": "casual",
        "dominant_emotion": "喜び",
        "theme": "career_change",
        "character_archetype": "若い女性エンジニア",
    }
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_response(json.dumps(tags))
    with patch("anthropic.Anthropic", return_value=mock_client):
        result = auto_tag.classify_screenplay(_sample_screenplay(), api_key="fake")
    assert result == tags


def test_classify_screenplay_strips_code_fence() -> None:
    tags = {"hook_type": "reveal", "tone": "informative",
            "dominant_emotion": "中立", "theme": "skills",
            "character_archetype": "解説者"}
    fenced = "```json\n" + json.dumps(tags) + "\n```"
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_response(fenced)
    with patch("anthropic.Anthropic", return_value=mock_client):
        result = auto_tag.classify_screenplay(_sample_screenplay(), api_key="fake")
    assert result["hook_type"] == "reveal"


def test_classify_screenplay_raises_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        auto_tag.classify_screenplay(_sample_screenplay(), api_key=None)
