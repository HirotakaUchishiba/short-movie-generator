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
    """catalog にある id + 全 field valid は annotation がそのまま残る。"""
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
    """catalog にない id は visual_intent_id のみ None になり、他フィールドは残る。"""
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
    # 未知 id は None に降格、annotation 自体は残る
    assert ann == {
        "visual_intent_id": None,
        "duration_bucket": 10,
        "motion_intensity": "medium",
    }


def test_build_screenplay_keeps_annotation_for_low_confidence(tmp_path) -> None:
    """Phase 4: 低 confidence でも annotation は drop されず、id もそのまま残る。"""
    body = {
        "caption": "x",
        "scenes": [{
            "duration": 5.0,
            "background_prompt": "b",
            "animation_prompt": "m",
            "annotation": {
                "visual_intent_id": "talking_head_calm",
                "confidence": 0.1,  # 低 conf
                "duration_bucket": 5,
                "motion_intensity": "low",
            },
            "lines": [{"text": "test", "start": 0.0, "end": 1.0, "emotion": "中立"}],
        }],
    }
    result, _u = _build_with_catalog(tmp_path, body, _make_catalog())
    ann = result["scenes"][0]["annotation"]
    # 低 confidence でも visual_intent_id を維持する
    assert ann == {
        "visual_intent_id": "talking_head_calm",
        "duration_bucket": 5,
        "motion_intensity": "low",
    }


def test_build_screenplay_partial_invalid_keeps_annotation(tmp_path) -> None:
    """個別 field invalid は当該 field のみ None。annotation 全体は残る。"""
    body = {
        "caption": "x",
        "scenes": [{
            "duration": 5.0,
            "background_prompt": "b",
            "animation_prompt": "m",
            "annotation": {
                "visual_intent_id": "talking_head_calm",
                "duration_bucket": "five",  # 不正型
                "motion_intensity": "extreme",  # enum 外
            },
            "lines": [{"text": "test", "start": 0.0, "end": 1.0, "emotion": "中立"}],
        }],
    }
    result, _u = _build_with_catalog(tmp_path, body, _make_catalog())
    ann = result["scenes"][0]["annotation"]
    assert ann == {
        "visual_intent_id": "talking_head_calm",
        "duration_bucket": None,
        "motion_intensity": None,
    }


