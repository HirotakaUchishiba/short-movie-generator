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
            "lines": [{"text": "やばい", "start": 0.0, "end": 1.0, "emotion": "中立"}],
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


