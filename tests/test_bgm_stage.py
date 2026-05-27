"""stages.bgm_mix.mix_bgm + staged_pipeline.run_bgm のテスト。"""
import json
import subprocess

import pytest

import config
import progress_store
import staged_pipeline
from stages import bgm_mix


def _make_video(path, dur=3.0):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s=320x240:d={dur}",
         "-f", "lavfi", "-i", f"sine=frequency=300:duration={dur}",
         "-shortest", "-c:v", "libx264", "-c:a", "aac", str(path)],
        check=True, capture_output=True,
    )


def _make_bgm(path, dur=2.0):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=200:duration={dur}",
         "-c:a", "libmp3lame", str(path)],
        check=True, capture_output=True,
    )


def _duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip())


def test_mix_bgm_ducking_produces_video_matching_duration(tmp_path):
    video = tmp_path / "in.mp4"
    bgm = tmp_path / "bgm.mp3"
    out = tmp_path / "out.mp4"
    _make_video(video, dur=3.0)
    _make_bgm(bgm, dur=2.0)  # 動画より短い → ループされる

    bgm_mix.mix_bgm(str(video), str(bgm), str(out), volume=0.2, ducking=True)

    assert out.exists()
    # 出力尺は入力動画とほぼ一致 (BGM は atrim で動画長に切られる)
    assert abs(_duration(out) - 3.0) < 0.3


def test_mix_bgm_no_ducking(tmp_path):
    video = tmp_path / "in.mp4"
    bgm = tmp_path / "bgm.mp3"
    out = tmp_path / "out.mp4"
    _make_video(video, dur=2.0)
    _make_bgm(bgm, dur=3.0)  # 動画より長い → 切られる

    bgm_mix.mix_bgm(str(video), str(bgm), str(out), volume=0.3, ducking=False)
    assert out.exists()
    assert abs(_duration(out) - 2.0) < 0.3


@pytest.fixture
def bgm_project(tmp_path, monkeypatch):
    """overlay 承認済み + overlaid.mp4 を持つ project を用意する。"""
    monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path / "output"))
    # caption 生成は別 stage の責務なので mock
    monkeypatch.setattr(
        staged_pipeline, "generate_post_captions", lambda *a, **k: "caption.md")
    ts = "20990101_000000"
    ts_path = tmp_path / ts
    ts_path.mkdir()
    progress_store.mark_generated(str(ts_path), "overlay")
    progress_store.mark_approved(str(ts_path), "overlay")
    return ts, str(ts_path)


def test_run_bgm_passthrough_when_no_bgm(bgm_project, monkeypatch):
    """metadata に bgm 未設定 → overlaid をそのまま reels にコピー (pass-through)。"""
    ts, ts_path = bgm_project
    overlaid = f"{ts_path}/overlaid.mp4"
    with open(overlaid, "wb") as f:
        f.write(b"fake-overlaid-mp4")
    with open(f"{ts_path}/metadata.json", "w") as f:
        json.dump({"screenplay_name": "x"}, f)

    staged_pipeline.run_bgm({"caption": "x", "scenes": []}, "x", ts_path)

    reels = f"{config.OUTPUT_DIR}/reels_{ts}.mp4"
    with open(reels, "rb") as f:
        assert f.read() == b"fake-overlaid-mp4"   # コピーされた
    assert progress_store.is_generated(ts_path, "bgm")


def test_run_bgm_backward_compat_uses_existing_reels(bgm_project, monkeypatch):
    """overlaid.mp4 が無い既存 project は既存 reels を入力にする (= 上書きしても壊れない)。"""
    ts, ts_path = bgm_project
    import os
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    reels = f"{config.OUTPUT_DIR}/reels_{ts}.mp4"
    with open(reels, "wb") as f:
        f.write(b"existing-reels")
    with open(f"{ts_path}/metadata.json", "w") as f:
        json.dump({"screenplay_name": "x"}, f)

    # overlaid.mp4 は作らない
    staged_pipeline.run_bgm({"caption": "x", "scenes": []}, "x", ts_path)

    with open(reels, "rb") as f:
        assert f.read() == b"existing-reels"   # bgm none + 同一パス → そのまま
    assert progress_store.is_generated(ts_path, "bgm")
