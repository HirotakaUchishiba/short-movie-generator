"""auto_animation_prompt の bg 画像 (Vision) 渡し機能のテスト。"""

import base64
import json
import os
from unittest.mock import MagicMock

import pytest

import auto_animation_prompt as aap


def _scene() -> dict:
    return {
        "duration": 5.0,
        "background_prompt": "デスクで作業する女性",
        "lines": [
            {"text": "やったー", "emotion": "喜び", "start": 0.0,
             "delivery": "弾むような声"},
        ],
    }


def _make_png(path: str, payload: bytes = b"FAKE_PNG_BYTES") -> None:
    with open(path, "wb") as f:
        f.write(payload)


def _mock_anthropic(monkeypatch, json_payload: dict) -> MagicMock:
    fake_response = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(json_payload, ensure_ascii=False)
    fake_response.content = [block]

    fake_messages = MagicMock()
    fake_messages.create = MagicMock(return_value=fake_response)
    fake_client = MagicMock()
    fake_client.messages = fake_messages
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic = MagicMock(return_value=fake_client)

    import sys
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)
    monkeypatch.setattr(aap.config, "ANTHROPIC_API_KEY", "test-key")
    return fake_messages


# ─────────── _input_signature with bg ───────────


def test_signature_includes_bg_hash_when_bg_exists(tmp_path) -> None:
    bg = tmp_path / "bg_000.png"
    _make_png(str(bg), b"X1")
    sig = aap._input_signature(_scene(), None, bg_path=str(bg))
    assert "bg_sha256" in sig
    assert len(sig["bg_sha256"]) == 64  # sha256 hex


def test_signature_excludes_bg_when_no_path() -> None:
    sig = aap._input_signature(_scene(), None, bg_path=None)
    assert "bg_sha256" not in sig


def test_signature_excludes_bg_when_path_missing(tmp_path) -> None:
    sig = aap._input_signature(_scene(), None,
                                bg_path=str(tmp_path / "nope.png"))
    assert "bg_sha256" not in sig


def test_hash_changes_when_bg_bytes_change(tmp_path) -> None:
    bg = tmp_path / "bg_000.png"
    _make_png(str(bg), b"VERSION_A")
    h1 = aap._input_hash(aap._input_signature(_scene(), None, bg_path=str(bg)))
    _make_png(str(bg), b"VERSION_B")
    h2 = aap._input_hash(aap._input_signature(_scene(), None, bg_path=str(bg)))
    assert h1 != h2


def test_hash_same_when_bg_unchanged(tmp_path) -> None:
    bg = tmp_path / "bg_000.png"
    _make_png(str(bg), b"SAME")
    h1 = aap._input_hash(aap._input_signature(_scene(), None, bg_path=str(bg)))
    h2 = aap._input_hash(aap._input_signature(_scene(), None, bg_path=str(bg)))
    assert h1 == h2


# ─────────── _build_message_content ───────────


def test_message_content_text_only_without_bg(tmp_path) -> None:
    blocks = aap._build_message_content(_scene(), None, bg_path=None)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "text"


def test_message_content_includes_image_when_bg_exists(tmp_path) -> None:
    bg = tmp_path / "bg_000.png"
    _make_png(str(bg), b"PNGDATA")
    blocks = aap._build_message_content(_scene(), None, bg_path=str(bg))
    # image block と text block の 2 つ
    assert len(blocks) == 2
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["type"] == "base64"
    assert blocks[0]["source"]["media_type"] == "image/png"
    decoded = base64.b64decode(blocks[0]["source"]["data"])
    assert decoded == b"PNGDATA"
    # 第 2 ブロックは指示テキスト + scene metadata
    assert blocks[1]["type"] == "text"
    assert "FIRST FRAME" in blocks[1]["text"]


def test_message_content_skips_image_when_path_missing(tmp_path) -> None:
    blocks = aap._build_message_content(_scene(), None,
                                          bg_path=str(tmp_path / "missing.png"))
    assert len(blocks) == 1
    assert blocks[0]["type"] == "text"


def test_bg_media_type_detects_png_magic(tmp_path) -> None:
    p = tmp_path / "actual_png.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    assert aap._bg_media_type(str(p)) == "image/png"


