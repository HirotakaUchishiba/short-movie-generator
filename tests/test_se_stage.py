"""stages.se_mix.mix_se + staged_pipeline.run_se のテスト。"""
import json
import os
import shutil
import subprocess

import pytest

import config
import progress_store
import staged_pipeline
from stages import se_mix


def _make_video(path, dur=3.0):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s=320x240:d={dur}",
         "-f", "lavfi", "-i", f"sine=frequency=300:duration={dur}",
         "-shortest", "-c:v", "libx264", "-c:a", "aac", str(path)],
        check=True, capture_output=True,
    )


def _make_se(path, dur=0.3):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=800:duration={dur}",
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


def test_mix_se_multiple_placements_keeps_video_duration(tmp_path):
    video = tmp_path / "in.mp4"
    se1 = tmp_path / "s1.mp3"
    se2 = tmp_path / "s2.mp3"
    out = tmp_path / "out.mp4"
    _make_video(video, dur=3.0)
    _make_se(se1)
    _make_se(se2)

    se_mix.mix_se(str(video), [
        (str(se1), 0.5, 0.6),
        (str(se2), 2.0, 0.6),
    ], str(out))

    assert out.exists()
    assert abs(_duration(out) - 3.0) < 0.3  # duration=first で動画長に固定


def test_mix_se_empty_raises(tmp_path):
    video = tmp_path / "in.mp4"
    out = tmp_path / "out.mp4"
    _make_video(video, dur=1.0)
    with pytest.raises(ValueError):
        se_mix.mix_se(str(video), [], str(out))


def test_mix_se_with_clip_trims_source(tmp_path):
    """clip_start/clip_end 付き placement (= trim) でも動画長を保ったまま焼ける。"""
    video = tmp_path / "in.mp4"
    se = tmp_path / "s.mp3"
    out = tmp_path / "out.mp4"
    _make_video(video, dur=3.0)
    _make_se(se, dur=1.0)
    se_mix.mix_se(str(video), [(str(se), 0.5, 0.6, 0.2, 0.6)], str(out))
    assert out.exists()
    assert abs(_duration(out) - 3.0) < 0.3


@pytest.fixture
def se_project(tmp_path, monkeypatch):
    """bgm 承認済み + bgm_mixed.mp4 を持つ project を用意する。"""
    monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(
        staged_pipeline, "generate_post_captions", lambda *a, **k: "caption.md")
    ts = "20990101_000000"
    ts_path = tmp_path / ts
    ts_path.mkdir()
    for st in ("overlay", "bgm"):
        progress_store.mark_generated(str(ts_path), st)
        progress_store.mark_approved(str(ts_path), st)
    return ts, str(ts_path)


def test_run_se_passthrough_when_no_items(se_project):
    """metadata に se items 無し → bgm_mixed をそのまま reels にコピー。"""
    ts, ts_path = se_project
    with open(f"{ts_path}/bgm_mixed.mp4", "wb") as f:
        f.write(b"fake-bgm-mixed")
    with open(f"{ts_path}/metadata.json", "w") as f:
        json.dump({"screenplay_name": "x"}, f)

    staged_pipeline.run_se({"caption": "x", "scenes": []}, "x", ts_path)

    reels = f"{config.OUTPUT_DIR}/reels_{ts}.mp4"
    with open(reels, "rb") as f:
        assert f.read() == b"fake-bgm-mixed"
    assert progress_store.is_generated(ts_path, "se")


def test_run_se_backward_compat_uses_existing_reels(se_project):
    """bgm_mixed.mp4 が無い既存 project は既存 reels を入力にする。"""
    ts, ts_path = se_project
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    reels = f"{config.OUTPUT_DIR}/reels_{ts}.mp4"
    with open(reels, "wb") as f:
        f.write(b"existing-reels")
    with open(f"{ts_path}/metadata.json", "w") as f:
        json.dump({"screenplay_name": "x"}, f)

    staged_pipeline.run_se({"caption": "x", "scenes": []}, "x", ts_path)

    with open(reels, "rb") as f:
        assert f.read() == b"existing-reels"
    assert progress_store.is_generated(ts_path, "se")


def test_run_se_prefers_overlaid_to_strip_se(se_project):
    """bgm_mixed が無い旧 project: overlaid を入力に SE を消せる (reels 自己参照しない)。"""
    ts, ts_path = se_project
    with open(f"{ts_path}/overlaid.mp4", "wb") as f:
        f.write(b"overlaid-no-se")
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    reels = f"{config.OUTPUT_DIR}/reels_{ts}.mp4"
    with open(reels, "wb") as f:
        f.write(b"old-reels-with-se")
    with open(f"{ts_path}/metadata.json", "w") as f:
        json.dump({"screenplay_name": "x", "se": {"items": []}}, f)

    staged_pipeline.run_se({"caption": "x", "scenes": []}, "x", ts_path)

    # overlaid で上書き = 焼き込まれていた SE が消える (reels 自己参照しない)
    with open(reels, "rb") as f:
        assert f.read() == b"overlaid-no-se"
    assert progress_store.is_generated(ts_path, "se")


def test_run_se_mixes_items(se_project, tmp_path, monkeypatch):
    """se items があれば mix_se 経由で reels (実動画) を生成する。"""
    ts, ts_path = se_project
    src = tmp_path / "src.mp4"
    _make_video(src, dur=2.0)
    shutil.copyfile(str(src), f"{ts_path}/bgm_mixed.mp4")
    se_file = tmp_path / "se.mp3"
    _make_se(se_file)
    monkeypatch.setattr(
        "se_library.resolve_se_path",
        lambda sid: str(se_file) if sid == "x1" else None)
    with open(f"{ts_path}/metadata.json", "w") as f:
        json.dump({"screenplay_name": "x", "se": {"items": [
            {"time": 0.5, "se_id": "x1", "volume": 0.6},
        ]}}, f)

    staged_pipeline.run_se({"caption": "x", "scenes": []}, "x", ts_path)

    reels = f"{config.OUTPUT_DIR}/reels_{ts}.mp4"
    assert _duration(reels) > 0  # 実動画が生成された
    assert progress_store.is_generated(ts_path, "se")
