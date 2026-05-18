"""stages/text_mapping.py の char-offset 計算 / time-mapping ロジックの単体テスト。

scene_gen._build_screenplay_text / _build_position_to_time_map /
_find_line_time_range / _resolve_inline_tag が text_mapping への shim になり、
shim と実体の挙動が一致することを確認する。
"""
from __future__ import annotations

import pytest

import scene_gen
from stages import text_mapping


def test_resolve_inline_tag_user_first():
    line = {"audio_tags": ["whispers"], "emotion": "怒り"}
    assert text_mapping.resolve_inline_tag(line, {}, 0) == "whispers"


def test_resolve_inline_tag_falls_back_to_emotion(monkeypatch):
    monkeypatch.setattr(
        "config.EMOTION_AUDIO_TAGS", {"驚き": ["surprised"]},
    )
    monkeypatch.setattr("config.EMOTION_AUDIO_TAGS_ENABLED", True)
    line = {"emotion": "驚き"}
    assert text_mapping.resolve_inline_tag(line, {}, 0) == "surprised"


def test_resolve_inline_tag_disabled_emotion_returns_empty(monkeypatch):
    monkeypatch.setattr("config.EMOTION_AUDIO_TAGS_ENABLED", False)
    monkeypatch.setattr(
        "config.EMOTION_AUDIO_TAGS", {"驚き": ["surprised"]},
    )
    assert text_mapping.resolve_inline_tag({"emotion": "驚き"}, {}, 0) == ""


def test_build_screenplay_text_joins_with_separator():
    sp = {
        "scenes": [
            {"lines": [{"text": "あ"}, {"text": "い"}]},
            {"lines": [{"text": "う"}]},
        ],
    }
    text, specs = text_mapping.build_screenplay_text(sp)
    assert text == "あ  い  う"
    assert len(specs) == 3
    # 連続 scene でも cursor は separator len を加算する
    assert specs[0]["char_start"] == 0
    assert specs[1]["char_start"] == specs[0]["char_end"] + 2
    assert specs[2]["char_start"] == specs[1]["char_end"] + 2


def test_build_screenplay_text_prefixes_tag_keeps_specs_for_body(monkeypatch):
    monkeypatch.setattr(
        "config.EMOTION_AUDIO_TAGS", {"驚き": ["surprised"]},
    )
    monkeypatch.setattr("config.EMOTION_AUDIO_TAGS_ENABLED", True)
    sp = {"scenes": [{"lines": [
        {"text": "あ", "emotion": "驚き"},
        {"text": "い"},
    ]}]}
    text, specs = text_mapping.build_screenplay_text(sp)
    # prefix "[surprised] " (12 chars) は line.text の前に挿入
    assert text == "[surprised] あ  い"
    assert specs[0]["char_start"] == 12  # 本文 "あ" の開始位置
    assert specs[0]["char_end"] == 13
    assert specs[1]["char_start"] == 13 + 2  # separator 2


def test_build_position_to_time_map_aligns_sequentially():
    txt = "abc"
    char_ts = [
        {"char": "a", "start": 0.0, "end": 0.1},
        {"char": "b", "start": 0.1, "end": 0.2},
        {"char": "c", "start": 0.2, "end": 0.3},
    ]
    out = text_mapping.build_position_to_time_map(txt, char_ts)
    assert out[0] == {"start": 0.0, "end": 0.1}
    assert out[1] == {"start": 0.1, "end": 0.2}
    assert out[2] == {"start": 0.2, "end": 0.3}


def test_build_position_to_time_map_skips_missing_chars():
    txt = "axbxc"
    # API が "x" を返さない場合でも順次マッチで a/b/c に紐付ける
    char_ts = [
        {"char": "a", "start": 0.0, "end": 0.1},
        {"char": "b", "start": 0.1, "end": 0.2},
        {"char": "c", "start": 0.2, "end": 0.3},
    ]
    out = text_mapping.build_position_to_time_map(txt, char_ts)
    assert out[0] == {"start": 0.0, "end": 0.1}
    assert out[1] is None
    assert out[2] == {"start": 0.1, "end": 0.2}
    assert out[3] is None
    assert out[4] == {"start": 0.2, "end": 0.3}


def test_find_line_time_range_first_and_last_valid():
    p2t: list[dict | None] = [
        None,
        {"start": 0.5, "end": 0.6},
        None,
        {"start": 0.9, "end": 1.0},
        None,
    ]
    s, e = text_mapping.find_line_time_range(p2t, 0, 5)
    assert s == 0.5
    assert e == 1.0


def test_find_line_time_range_no_valid_returns_none():
    p2t: list[dict | None] = [None, None, None]
    assert text_mapping.find_line_time_range(p2t, 0, 3) == (None, None)


def test_scene_gen_shims_delegate(monkeypatch):
    """scene_gen._resolve_inline_tag / _build_screenplay_text / 等が
    stages.text_mapping を呼ぶことを確認。"""
    calls: list[str] = []

    def fake_resolve(*a, **kw):
        calls.append("resolve")
        return ""

    def fake_build_text(*a, **kw):
        calls.append("build_text")
        return ("", [])

    def fake_build_p2t(*a, **kw):
        calls.append("build_p2t")
        return []

    def fake_find_range(*a, **kw):
        calls.append("find_range")
        return (None, None)

    monkeypatch.setattr(text_mapping, "resolve_inline_tag", fake_resolve)
    monkeypatch.setattr(text_mapping, "build_screenplay_text", fake_build_text)
    monkeypatch.setattr(
        text_mapping, "build_position_to_time_map", fake_build_p2t,
    )
    monkeypatch.setattr(text_mapping, "find_line_time_range", fake_find_range)

    scene_gen._resolve_inline_tag({}, {}, 0)
    scene_gen._build_screenplay_text({})
    scene_gen._build_position_to_time_map("", [])
    scene_gen._find_line_time_range([], 0, 0)
    assert calls == ["resolve", "build_text", "build_p2t", "find_range"]


def test_scene_gen_re_exports_separator():
    """SCREENPLAY_TEXT_SEPARATOR は scene_gen からも依然アクセス可能。"""
    # scene_gen.py L23 で独立定義しているため、text_mapping 側と同値であること
    assert scene_gen.SCREENPLAY_TEXT_SEPARATOR == text_mapping.SCREENPLAY_TEXT_SEPARATOR
    assert text_mapping.SCREENPLAY_TEXT_SEPARATOR == "  "
