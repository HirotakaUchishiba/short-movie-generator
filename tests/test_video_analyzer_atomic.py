"""Phase X-2b: video_analyzer の atomic_menu 配線テスト。

build_screenplay が ``atomic_menu`` を Claude の user content に書き込むことを
mock で確認する。SYSTEM_PROMPT に atomic id 出力ルールが入っていることも確認。
旧 signature (= atomic_menu 引数省略) は test_video_analyzer.py が引き続き
カバーしている。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import atomic_assets
import video_analyzer


def _stub_stream(body_text: str):
    final = MagicMock()
    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 100
    final.usage = usage
    stream_obj = MagicMock()
    stream_obj.text_stream = iter([body_text])
    stream_obj.get_final_message.return_value = final
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=stream_obj)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def _capture_text(mock_client) -> str:
    """messages.stream に渡された user content の text を 1 本に連結して返す。"""
    call = mock_client.messages.stream.call_args
    content = call.kwargs["messages"][0]["content"]
    return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")


# ───────────── SYSTEM_PROMPT ─────────────


def test_system_prompt_has_atomic_section():
    assert "atomic id 出力ルール" in video_analyzer.SYSTEM_PROMPT


def test_system_prompt_mentions_atomic_id_keys():
    assert "hook_id" in video_analyzer.SYSTEM_PROMPT
    assert "arc_id" in video_analyzer.SYSTEM_PROMPT
    assert "action_id" in video_analyzer.SYSTEM_PROMPT


def test_system_prompt_explicit_no_new_id_rule():
    """新規 id 生成禁止の文言があること。"""
    assert "新規 id を作らない" in video_analyzer.SYSTEM_PROMPT


# ───────────── build_screenplay menu 配線 ─────────────


def test_omit_atomic_section_when_menu_none(tmp_path):
    """atomic_menu=None なら user content に atomic 集合セクションは出ない (= 旧挙動)。"""
    f = tmp_path / "f.jpg"
    f.write_bytes(b"\xff\xd8\xff\xd9")

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stub_stream(
        json.dumps({"caption": "test", "scenes": []}),
    )

    with patch("anthropic.Anthropic", return_value=mock_client):
        video_analyzer.build_screenplay(
            frame_paths=[str(f)],
            transcript={"text": "", "segments": [], "words": [], "duration": 0},
            phrase_features=[],
            source_video_path="/tmp/x.mov",
            api_key="fake",
        )
    text_blob = _capture_text(mock_client)
    assert "利用可能な atomic 集合" not in text_blob


def test_inject_atomic_menu_into_content(tmp_path):
    f = tmp_path / "f.jpg"
    f.write_bytes(b"\xff\xd8\xff\xd9")

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stub_stream(
        json.dumps({"caption": "test", "scenes": []}),
    )

    menu = {
        "actions": [{"id": "surprise_pc", "label": "PCを覗き込み驚愕"}],
        "hooks": [{"id": "paradox_q", "label": "逆説提示型"}],
        "arcs": [{"id": "low_to_high", "label": "落胆から高揚"}],
    }

    with patch("anthropic.Anthropic", return_value=mock_client):
        video_analyzer.build_screenplay(
            frame_paths=[str(f)],
            transcript={"text": "", "segments": [], "words": [], "duration": 0},
            phrase_features=[],
            source_video_path="/tmp/x.mov",
            api_key="fake",
            atomic_menu=menu,
        )
    text_blob = _capture_text(mock_client)
    assert "利用可能な atomic 集合" in text_blob
    assert "surprise_pc" in text_blob
    assert "paradox_q" in text_blob
    assert "low_to_high" in text_blob


def test_real_menu_includes_all_handwritten_ids(tmp_path):
    """build_prompt_menu() を渡すと、actions / hooks / arcs の全 id が Claude content に伝わる。"""
    f = tmp_path / "f.jpg"
    f.write_bytes(b"\xff\xd8\xff\xd9")

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stub_stream(
        json.dumps({"caption": "test", "scenes": []}),
    )

    menu = atomic_assets.build_prompt_menu()
    with patch("anthropic.Anthropic", return_value=mock_client):
        video_analyzer.build_screenplay(
            frame_paths=[str(f)],
            transcript={"text": "", "segments": [], "words": [], "duration": 0},
            phrase_features=[],
            source_video_path="/tmp/x.mov",
            api_key="fake",
            atomic_menu=menu,
        )
    text_blob = _capture_text(mock_client)
    for action_id in atomic_assets.list_action_ids():
        assert action_id in text_blob, f"action {action_id} missing from prompt"
    for hook_id in atomic_assets.list_hook_ids():
        assert hook_id in text_blob, f"hook {hook_id} missing from prompt"
    for arc_id in atomic_assets.list_arc_ids():
        assert arc_id in text_blob, f"arc {arc_id} missing from prompt"


def test_existing_signature_compatible_with_old_callers(tmp_path):
    """旧 caller (= atomic_menu 引数を渡さない) は引き続き動く。"""
    f = tmp_path / "f.jpg"
    f.write_bytes(b"\xff\xd8\xff\xd9")

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stub_stream(
        json.dumps({"caption": "x", "scenes": []}),
    )

    with patch("anthropic.Anthropic", return_value=mock_client):
        result, usage = video_analyzer.build_screenplay(
            frame_paths=[str(f)],
            transcript={"text": "", "segments": [], "words": [], "duration": 0},
            phrase_features=[],
            source_video_path="/tmp/x.mov",
            api_key="fake",
        )
    assert result["caption"] == "x"
    assert "input_tokens" in usage
