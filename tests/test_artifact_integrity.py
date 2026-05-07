"""artifact_integrity の挙動カバー。

- 妥当ファイル → True
- 破損 + AUTO_DELETE off (既定) → warning ログ + True (= 既存 skip 維持)
- 破損 + AUTO_DELETE on → 削除して False (= 再生成へ)
- DISABLED → 常に True (= チェック自体を素通り)
"""
import logging
import os
import subprocess

import pytest
from PIL import Image

import artifact_integrity


def _make_valid_png(path: str) -> None:
    img = Image.new("RGB", (10, 10), color=(255, 0, 0))
    img.save(path, "PNG")


def _make_corrupt_png(path: str) -> None:
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")  # PNG header だけ書いて中身無し


def _make_valid_mp4(path: str) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.5",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _make_corrupt_mp4(path: str) -> None:
    with open(path, "wb") as f:
        f.write(b"not actually an mp4")


def test_is_valid_png_true(tmp_path):
    p = str(tmp_path / "ok.png")
    _make_valid_png(p)
    assert artifact_integrity.is_valid_png(p) is True


def test_is_valid_png_false_on_truncated(tmp_path):
    p = str(tmp_path / "bad.png")
    _make_corrupt_png(p)
    assert artifact_integrity.is_valid_png(p) is False


def test_is_valid_png_false_on_missing(tmp_path):
    assert artifact_integrity.is_valid_png(str(tmp_path / "nope.png")) is False


def test_is_valid_mp4_true(tmp_path):
    p = str(tmp_path / "ok.mp4")
    _make_valid_mp4(p)
    assert artifact_integrity.is_valid_mp4(p) is True


def test_is_valid_mp4_false_on_garbage(tmp_path):
    p = str(tmp_path / "bad.mp4")
    _make_corrupt_mp4(p)
    assert artifact_integrity.is_valid_mp4(p) is False


def _make_valid_mp3(path: str) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "anullsrc=cl=mono:r=8000:d=0.5",
        "-c:a", "libmp3lame", "-b:a", "32k", path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def test_is_valid_audio_true_for_real_mp3(tmp_path):
    p = str(tmp_path / "ok.mp3")
    _make_valid_mp3(p)
    assert artifact_integrity.is_valid_audio(p) is True


def test_is_valid_audio_false_on_garbage(tmp_path):
    p = str(tmp_path / "bad.mp3")
    with open(p, "wb") as f:
        f.write(b"not actually an mp3")
    assert artifact_integrity.is_valid_audio(p) is False


def test_is_valid_audio_false_on_zero_byte(tmp_path):
    p = str(tmp_path / "empty.mp3")
    open(p, "wb").close()
    assert artifact_integrity.is_valid_audio(p) is False


def test_is_valid_audio_min_duration_threshold(tmp_path):
    """min_duration を強気に設定すると、短い mp3 は reject される。"""
    p = str(tmp_path / "short.mp3")
    _make_valid_mp3(p)
    assert artifact_integrity.is_valid_audio(p, min_duration=10.0) is False


def test_build_audios_from_full_raises_on_corrupt_tts_full(tmp_path):
    """tts_full.mp3 が破損していると _build_audios_from_full は cleanup + raise."""
    import scene_gen
    ts = str(tmp_path)
    full_mp3 = os.path.join(ts, "tts_full.mp3")
    full_json = os.path.join(ts, "tts_full.json")
    text_meta = os.path.join(ts, "tts_full.text_meta.json")
    with open(full_mp3, "wb") as f:
        f.write(b"not really an mp3")
    with open(full_json, "w") as f:
        f.write("[]")
    with open(text_meta, "w") as f:
        f.write("{}")

    sp = {
        "scenes": [
            {"duration": 1.0, "background_prompt": "x",
             "lines": [{"text": "a", "start": 0}]},
        ],
    }
    with pytest.raises(RuntimeError, match="tts_full.mp3"):
        scene_gen._build_audios_from_full(sp, ts)
    # cleanup された
    assert not os.path.exists(full_mp3)
    assert not os.path.exists(full_json)
    assert not os.path.exists(text_meta)


def test_check_existing_returns_true_for_valid_png(tmp_path):
    p = str(tmp_path / "ok.png")
    _make_valid_png(p)
    assert artifact_integrity.check_existing(p, "png") is True


def test_check_existing_warns_but_keeps_when_corrupt_default(
    tmp_path, monkeypatch, caplog,
):
    """既定モード: 破損検出 → warning だけ、ファイルは消さず True を返す。"""
    monkeypatch.setattr("config.ARTIFACT_INTEGRITY_AUTO_DELETE", False,
                        raising=False)
    monkeypatch.delenv("ARTIFACT_INTEGRITY_AUTO_DELETE", raising=False)
    p = str(tmp_path / "bad.png")
    _make_corrupt_png(p)
    with caplog.at_level(logging.WARNING):
        result = artifact_integrity.check_existing(
            p, "png", label="scene 1 BG")
    assert result is True
    assert os.path.exists(p)
    assert any("破損疑い" in rec.getMessage() for rec in caplog.records)
    assert any("scene 1 BG" in rec.getMessage() for rec in caplog.records)


def test_check_existing_auto_delete_removes_corrupt(
    tmp_path, monkeypatch, caplog,
):
    """AUTO_DELETE=on で破損 → 削除して False (caller は再生成へ進む)。"""
    monkeypatch.setattr("config.ARTIFACT_INTEGRITY_AUTO_DELETE", True,
                        raising=False)
    p = str(tmp_path / "bad.png")
    _make_corrupt_png(p)
    with caplog.at_level(logging.WARNING):
        result = artifact_integrity.check_existing(p, "png")
    assert result is False
    assert not os.path.exists(p)


def test_check_existing_disabled_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_INTEGRITY_CHECK_DISABLED", "1")
    p = str(tmp_path / "bad.png")
    _make_corrupt_png(p)
    assert artifact_integrity.check_existing(p, "png") is True
    assert os.path.exists(p)


def test_check_existing_disabled_via_config(tmp_path, monkeypatch):
    monkeypatch.delenv("ARTIFACT_INTEGRITY_CHECK_DISABLED", raising=False)
    monkeypatch.setattr(
        "config.ARTIFACT_INTEGRITY_CHECK_ENABLED", False, raising=False)
    p = str(tmp_path / "bad.png")
    _make_corrupt_png(p)
    assert artifact_integrity.check_existing(p, "png") is True


def test_check_existing_missing_file_returns_true(tmp_path):
    p = str(tmp_path / "absent.mp4")
    assert artifact_integrity.check_existing(p, "mp4") is True


def test_auto_delete_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_INTEGRITY_AUTO_DELETE", "1")
    monkeypatch.setattr(
        "config.ARTIFACT_INTEGRITY_AUTO_DELETE", False, raising=False)
    p = str(tmp_path / "bad.mp4")
    _make_corrupt_mp4(p)
    assert artifact_integrity.check_existing(p, "mp4") is False
    assert not os.path.exists(p)