def test_build_screenplay_drops_empty_annotation(tmp_path) -> None:
    """すべて invalid (全 field None) のときのみ scene から annotation key を削除。"""
    body = {
        "caption": "x",
        "scenes": [{
            "duration": 5.0,
            "background_prompt": "b",
            "animation_prompt": "m",
            "annotation": {
                "visual_intent_id": "ghost",
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


# ───────────── location_catalog wire (= analyze location 自動選定) ─────────────


def _make_location_catalog():
    """テスト用 location catalog (= 2 entry の最小集合)。"""
    return [
        {"id": "home_office", "decor": "北欧風オフィス", "lighting": "自然光",
         "color_palette": "白基調", "props": "MacBook", "camera_distance": "medium-close"},
        {"id": "warm_cafe", "decor": "暖色カフェ", "lighting": "間接照明",
         "color_palette": "ブラウン", "props": "マグカップ", "camera_distance": "medium"},
    ]


def _build_with_location_catalog(tmp_path, body: dict, catalog):
    """build_screenplay を mock claude + location_catalog で呼ぶ helper。"""
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
            location_catalog=catalog,
        )


def test_build_screenplay_injects_location_catalog_into_prompt(tmp_path) -> None:
    """location_catalog 指定時、user content に location 集合セクションが注入される。"""
    body = {
        "caption": "x",
        "scenes": [{
            "location_ref": "home_office", "camera_distance": "medium-close",
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
            location_catalog=_make_location_catalog(),
        )
    call_kwargs = mock_client.messages.stream.call_args.kwargs
    user_text_blocks = [
        b["text"] for b in call_kwargs["messages"][0]["content"]
        if b.get("type") == "text"
    ]
    joined = "\n".join(user_text_blocks)
    assert "利用可能な location 集合" in joined
    assert "home_office" in joined
    assert "warm_cafe" in joined


def test_build_screenplay_keeps_valid_location(tmp_path) -> None:
    """catalog にある location_ref + enum 内 camera_distance はそのまま残る。"""
    body = {
        "caption": "x",
        "scenes": [{
            "location_ref": "warm_cafe", "camera_distance": "medium",
            "lines": [{"text": "t", "start": 0.0, "end": 1.0, "emotion": "中立"}],
        }],
    }
    result, _u = _build_with_location_catalog(
        tmp_path, body, _make_location_catalog(),
    )
    scene = result["scenes"][0]
    assert scene["location_ref"] == "warm_cafe"
    assert scene["camera_distance"] == "medium"


def test_build_screenplay_corrects_unknown_location_ref(tmp_path) -> None:
    """catalog に無い location_ref は catalog 先頭 (= 最近傍) に矯正される。"""
    body = {
        "caption": "x",
        "scenes": [{
            "location_ref": "nonexistent_loc", "camera_distance": "medium",
            "lines": [{"text": "t", "start": 0.0, "end": 1.0, "emotion": "中立"}],
        }],
    }
    result, _u = _build_with_location_catalog(
        tmp_path, body, _make_location_catalog(),
    )
    # catalog 先頭 = home_office に矯正
    assert result["scenes"][0]["location_ref"] == "home_office"


def test_build_screenplay_corrects_missing_location_ref(tmp_path) -> None:
    """location_ref が欠落していても catalog 先頭に矯正される (= compose fail-fast 防止)。"""
    body = {
        "caption": "x",
        "scenes": [{
            "lines": [{"text": "t", "start": 0.0, "end": 1.0, "emotion": "中立"}],
        }],
    }
    result, _u = _build_with_location_catalog(
        tmp_path, body, _make_location_catalog(),
    )
    assert result["scenes"][0]["location_ref"] == "home_office"


def test_build_screenplay_drops_invalid_camera_distance(tmp_path) -> None:
    """enum 外の camera_distance は drop される (= _derive_identity の fallback に委ねる)。"""
    body = {
        "caption": "x",
        "scenes": [{
            "location_ref": "home_office", "camera_distance": "extreme-zoom",
            "lines": [{"text": "t", "start": 0.0, "end": 1.0, "emotion": "中立"}],
        }],
    }
    result, _u = _build_with_location_catalog(
        tmp_path, body, _make_location_catalog(),
    )
    assert "camera_distance" not in result["scenes"][0]


def test_build_screenplay_skips_location_normalize_when_catalog_none(tmp_path) -> None:
    """location_catalog 渡さない (= 旧経路) なら location 正規化は走らない。"""
    body = {
        "caption": "x",
        "scenes": [{
            "duration": 5.0,
            "background_prompt": "b",
            "animation_prompt": "m",
            "location_ref": "anything_goes",
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
            # location_catalog 未指定
        )
    # 正規化が走らないので生の location_ref がそのまま残る
    assert result["scenes"][0]["location_ref"] == "anything_goes"


# ───────────── character_catalog wire (= analyze casting 提案) ─────────────


def _make_character_catalog():
    """テスト用 character catalog (= 2 base の最小集合)。"""
    return [
        {"id": "f1", "appearance": {"gender": "female", "age_range": "20s"},
         "refs": ["f1", "f1__office"]},
        {"id": "m1", "appearance": {"gender": "male"},
         "refs": ["m1", "m1__suit"]},
    ]


def _build_with_character_catalog(tmp_path, body: dict, catalog):
    """build_screenplay を mock claude + character_catalog で呼ぶ helper。"""
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
            character_catalog=catalog,
        )


def test_build_screenplay_injects_character_catalog_into_prompt(tmp_path) -> None:
    """character_catalog 指定時、user content に character 集合セクションが注入される。"""
    body = {"caption": "x", "scenes": [{"lines": [
        {"text": "t", "start": 0.0, "end": 1.0, "emotion": "中立"}]}]}
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
            character_catalog=_make_character_catalog(),
        )
    call_kwargs = mock_client.messages.stream.call_args.kwargs
    user_text_blocks = [
        b["text"] for b in call_kwargs["messages"][0]["content"]
        if b.get("type") == "text"
    ]
    joined = "\n".join(user_text_blocks)
    assert "利用可能な character 集合" in joined
    assert "f1__office" in joined
    assert "m1__suit" in joined


def test_build_screenplay_passes_speaker_profiles_through(tmp_path) -> None:
    """speaker_profiles はそのまま素通しされる。"""
    body = {
        "caption": "x",
        "speaker_profiles": {
            "speaker_1": {"gender": "female", "age_range": "20s",
                          "description": "明るく早口"},
        },
        "scenes": [{"lines": [
            {"text": "t", "start": 0.0, "end": 1.0, "emotion": "中立",
             "speaker": "speaker_1"}]}],
    }
    result, _u = _build_with_character_catalog(
        tmp_path, body, _make_character_catalog())
    assert result["speaker_profiles"]["speaker_1"]["gender"] == "female"


def test_build_screenplay_keeps_valid_casting(tmp_path) -> None:
    """catalog の refs に在る featured_characters / speaker_to_ref は残る。"""
    body = {
        "caption": "x",
        "featured_characters": ["f1__office"],
        "speaker_to_ref": {"speaker_1": "f1__office"},
        "scenes": [{"lines": [
            {"text": "t", "start": 0.0, "end": 1.0, "emotion": "中立",
             "speaker": "speaker_1"}]}],
    }
    result, _u = _build_with_character_catalog(
        tmp_path, body, _make_character_catalog())
    assert result["speaker_to_ref"] == {"speaker_1": "f1__office"}
    assert result["featured_characters"] == ["f1__office"]


def test_build_screenplay_drops_unknown_casting_refs(tmp_path) -> None:
    """catalog の refs に無い ref は drop され、未マッチ speaker は省略される。"""
    body = {
        "caption": "x",
        "featured_characters": ["f1__office", "ghost__nope"],
        "speaker_to_ref": {"speaker_1": "f1__office", "speaker_2": "ghost__nope"},
        "scenes": [{"lines": [
            {"text": "t", "start": 0.0, "end": 1.0, "emotion": "中立",
             "speaker": "speaker_1"}]}],
    }
    result, _u = _build_with_character_catalog(
        tmp_path, body, _make_character_catalog())
    assert result["speaker_to_ref"] == {"speaker_1": "f1__office"}
    assert result["featured_characters"] == ["f1__office"]


def test_build_screenplay_unions_featured_with_speaker_to_ref(tmp_path) -> None:
    """featured_characters は speaker_to_ref の値との和集合 (順序維持) になる。"""
    body = {
        "caption": "x",
        "featured_characters": ["f1__office"],
        "speaker_to_ref": {"speaker_1": "f1__office", "speaker_2": "m1__suit"},
        "scenes": [{"lines": [
            {"text": "t", "start": 0.0, "end": 1.0, "emotion": "中立",
             "speaker": "speaker_1"}]}],
    }
    result, _u = _build_with_character_catalog(
        tmp_path, body, _make_character_catalog())
    # m1__suit は speaker_to_ref にしか無いが featured にも入る
    assert result["featured_characters"] == ["f1__office", "m1__suit"]


def test_build_screenplay_drops_empty_casting(tmp_path) -> None:
    """全 ref が invalid なら featured_characters / speaker_to_ref キーごと消える。"""
    body = {
        "caption": "x",
        "featured_characters": ["ghost__a"],
        "speaker_to_ref": {"speaker_1": "ghost__b"},
        "scenes": [{"lines": [
            {"text": "t", "start": 0.0, "end": 1.0, "emotion": "中立"}]}],
    }
    result, _u = _build_with_character_catalog(
        tmp_path, body, _make_character_catalog())
    assert "speaker_to_ref" not in result
    assert "featured_characters" not in result


def test_build_screenplay_skips_casting_normalize_when_catalog_none(tmp_path) -> None:
    """character_catalog 渡さない (= 旧経路) なら casting 正規化は走らない。"""
    body = {
        "caption": "x",
        "featured_characters": ["anything_goes"],
        "speaker_to_ref": {"speaker_1": "whatever"},
        "scenes": [{
            "background_prompt": "b", "animation_prompt": "m",
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
            # character_catalog 未指定
        )
    # 正規化が走らないので生の値がそのまま残る
    assert result["featured_characters"] == ["anything_goes"]
    assert result["speaker_to_ref"] == {"speaker_1": "whatever"}


# ───────────── Rule A (wardrobe-by-location) / Rule B (distinct base) ─────────────


def _make_location_catalog_with_wardrobes():
    """テスト用 location catalog (= recommended_wardrobes 付き)。"""
    return [
        {"id": "home_office", "recommended_wardrobes": ["office"]},
        {"id": "warm_cafe", "recommended_wardrobes": ["casual"]},
        {"id": "soft_gradient"},  # recommended_wardrobes 無し
    ]


def _make_character_catalog_multi_wardrobe():
    """3 wardrobes × 2 base の catalog。"""
    return [
        {"id": "f1", "appearance": {"gender": "female"},
         "refs": ["f1", "f1__office", "f1__casual", "f1__loungewear"]},
        {"id": "m1", "appearance": {"gender": "male"},
         "refs": ["m1", "m1__office", "m1__casual"]},
    ]


def _build_with_both_catalogs(tmp_path, body, char_cat, loc_cat):
    """build_screenplay を mock claude + character + location catalog で呼ぶ。"""
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
            character_catalog=char_cat,
            location_catalog=loc_cat,
        )


def test_rule_b_drops_duplicate_base(tmp_path) -> None:
    """同じ base が複数 speaker にマッピングされていれば 2 件目以降は drop。"""
    body = {
        "caption": "x",
        "featured_characters": ["f1__office", "f1__casual"],
        "speaker_to_ref": {"speaker_1": "f1__office", "speaker_2": "f1__casual"},
        "scenes": [{"location_ref": "home_office", "lines": [
            {"text": "a", "start": 0, "end": 1, "emotion": "中立", "speaker": "speaker_1"},
            {"text": "b", "start": 1, "end": 2, "emotion": "中立", "speaker": "speaker_2"},
        ]}],
    }
    result, _u = _build_with_both_catalogs(
        tmp_path, body, _make_character_catalog_multi_wardrobe(),
        _make_location_catalog_with_wardrobes())
    # speaker_2 (= 2 件目の f1) は drop
    assert result["speaker_to_ref"] == {"speaker_1": "f1__office"}
    # featured も同 base 重複が排除される (= cleaned_s2r 優先)
    assert result["featured_characters"] == ["f1__office"]


def test_rule_a_swaps_wardrobe_to_match_dominant_location(tmp_path) -> None:
    """speaker が主に登場するシーンの location の recommended_wardrobes に
    合うように wardrobe が swap される。"""
    body = {
        "caption": "x",
        "speaker_to_ref": {"speaker_1": "f1__casual"},  # Claude は casual を選んだ
        "scenes": [
            {"location_ref": "home_office", "lines": [
                {"text": "a", "start": 0, "end": 1, "emotion": "中立", "speaker": "speaker_1"},
                {"text": "b", "start": 1, "end": 2, "emotion": "中立", "speaker": "speaker_1"},
            ]},
        ],
    }
    result, _u = _build_with_both_catalogs(
        tmp_path, body, _make_character_catalog_multi_wardrobe(),
        _make_location_catalog_with_wardrobes())
    # home_office (= recommended ["office"]) に合わせて casual → office に swap
    assert result["speaker_to_ref"] == {"speaker_1": "f1__office"}
    assert result["featured_characters"] == ["f1__office"]


def test_rule_a_keeps_wardrobe_when_already_matching(tmp_path) -> None:
    """wardrobe が既に recommended_wardrobes に含まれていれば swap しない。"""
    body = {
        "caption": "x",
        "speaker_to_ref": {"speaker_1": "f1__office"},
        "scenes": [{"location_ref": "home_office", "lines": [
            {"text": "a", "start": 0, "end": 1, "emotion": "中立", "speaker": "speaker_1"},
        ]}],
    }
    result, _u = _build_with_both_catalogs(
        tmp_path, body, _make_character_catalog_multi_wardrobe(),
        _make_location_catalog_with_wardrobes())
    assert result["speaker_to_ref"] == {"speaker_1": "f1__office"}


def test_rule_a_keeps_when_no_recommended_wardrobes(tmp_path) -> None:
    """location に recommended_wardrobes が無ければ swap しない (graceful)。"""
    body = {
        "caption": "x",
        "speaker_to_ref": {"speaker_1": "f1__casual"},
        "scenes": [{"location_ref": "soft_gradient", "lines": [
            {"text": "a", "start": 0, "end": 1, "emotion": "中立", "speaker": "speaker_1"},
        ]}],
    }
    result, _u = _build_with_both_catalogs(
        tmp_path, body, _make_character_catalog_multi_wardrobe(),
        _make_location_catalog_with_wardrobes())
    # soft_gradient は recommended なし → Claude の選択を尊重
    assert result["speaker_to_ref"] == {"speaker_1": "f1__casual"}


def test_rule_a_keeps_when_no_matching_variant(tmp_path) -> None:
    """character に適合 wardrobe バリアントが無ければ swap しない (graceful)。"""
    body = {
        "caption": "x",
        # m1 は loungewear バリアントを持たない (catalog で m1 の refs は
        # ["m1", "m1__office", "m1__casual"] のみ)
        "speaker_to_ref": {"speaker_1": "m1__casual"},
        "scenes": [{"location_ref": "cozy_living", "lines": [
            {"text": "a", "start": 0, "end": 1, "emotion": "中立", "speaker": "speaker_1"},
        ]}],
    }
    # cozy_living で loungewear を推奨するが m1 には無い → swap せず keep
    loc_cat = [{"id": "cozy_living", "recommended_wardrobes": ["loungewear"]}]
    result, _u = _build_with_both_catalogs(
        tmp_path, body, _make_character_catalog_multi_wardrobe(), loc_cat)
    assert result["speaker_to_ref"] == {"speaker_1": "m1__casual"}


def test_rule_a_picks_dominant_location_by_line_count(tmp_path) -> None:
    """speaker が複数 location に出現するとき、line 数が多い location を dominant とする。"""
    body = {
        "caption": "x",
        "speaker_to_ref": {"speaker_1": "f1__casual"},
        "scenes": [
            # cafe で 1 line
            {"location_ref": "warm_cafe", "lines": [
                {"text": "a", "start": 0, "end": 1, "emotion": "中立", "speaker": "speaker_1"},
            ]},
            # office で 3 line → dominant
            {"location_ref": "home_office", "lines": [
                {"text": "b", "start": 0, "end": 1, "emotion": "中立", "speaker": "speaker_1"},
                {"text": "c", "start": 1, "end": 2, "emotion": "中立", "speaker": "speaker_1"},
                {"text": "d", "start": 2, "end": 3, "emotion": "中立", "speaker": "speaker_1"},
            ]},
        ],
    }
    result, _u = _build_with_both_catalogs(
        tmp_path, body, _make_character_catalog_multi_wardrobe(),
        _make_location_catalog_with_wardrobes())
    # home_office (= dominant、recommended ["office"]) に合わせて casual → office
    assert result["speaker_to_ref"] == {"speaker_1": "f1__office"}


def test_rule_a_skipped_when_location_catalog_none(tmp_path) -> None:
    """location_catalog 未指定なら Rule A はスキップ (= Claude の選択を尊重)。"""
    body = {
        "caption": "x",
        "speaker_to_ref": {"speaker_1": "f1__casual"},
        "scenes": [{"location_ref": "home_office", "lines": [
            {"text": "a", "start": 0, "end": 1, "emotion": "中立", "speaker": "speaker_1"},
        ]}],
    }
    # character_catalog のみ (location_catalog なし)
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
            character_catalog=_make_character_catalog_multi_wardrobe(),
            # location_catalog 未指定
        )
    # swap せずそのまま
    assert result["speaker_to_ref"] == {"speaker_1": "f1__casual"}


def test_featured_prefers_s2r_swapped_wardrobe(tmp_path) -> None:
    """Rule A が wardrobe を swap した場合、featured_characters も同 base の
    新しい ref に同期する (= 旧 ref が featured に残らない)。"""
    body = {
        "caption": "x",
        # featured と s2r の両方が casual。Rule A で s2r が office に swap される
        "featured_characters": ["f1__casual"],
        "speaker_to_ref": {"speaker_1": "f1__casual"},
        "scenes": [{"location_ref": "home_office", "lines": [
            {"text": "a", "start": 0, "end": 1, "emotion": "中立", "speaker": "speaker_1"},
        ]}],
    }
    result, _u = _build_with_both_catalogs(
        tmp_path, body, _make_character_catalog_multi_wardrobe(),
        _make_location_catalog_with_wardrobes())
    # featured には swap 後の office のみ (= raw_feat の casual は同 base で skip)
    assert result["featured_characters"] == ["f1__office"]
    assert result["speaker_to_ref"] == {"speaker_1": "f1__office"}


# ───── Phase D: unmapped speaker fallback (= _fill_unmapped_speakers) ─────
# Claude が確信を持てず speaker_to_ref を埋め残しても、speaker_profiles に
# 載っている全 speaker が必ず resolved ref を持つ状態に補完されることを保証


class TestFillUnmappedSpeakers:
    """`_fill_unmapped_speakers` の単体テスト。

    2026-05-17 方針変更 (= `docs/plannings/2026-05-17_decouple-casting-from-reference.md`):
    appearance 突合を撤廃し、catalog の alphabetical 順で割当てる。
    """

    def _catalog(self):
        """3 base の catalog。appearance は dead field 化したので保持されているか
        否かは問わない (= 後続 PR で削除予定)。"""
        return [
            {"id": "f1", "refs": ["f1", "f1__office"]},
            {"id": "f2", "refs": ["f2", "f2__office"]},
            {"id": "m1", "refs": ["m1", "m1__suit"]},
        ]

    def test_assigns_in_alphabetical_order(self) -> None:
        """unmapped speaker は catalog alphabetical 先頭から順に割当てられる。"""
        out = video_analyzer._fill_unmapped_speakers(
            speaker_profiles={
                "speaker_1": {"gender": "male"},
                "speaker_2": {"gender": "female"},
            },
            cleaned_s2r={},
            character_catalog=self._catalog(),
            base_to_refs={"f1": ["f1"], "f2": ["f2"], "m1": ["m1"]},
            loc_to_wardrobes={},
            speaker_to_locs={},
        )
        # 元動画の gender に寄せない → catalog 順 (f1, f2, m1, ...) で割当
        # speaker_1 → f1、speaker_2 → f2
        assert out == {"speaker_1": "f1", "speaker_2": "f2"}

    def test_distinct_character_rule_when_filling(self) -> None:
        """既に Claude が割り当てた base は fill 候補から除外される (= distinct rule)。"""
        out = video_analyzer._fill_unmapped_speakers(
            speaker_profiles={
                "speaker_1": {},
                "speaker_2": {},
            },
            cleaned_s2r={"speaker_1": "f1"},  # Claude が f1 を確定済み
            character_catalog=self._catalog(),
            base_to_refs={"f1": ["f1"], "f2": ["f2"], "m1": ["m1"]},
            loc_to_wardrobes={},
            speaker_to_locs={},
        )
        # speaker_2 は f1 が使用済みなので f2 (= alphabetical 次)
        assert out == {"speaker_1": "f1", "speaker_2": "f2"}

    def test_relaxes_distinct_rule_when_catalog_exhausted(self) -> None:
        """catalog 全 base 使用済みなら distinct rule を緩めて alphabetical 先頭から再利用。"""
        out = video_analyzer._fill_unmapped_speakers(
            speaker_profiles={
                "speaker_1": {}, "speaker_2": {}, "speaker_3": {},
                "speaker_4": {},  # 4 人 vs catalog 3 base
            },
            cleaned_s2r={},
            character_catalog=self._catalog(),
            base_to_refs={"f1": ["f1"], "f2": ["f2"], "m1": ["m1"]},
            loc_to_wardrobes={},
            speaker_to_locs={},
        )
        # f1, f2, m1 を順番に割当 → 4 人目は alphabetical 先頭の f1 を再利用
        assert out["speaker_1"] == "f1"
        assert out["speaker_2"] == "f2"
        assert out["speaker_3"] == "m1"
        assert out["speaker_4"] == "f1"  # 再利用

    def test_ignores_speaker_profile_gender(self) -> None:
        """speaker_profile の gender / age は補完判定に **影響しない**
        (= 元動画に寄せない方針)。"""
        out = video_analyzer._fill_unmapped_speakers(
            # speaker_1 は male profile だが、catalog 順で f1 が割当てられる
            speaker_profiles={"speaker_1": {"gender": "male", "age_range": "30s"}},
            cleaned_s2r={},
            character_catalog=self._catalog(),
            base_to_refs={"f1": ["f1"], "f2": ["f2"], "m1": ["m1"]},
            loc_to_wardrobes={},
            speaker_to_locs={},
        )
        # gender hard reject が撤廃されたので male profile でも f1 が選ばれる
        # (= Stage 1 UI で人間が選び直す前提)
        assert out == {"speaker_1": "f1"}

    def test_no_profile_picks_alphabetical_first(self) -> None:
        """speaker_profile が空でも catalog alphabetical 先頭が選ばれる。"""
        out = video_analyzer._fill_unmapped_speakers(
            speaker_profiles={"speaker_1": {}},
            cleaned_s2r={},
            character_catalog=self._catalog(),
            base_to_refs={"f1": ["f1"], "f2": ["f2"], "m1": ["m1"]},
            loc_to_wardrobes={},
            speaker_to_locs={},
        )
        assert out == {"speaker_1": "f1"}

    def test_wardrobe_aware_pick_with_dominant_location(self) -> None:
        """補完時の wardrobe は dominant location の recommended_wardrobes を優先
        (= location 依存ルールは維持)。"""
        out = video_analyzer._fill_unmapped_speakers(
            speaker_profiles={"speaker_1": {}},
            cleaned_s2r={},
            character_catalog=[
                {"id": "f1", "refs": ["f1", "f1__office", "f1__casual"]},
            ],
            base_to_refs={"f1": ["f1", "f1__office", "f1__casual"]},
            loc_to_wardrobes={"warm_cafe": ["casual"]},
            speaker_to_locs={"speaker_1": ["warm_cafe", "warm_cafe"]},
        )
        # dominant=warm_cafe → casual wardrobe → f1__casual
        assert out == {"speaker_1": "f1__casual"}

    def test_keeps_existing_mapping_untouched(self) -> None:
        """既存の cleaned_s2r エントリは fall-through で温存される。"""
        out = video_analyzer._fill_unmapped_speakers(
            speaker_profiles={"speaker_1": {}, "speaker_2": {}},
            cleaned_s2r={"speaker_1": "f1__office"},  # 既存
            character_catalog=self._catalog(),
            base_to_refs={"f1": ["f1", "f1__office"],
                          "f2": ["f2"], "m1": ["m1", "m1__suit"]},
            loc_to_wardrobes={},
            speaker_to_locs={},
        )
        # speaker_1 は触らない、speaker_2 は f1 が使用済みなので f2 (alphabetical 次)
        assert out["speaker_1"] == "f1__office"
        assert out["speaker_2"] == "f2"

    def test_empty_catalog_returns_input_as_is(self) -> None:
        """catalog が空なら fill 不能で input をそのまま返す。"""
        out = video_analyzer._fill_unmapped_speakers(
            speaker_profiles={"speaker_1": {}},
            cleaned_s2r={},
            character_catalog=[],
            base_to_refs={},
            loc_to_wardrobes={},
            speaker_to_locs={},
        )
        assert out == {}

    def test_empty_speaker_profiles_returns_input_as_is(self) -> None:
        """speaker_profiles が空ならそのまま返す。"""
        out = video_analyzer._fill_unmapped_speakers(
            speaker_profiles={},
            cleaned_s2r={"speaker_1": "f1"},
            character_catalog=self._catalog(),
            base_to_refs={"f1": ["f1"]},
            loc_to_wardrobes={},
            speaker_to_locs={},
        )
        assert out == {"speaker_1": "f1"}


class TestBuildScreenplayFillsAllSpeakers:
    """build_screenplay の end-to-end: Claude が埋め残しても全 speaker が
    speaker_to_ref に登場することを保証する。
    """

    def test_unmapped_speaker_gets_filled_by_post_process(self, tmp_path) -> None:
        """Claude が speaker_1 のみ提案 → speaker_2 は post-process で補完。"""
        body = {
            "caption": "x",
            "speaker_profiles": {
                "speaker_1": {"gender": "female"},
                "speaker_2": {"gender": "male"},
            },
            "featured_characters": ["f1__office"],
            "speaker_to_ref": {"speaker_1": "f1__office"},  # speaker_2 は欠落
            "scenes": [{"lines": [
                {"text": "t", "start": 0.0, "end": 1.0, "emotion": "中立",
                 "speaker": "speaker_1"},
                {"text": "u", "start": 1.0, "end": 2.0, "emotion": "中立",
                 "speaker": "speaker_2"},
            ]}],
        }
        result, _u = _build_with_character_catalog(
            tmp_path, body, _make_character_catalog())
        # 両 speaker が必ず埋まる
        assert "speaker_1" in result["speaker_to_ref"]
        assert "speaker_2" in result["speaker_to_ref"]
        assert result["speaker_to_ref"]["speaker_1"] == "f1__office"
        # speaker_2 は male 一致の m1 base から選ばれる (resolved は m1 or m1__suit)
        assert result["speaker_to_ref"]["speaker_2"].startswith("m1")

    def test_all_speakers_unmapped_get_filled(self, tmp_path) -> None:
        """Claude が speaker_to_ref を完全に省略しても全 speaker が補完される。"""
        body = {
            "caption": "x",
            "speaker_profiles": {
                "speaker_1": {"gender": "female"},
                "speaker_2": {"gender": "male"},
            },
            # speaker_to_ref / featured_characters なし (= Claude が確信無し)
            "scenes": [{"lines": [
                {"text": "t", "start": 0.0, "end": 1.0, "emotion": "中立",
                 "speaker": "speaker_1"},
                {"text": "u", "start": 1.0, "end": 2.0, "emotion": "中立",
                 "speaker": "speaker_2"},
            ]}],
        }
        result, _u = _build_with_character_catalog(
            tmp_path, body, _make_character_catalog())
        s2r = result["speaker_to_ref"]
        assert "speaker_1" in s2r
        assert "speaker_2" in s2r
        # distinct rule で別 base が選ばれる
        assert s2r["speaker_1"].split("__")[0] != s2r["speaker_2"].split("__")[0]

    def test_unmapped_speaker_propagates_to_featured_characters(self, tmp_path) -> None:
        """補完された speaker の ref は featured_characters にも入る。"""
        body = {
            "caption": "x",
            "speaker_profiles": {
                "speaker_1": {"gender": "female"},
                "speaker_2": {"gender": "male"},
            },
            "speaker_to_ref": {"speaker_1": "f1__office"},
            "scenes": [{"lines": [
                {"text": "t", "start": 0.0, "end": 1.0, "emotion": "中立",
                 "speaker": "speaker_1"},
                {"text": "u", "start": 1.0, "end": 2.0, "emotion": "中立",
                 "speaker": "speaker_2"},
            ]}],
        }
        result, _u = _build_with_character_catalog(
            tmp_path, body, _make_character_catalog())
        # speaker_2 用に補完された ref も featured に含まれる
        feat = result["featured_characters"]
        assert "f1__office" in feat
        s2_ref = result["speaker_to_ref"]["speaker_2"]
        assert s2_ref in feat


# ───── speaker_profiles ↔ line.speaker 整合性 (= post-process backfill) ─────
# 2026-05-17 PR #205 で発見した bug: Claude が speaker_profiles を出す一方で
# 全 line.speaker を null にする inconsistent ケースがある。post-process が
# 1 speaker の場合は backfill する。


class TestSpeakerBackfillIntegrity:
    """speaker_profiles と line.speaker の整合性を post-process で回復。"""

    def test_backfills_single_speaker_when_line_speaker_missing(
        self, tmp_path,
    ) -> None:
        """profiles=1 speaker かつ line.speaker 全 null → backfill される。"""
        body = {
            "caption": "x",
            "speaker_profiles": {
                "speaker_1": {"gender": "male", "age_range": "30s"},
            },
            "scenes": [{"lines": [
                {"text": "a", "start": 0.0, "end": 1.0, "emotion": "中立"},
                {"text": "b", "start": 1.0, "end": 2.0, "emotion": "中立"},
            ]}, {"lines": [
                {"text": "c", "start": 0.0, "end": 1.0, "emotion": "中立"},
            ]}],
        }
        result, _u = _build_with_character_catalog(
            tmp_path, body, _make_character_catalog())
        # 全 3 lines に speaker_1 が backfill されている
        speakers = [
            line.get("speaker") for sc in result["scenes"]
            for line in sc.get("lines", [])
        ]
        assert speakers == ["speaker_1", "speaker_1", "speaker_1"]

    def test_does_not_overwrite_existing_line_speaker(
        self, tmp_path,
    ) -> None:
        """既に line.speaker が一部設定されていれば backfill しない (= no-op)。"""
        body = {
            "caption": "x",
            "speaker_profiles": {
                "speaker_1": {"gender": "male"},
            },
            "scenes": [{"lines": [
                {"text": "a", "start": 0.0, "end": 1.0, "emotion": "中立",
                 "speaker": "speaker_1"},
                {"text": "b", "start": 1.0, "end": 2.0, "emotion": "中立"},
            ]}],
        }
        result, _u = _build_with_character_catalog(
            tmp_path, body, _make_character_catalog())
        # 1 line に speaker 設定済みなので backfill しない (= 既存値維持、
        # 残りは null のまま、Stage 1 で人間が直す)
        speakers = [
            line.get("speaker") for sc in result["scenes"]
            for line in sc.get("lines", [])
        ]
        assert speakers == ["speaker_1", None]

    def test_does_not_backfill_when_multiple_speakers(
        self, tmp_path, caplog,
    ) -> None:
        """profiles=2+ speakers で line.speaker 全 null → ambiguous なので
        backfill しない (= warn ログのみ)。"""
        body = {
            "caption": "x",
            "speaker_profiles": {
                "speaker_1": {"gender": "male"},
                "speaker_2": {"gender": "female"},
            },
            "scenes": [{"lines": [
                {"text": "a", "start": 0.0, "end": 1.0, "emotion": "中立"},
                {"text": "b", "start": 1.0, "end": 2.0, "emotion": "中立"},
            ]}],
        }
        with caplog.at_level("WARNING"):
            result, _u = _build_with_character_catalog(
                tmp_path, body, _make_character_catalog())
        speakers = [
            line.get("speaker") for sc in result["scenes"]
            for line in sc.get("lines", [])
        ]
        # 全 null のまま
        assert speakers == [None, None]
        # warn ログが出ている
        assert any(
            "speaker_drift" in rec.message
            and "backfill 不可" in rec.message
            for rec in caplog.records
        )

    def test_no_op_when_no_speaker_profiles(self, tmp_path) -> None:
        """speaker_profiles が無いケースは何もしない (= 旧挙動互換)。"""
        body = {
            "caption": "x",
            "scenes": [{"lines": [
                {"text": "a", "start": 0.0, "end": 1.0, "emotion": "中立"},
            ]}],
        }
        result, _u = _build_with_character_catalog(
            tmp_path, body, _make_character_catalog())
        speakers = [
            line.get("speaker") for sc in result["scenes"]
            for line in sc.get("lines", [])
        ]
        assert speakers == [None]

    def test_no_op_when_lines_empty(self, tmp_path) -> None:
        """全 scene の lines が空でも crash しない。"""
        body = {
            "caption": "x",
            "speaker_profiles": {"speaker_1": {"gender": "male"}},
            "scenes": [{"lines": []}],
        }
        # 例外を投げないことだけ確認
        result, _u = _build_with_character_catalog(
            tmp_path, body, _make_character_catalog())
        assert result["scenes"][0]["lines"] == []
