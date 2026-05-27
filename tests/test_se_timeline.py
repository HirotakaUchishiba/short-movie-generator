"""SE タイムライン UI 用 backend (波形 peaks / サムネ抽出 / duration) のテスト。"""
import json
import subprocess

import audio_features
import config
import se_library
from routes.se import _ensure_thumbnails


def _make_audio(path, dur=1.0, freq=440):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"sine=frequency={freq}:duration={dur}",
         "-c:a", "libmp3lame", str(path)],
        check=True, capture_output=True,
    )


def _make_video(path, dur=3.0):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size=90x160:rate=30:d={dur}",
         "-f", "lavfi", "-i", f"sine=frequency=200:duration={dur}",
         "-shortest", "-c:v", "libx264", "-c:a", "aac", str(path)],
        check=True, capture_output=True,
    )


def test_extract_waveform_peaks_normalized(tmp_path):
    audio = tmp_path / "a.mp3"
    _make_audio(audio, dur=1.0)
    d = audio_features.extract_waveform_peaks(str(audio))
    assert d["duration"] > 0.5
    assert len(d["peaks"]) > 0
    assert all(0.0 <= p <= 1.0 for p in d["peaks"])
    assert max(d["peaks"]) <= 1.0


def test_ensure_thumbnails_count_and_cache(tmp_path):
    video = tmp_path / "v.mp4"
    _make_video(video, dur=3.0)
    thumb_dir = tmp_path / "thumbs"
    count = _ensure_thumbnails(str(video), str(thumb_dir), 1.0)
    assert count == 3
    assert (thumb_dir / "thumb_001.jpg").exists()
    # cache: 同じ src なら再抽出せず同数
    count2 = _ensure_thumbnails(str(video), str(thumb_dir), 1.0)
    assert count2 == 3


def test_list_se_includes_duration_sec(tmp_path, monkeypatch):
    se_dir = tmp_path / "se"
    se_dir.mkdir()
    _make_audio(se_dir / "a.mp3", dur=1.5)
    catalog = tmp_path / "se_catalog.json"
    catalog.write_text(
        json.dumps([{"id": "a", "file": "a.mp3", "category": "reaction"}]),
        encoding="utf-8")
    monkeypatch.setattr(config, "SE_DIR", str(se_dir))
    monkeypatch.setattr(config, "SE_CATALOG_PATH", str(catalog))
    out = se_library.list_se()
    assert len(out) == 1
    assert out[0]["duration_sec"] > 1.0
