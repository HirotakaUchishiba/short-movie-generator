from unittest.mock import MagicMock, patch

import pytest

import whisper_client


def test_transcribe_falls_back_to_local_when_no_api_key(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")

    fake_local = MagicMock(return_value={"text": "local", "segments": [], "words": [], "duration": 1.0})
    monkeypatch.setattr(whisper_client, "_transcribe_local", fake_local)

    result = whisper_client.transcribe(str(audio), api_key=None)
    assert result["text"] == "local"
    fake_local.assert_called_once()


def test_transcribe_local_raises_without_faster_whisper(monkeypatch, tmp_path) -> None:
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    import builtins
    real_import = builtins.__import__

    def block_faster_whisper(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_faster_whisper)
    with pytest.raises(whisper_client.WhisperClientError, match="faster-whisper"):
        whisper_client._transcribe_local(str(audio), "ja", "tiny")


def test_transcribe_raises_when_file_missing() -> None:
    with pytest.raises(whisper_client.WhisperClientError):
        whisper_client.transcribe("/nonexistent.wav", api_key="fake")


def test_transcribe_parses_response(monkeypatch, tmp_path) -> None:
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")

    mock_response = MagicMock()
    mock_response.text = "8時50分"
    mock_response.duration = 2.5
    mock_response.segments = [
        MagicMock(start=0.1, end=2.3, text=" 8時50分 "),
    ]
    mock_response.words = [
        MagicMock(start=0.1, end=0.9, word="8時"),
        MagicMock(start=1.0, end=2.3, word="50分"),
    ]

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = mock_response

    with patch("openai.OpenAI", return_value=mock_client):
        result = whisper_client.transcribe(str(audio), api_key="fake")

    assert result["text"] == "8時50分"
    assert result["duration"] == 2.5
    assert len(result["segments"]) == 1
    assert result["segments"][0]["text"] == "8時50分"
    assert len(result["words"]) == 2
    assert result["words"][0]["word"] == "8時"
