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
        result, usage = video_analyzer.build_screenplay(
            frame_paths=[str(f)],
            transcript={"text": "やばい", "segments": [], "words": [], "duration": 1.0},
            phrase_features=[],
            source_video_path="/tmp/ref.mov",
            api_key="fake",
        )

    assert result["caption"] == "test"
    assert result["scenes"][0]["duration"] == 5.0
    assert usage == {"input_tokens": 100_000, "output_tokens": 2000}


def test_build_screenplay_strips_code_fence(tmp_path) -> None:
    f = tmp_path / "f.jpg"
    f.write_bytes(b"\xff\xd8\xff\xd9")

    fenced = "```json\n" + json.dumps({"caption": "x", "scenes": []}) + "\n```"
    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stub_stream(fenced)

    with patch("anthropic.Anthropic", return_value=mock_client):
        result, _usage = video_analyzer.build_screenplay(
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
        with pytest.raises(video_analyzer.ScreenplayParseError, match="JSON parse"):
            video_analyzer.build_screenplay(
                frame_paths=[str(f)],
                transcript={"text": "", "segments": [], "words": [], "duration": 0},
                phrase_features=[],
                source_video_path="/tmp/x.mov",
                api_key="fake",
            )


def test_parse_error_carries_usage_for_recording(tmp_path) -> None:
    """parse 失敗時も Claude 課金分の usage を例外に同梱する (= recorder に渡せる)。"""
    f = tmp_path / "f.jpg"
    f.write_bytes(b"\xff\xd8\xff\xd9")

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stub_stream(
        "broken json", input_tokens=12345, output_tokens=678,
    )

    with patch("anthropic.Anthropic", return_value=mock_client):
        with pytest.raises(video_analyzer.ScreenplayParseError) as exc_info:
            video_analyzer.build_screenplay(
                frame_paths=[str(f)],
                transcript={"text": "", "segments": [], "words": [], "duration": 0},
                phrase_features=[],
                source_video_path="/tmp/x.mov",
                api_key="fake",
            )
    assert exc_info.value.usage == {"input_tokens": 12345, "output_tokens": 678}


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


# ───────────── Step 1: intent_catalog wire ─────────────


def _make_catalog():
    """テスト用 visual_intents catalog (= 2 entry の最小集合)。"""
    from analyze.intent_resolver import IntentEntry

    return [
        IntentEntry(
            id="talking_head_calm",
            description="x",
            valid_start_emotions=("中立",),
            duration_buckets=(5, 10),
            motion_intensity_bucket="low",
            compatible_with=(),
        ),
        IntentEntry(
            id="reaction_surprise",
            description="x",
            valid_start_emotions=("驚き",),
            duration_buckets=(5,),
            motion_intensity_bucket="medium",
            compatible_with=(),
        ),
    ]


def _build_with_catalog(tmp_path, body: dict, catalog):
    """build_screenplay を mock claude + 任意 catalog で呼ぶ helper。"""
    f = tmp_path / "f.jpg"
    f.write_bytes(b"\xff\xd8\xff\xd9")
    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stub_stream(json.dumps(body))
    with patch("anthropic.Anthropic", return_value=mock_client):
        return video_analyzer.build_screenplay(
            frame_paths=[str(f)],
            transcript={"text": "", "segments": [], "words": [], "duration": 0},
            phrase_features=[],
            source_video_path="/tmp/x.mov",
            api_key="fake",
            intent_catalog=catalog,
        )


def test_build_screenplay_normalizes_valid_annotation(tmp_path) -> None:
    """catalog にある id + 高 confidence は annotation がそのまま残る。"""
    body = {
        "caption": "x",
        "scenes": [{
            "duration": 5.0,
            "background_prompt": "bg",
            "animation_prompt": "motion",
            "annotation": {
                "visual_intent_id": "talking_head_calm",
                "confidence": 0.95,
                "duration_bucket": 5,
                "motion_intensity": "low",
                "rationale": "subject talks calmly facing camera",
            },
            "lines": [{"text": "やばい", "start": 0.0, "end": 1.0, "emotion": "驚き"}],
        }],
    }
    result, _u = _build_with_catalog(tmp_path, body, _make_catalog())
    ann = result["scenes"][0]["annotation"]
    assert ann["visual_intent_id"] == "talking_head_calm"
    assert ann["duration_bucket"] == 5
    assert ann["motion_intensity"] == "low"
    # rationale / confidence は normalize で drop される (= snapshot に書かない)
    assert "rationale" not in ann
    assert "confidence" not in ann


def test_build_screenplay_demotes_unknown_intent_id(tmp_path) -> None:
    """catalog にない id は drop されるが、他フィールドは残る。"""
    body = {
        "caption": "x",
        "scenes": [{
            "duration": 5.0,
            "background_prompt": "b",
            "animation_prompt": "m",
            "annotation": {
                "visual_intent_id": "ghost_intent",
                "confidence": 0.99,
                "duration_bucket": 10,
                "motion_intensity": "medium",
            },
            "lines": [{"text": "test", "start": 0.0, "end": 1.0, "emotion": "中立"}],
        }],
    }
    result, _u = _build_with_catalog(tmp_path, body, _make_catalog())
    ann = result["scenes"][0]["annotation"]
    assert "visual_intent_id" not in ann
    assert ann == {"duration_bucket": 10, "motion_intensity": "medium"}


def test_build_screenplay_drops_empty_annotation(tmp_path) -> None:
    """すべて drop される annotation は scene から key 自体を削除する。"""
    body = {
        "caption": "x",
        "scenes": [{
            "duration": 5.0,
            "background_prompt": "b",
            "animation_prompt": "m",
            "annotation": {
                "visual_intent_id": "ghost",
                "confidence": 0.1,  # 低 conf
                "duration_bucket": "five",  # 不正型
                "motion_intensity": "extreme",  # enum 外
            },
            "lines": [{"text": "test", "start": 0.0, "end": 1.0, "emotion": "中立"}],
        }],
    }
    result, _u = _build_with_catalog(tmp_path, body, _make_catalog())
    assert "annotation" not in result["scenes"][0]


def test_build_screenplay_skips_normalize_when_catalog_none(tmp_path) -> None:
    """catalog 渡さない (= 旧経路) なら annotation は素通り (= normalize しない)。"""
    body = {
        "caption": "x",
        "scenes": [{
            "duration": 5.0,
            "background_prompt": "b",
            "animation_prompt": "m",
            "annotation": {"visual_intent_id": "anything", "confidence": 0.1},
            "lines": [{"text": "t", "start": 0.0, "end": 1.0, "emotion": "中立"}],
        }],
    }
    f = tmp_path / "f.jpg"
    f.write_bytes(b"\xff\xd8\xff\xd9")
    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stub_stream(json.dumps(body))
    with patch("anthropic.Anthropic", return_value=mock_client):
        result, _u = video_analyzer.build_screenplay(
            frame_paths=[str(f)],
            transcript={"text": "", "segments": [], "words": [], "duration": 0},
            phrase_features=[],
            source_video_path="/tmp/x.mov",
            api_key="fake",
            # intent_catalog 未指定
        )
    # normalize が走らないので生の annotation がそのまま残る
    assert result["scenes"][0]["annotation"] == {
        "visual_intent_id": "anything",
        "confidence": 0.1,
    }


def test_build_screenplay_injects_catalog_into_prompt(tmp_path) -> None:
    """intent_catalog 指定時、Claude への user content に catalog セクションが注入される。"""
    body = {
        "caption": "x",
        "scenes": [{
            "duration": 5.0,
            "background_prompt": "b",
            "animation_prompt": "m",
            "lines": [{"text": "t", "start": 0.0, "end": 1.0, "emotion": "中立"}],
        }],
    }
    f = tmp_path / "f.jpg"
    f.write_bytes(b"\xff\xd8\xff\xd9")
    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stub_stream(json.dumps(body))
    with patch("anthropic.Anthropic", return_value=mock_client):
        video_analyzer.build_screenplay(
            frame_paths=[str(f)],
            transcript={"text": "", "segments": [], "words": [], "duration": 0},
            phrase_features=[],
            source_video_path="/tmp/x.mov",
            api_key="fake",
            intent_catalog=_make_catalog(),
        )
    # mock_client.messages.stream の呼び出し引数から user content を取り出して assert
    call_kwargs = mock_client.messages.stream.call_args.kwargs
    messages = call_kwargs["messages"]
    user_text_blocks = [
        b["text"] for b in messages[0]["content"] if b.get("type") == "text"
    ]
    joined = "\n".join(user_text_blocks)
    assert "利用可能な visual intent 集合" in joined
    assert "talking_head_calm" in joined
    assert "reaction_surprise" in joined
