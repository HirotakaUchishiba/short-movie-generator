import json
from unittest.mock import MagicMock, patch

import pytest

import video_analyzer


def _stub_stream(body_text: str, input_tokens: int = 100_000,
                 output_tokens: int = 2000) -> MagicMock:
    """anthropic.messages.stream を模す context manager。"""
    final = MagicMock()
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    final.usage = usage

    stream_obj = MagicMock()
    stream_obj.text_stream = iter([body_text])
    stream_obj.get_final_message.return_value = final

    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=stream_obj)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def test_build_screenplay_parses_response(tmp_path) -> None:
    f = tmp_path / "f.jpg"
    f.write_bytes(b"\xff\xd8\xff\xd9")

    body = {
        "caption": "test",
        "audio_mode": "voiced",
        "scenes": [{
            "duration": 5.0,
            "background_prompt": "bg",
            "animation_prompt": "motion",
            "lines": [{"text": "やばい", "start": 0.0, "end": 1.0, "emotion": "驚き"}],
        }],
    }

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stub_stream(json.dumps(body))

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = video_analyzer.build_screenplay(
            frame_paths=[str(f)],
            transcript={"text": "やばい", "segments": [], "words": [], "duration": 1.0},
            phrase_features=[],
            source_video_path="/tmp/ref.mov",
            api_key="fake",
        )

    assert result["caption"] == "test"
    assert result["_analysis"]["source_video"] == "/tmp/ref.mov"
    assert result["_analysis"]["input_tokens"] == 100_000


def test_build_screenplay_strips_code_fence(tmp_path) -> None:
    f = tmp_path / "f.jpg"
    f.write_bytes(b"\xff\xd8\xff\xd9")

    fenced = "```json\n" + json.dumps({"caption": "x", "scenes": []}) + "\n```"
    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stub_stream(fenced)

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = video_analyzer.build_screenplay(
            frame_paths=[str(f)],
            transcript={"text": "", "segments": [], "words": [], "duration": 0},
            phrase_features=[],
            source_video_path="/tmp/x.mov",
            api_key="fake",
        )
    assert result["caption"] == "x"


def test_build_screenplay_raises_on_bad_json(tmp_path) -> None:
    f = tmp_path / "f.jpg"
    f.write_bytes(b"\xff\xd8\xff\xd9")

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stub_stream("not json at all")

    with patch("anthropic.Anthropic", return_value=mock_client):
        with pytest.raises(RuntimeError, match="JSON parse"):
            video_analyzer.build_screenplay(
                frame_paths=[str(f)],
                transcript={"text": "", "segments": [], "words": [], "duration": 0},
                phrase_features=[],
                source_video_path="/tmp/x.mov",
                api_key="fake",
            )


def test_build_screenplay_raises_without_api_key(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    f = tmp_path / "f.jpg"
    f.write_bytes(b"\xff\xd8\xff\xd9")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        video_analyzer.build_screenplay(
            frame_paths=[str(f)],
            transcript={"text": "", "segments": [], "words": [], "duration": 0},
            phrase_features=[],
            source_video_path="/tmp/x.mov",
            api_key=None,
        )
