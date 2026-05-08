"""Phase X-2b: video_analyzer の atomic_menu 配線テスト。

build_screenplay が ``atomic_menu`` を Claude の user content に書き込むことを
mock で確認する。SYSTEM_PROMPT に atomic id 出力ルールが入っていることも確認。
旧 signature (= atomic_menu 引数省略) は test_video_analyzer.py が引き続き
カバーしている。
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import atomic_assets
import screenplay_validator
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
    """新規 id 生成禁止のニュアンスが何らかの形で表現されていること。

    具体的な文言 ("新規 id を作らない" 等) はリワード可能だが、「新規/未定義の
    id を生成しない」という意味のルールが残っているかを緩めに検証する。
    """
    prompt = video_analyzer.SYSTEM_PROMPT
    has_new_id_token = any(
        kw in prompt for kw in ("新規 id", "新しい id", "未定義 id", "新規")
    )
    has_negation = any(
        kw in prompt for kw in ("作らない", "生成しない", "禁止", "reject")
    )
    assert has_new_id_token and has_negation, (
        "SYSTEM_PROMPT から '新規 id 生成禁止' のルールが消えている可能性"
    )


def test_system_prompt_does_not_carry_phase_tag_in_section_header():
    """section header に "(Phase X-2b)" のような時限タグが残っていないこと。

    Phase tag は時間が経つとノイズになるので prompt 本文から外す方針。
    docstring / コメントには残しても良いが、Claude に渡される prompt 本文には
    入れない。
    """
    prompt = video_analyzer.SYSTEM_PROMPT
    assert "(Phase X-" not in prompt, (
        "SYSTEM_PROMPT に Phase tag が残っている (= 将来ノイズになる)"
    )


def test_system_prompt_references_keys_present_in_menu():
    """SYSTEM_PROMPT が言及するキー名が build_prompt_menu の出力に存在すること。

    "compatible_locations" / "first_scene_action_id" / "emotion_sequence" 等の
    キー名を menu builder 側でリネームしたら SYSTEM_PROMPT もアップデートが
    必要。整合を CI で検出する。
    """
    prompt = video_analyzer.SYSTEM_PROMPT
    menu = atomic_assets.build_prompt_menu()
    candidate_keys = (
        "compatible_locations",
        "first_scene_action_id",
        "emotion_sequence",
    )
    referenced = [k for k in candidate_keys if k in prompt]
    assert referenced, (
        "SYSTEM_PROMPT が menu schema のキー名を 1 つも参照していない "
        "(= drift 検出の前提が崩れている)"
    )
    all_menu_keys: set[str] = set()
    for entries in menu.values():
        for e in entries:
            all_menu_keys.update(e.keys())
    for key in referenced:
        assert key in all_menu_keys, (
            f"SYSTEM_PROMPT が '{key}' を参照しているが build_prompt_menu の "
            "出力に含まれていない (drift 発生)"
        )


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


def test_omit_atomic_section_when_menu_all_empty(tmp_path):
    """全集合が空の atomic_menu (= dict は truthy だが中身無し) ではセクションを注入しない。

    SSOT ディレクトリが空のテスト環境などで「id を選べ。集合は空」という
    矛盾した prompt が Claude に届くのを防ぐ。
    """
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
            atomic_menu={"actions": [], "hooks": [], "arcs": []},
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


# ───────────── analyze pipeline の警告降格経路 ─────────────


def test_validator_warns_on_unknown_atomic_ids_without_raising():
    """Claude が幻覚で未定義 id を吐いても、analyze pipeline 経路 (= strict=False)
    なら raise せず errors list に該当 id の警告を返すこと。

    pipeline.py:396 で ``validate_screenplay(strict=False)`` を呼んでいるので、
    Claude 応答に未定義 id が含まれても analyze ジョブを止めない (= 互換維持)。
    """
    sp = {
        "caption": "test",
        "hook_id": "nonexistent_hook_xyz",
        "arc_id": "nonexistent_arc_xyz",
        "scenes": [
            {
                "duration": 5.0,
                "action_id": "nonexistent_action_xyz",
                "lines": [{"text": "あ", "start": 0.0, "end": 1.0}],
            },
        ],
    }
    errors = screenplay_validator.validate_screenplay(
        sp, strict=False, require_composed=False,
    )
    joined = "\n".join(errors)
    assert "nonexistent_hook_xyz" in joined
    assert "nonexistent_arc_xyz" in joined
    assert "nonexistent_action_xyz" in joined


def test_pipeline_uses_validator_in_non_strict_mode():
    """analyze/pipeline.py が validate_screenplay を strict=False で呼ぶこと。

    strict=True に戻すと未定義 id を吐いた Claude 応答で analyze ジョブが落ち、
    既存 caller / cache 再利用フローを破壊する。リグレッション検出用のメタテスト。
    """
    src = (Path(__file__).resolve().parent.parent / "analyze" / "pipeline.py").read_text(
        encoding="utf-8",
    )
    assert "validate_screenplay(" in src
    assert "strict=False" in src