def test_bg_media_type_detects_jpeg_magic_even_with_png_extension(
    tmp_path,
) -> None:
    """Imagen が .png 拡張子で実体 JPEG を吐く問題に対応"""
    p = tmp_path / "actual_jpeg.png"
    p.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)
    assert aap._bg_media_type(str(p)) == "image/jpeg"


def test_bg_media_type_detects_webp(tmp_path) -> None:
    p = tmp_path / "x.webp"
    p.write_bytes(b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 16)
    assert aap._bg_media_type(str(p)) == "image/webp"


def test_bg_media_type_falls_back_to_extension_when_no_magic(tmp_path) -> None:
    p = tmp_path / "tiny.jpg"
    p.write_bytes(b"")  # 空ファイル → magic 検出不可
    assert aap._bg_media_type(str(p)) == "image/jpeg"


# ─────────── generate (bg 経路) ───────────


def test_generate_with_bg_passes_image_to_llm(tmp_path, monkeypatch) -> None:
    bg = tmp_path / "bg_000.png"
    _make_png(str(bg), b"BG_BYTES")

    fake_messages = _mock_anthropic(monkeypatch, {
        "subject": "S",
        "action_sequence": "A",
        "camera": "C",
        "mood": "M",
    })

    entry = aap.generate(_scene(), None, str(tmp_path), 0,
                          force=True, bg_path=str(bg))

    assert entry["bg_used"] is True
    # API 呼出時の content blocks に image が含まれているか
    call = fake_messages.create.call_args
    msgs = call.kwargs["messages"]
    content = msgs[0]["content"]
    assert any(b.get("type") == "image" for b in content)


def test_generate_without_bg_uses_text_only(tmp_path, monkeypatch) -> None:
    fake_messages = _mock_anthropic(monkeypatch, {
        "subject": "S", "action_sequence": "A",
        "camera": "C", "mood": "M",
    })

    entry = aap.generate(_scene(), None, str(tmp_path), 0,
                          force=True, bg_path=None)

    assert entry["bg_used"] is False
    call = fake_messages.create.call_args
    content = call.kwargs["messages"][0]["content"]
    assert all(b.get("type") != "image" for b in content)


def test_generate_bg_change_invalidates_cache(tmp_path, monkeypatch) -> None:
    bg = tmp_path / "bg_000.png"
    _make_png(str(bg), b"V1")

    fake_messages = _mock_anthropic(monkeypatch, {
        "subject": "S", "action_sequence": "A",
        "camera": "C", "mood": "M",
    })

    aap.generate(_scene(), None, str(tmp_path), 0, force=False,
                  bg_path=str(bg))
    # 同じ bg なら cache hit
    aap.generate(_scene(), None, str(tmp_path), 0, force=False,
                  bg_path=str(bg))
    assert fake_messages.create.call_count == 1

    # bg 内容を変えたら cache 無効化されて再呼出
    _make_png(str(bg), b"V2_DIFFERENT")
    aap.generate(_scene(), None, str(tmp_path), 0, force=False,
                  bg_path=str(bg))
    assert fake_messages.create.call_count == 2


def test_generate_bg_missing_falls_back_to_text(tmp_path, monkeypatch) -> None:
    fake_messages = _mock_anthropic(monkeypatch, {
        "subject": "S", "action_sequence": "A",
        "camera": "C", "mood": "M",
    })

    entry = aap.generate(_scene(), None, str(tmp_path), 0, force=True,
                          bg_path=str(tmp_path / "missing.png"))

    assert entry["bg_used"] is False


def test_get_cached_uses_bg_in_signature(tmp_path, monkeypatch) -> None:
    bg = tmp_path / "bg_000.png"
    _make_png(str(bg), b"X")

    _mock_anthropic(monkeypatch, {
        "subject": "S", "action_sequence": "A",
        "camera": "C", "mood": "M",
    })

    aap.generate(_scene(), None, str(tmp_path), 0, force=True,
                  bg_path=str(bg))

    # 同じ bg なら命中
    cached = aap.get_cached(str(tmp_path), 0, _scene(), None, bg_path=str(bg))
    assert cached is not None
    # bg 抜きで参照すると hash が変わって命中しない
    cached_no_bg = aap.get_cached(str(tmp_path), 0, _scene(), None, bg_path=None)
    assert cached_no_bg is None
