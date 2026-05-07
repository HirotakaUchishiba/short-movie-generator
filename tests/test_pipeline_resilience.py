"""パイプラインの **回復性** に関する regression test。

PR #52〜#57 で塞いだ穴 (timeout / partial output / disk space / 整合性) が
将来のリファクタで silent に崩れないようガードする。

カバーしているケース:
    - lipsync / kling 結果動画 DL の timeout が retry 経路に乗る
    - collect_scene_videos が truncated mp4 を確実に reject する
    - run_overlay の途中失敗で merged / overlaid / output 残骸が残らない
    - preflight.check_disk_space が空き不足で PreflightError を投げる
"""
import os
import subprocess
from collections import namedtuple
from unittest.mock import MagicMock

import pytest
import requests

import compositor
import config
import preflight
import progress_store
import scene_gen
import staged_pipeline


# ──────────────── helpers ────────────────

def _make_silent_aac(path: str, duration: float = 0.5) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", f"{duration:.3f}",
        "-c:a", "aac", "-b:a", "64k", path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _make_tiny_mp4(path: str, duration: float = 0.5) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=black:s=108x192:d={duration:.3f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


# ──────────────── timeout retry ────────────────

def test_lipsync_fal_download_timeout_triggers_retry(monkeypatch, tmp_path):
    """fal-sync の result DL が timeout した時、retry classifier が
    'retry' と判定して再試行に乗るか。"""
    import lipsync_client

    monkeypatch.setattr(lipsync_client.config, "FAL_API_KEY", "test-key")
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_MODEL",
                        "lipsync-1.9.0-beta", raising=False)
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_SYNC_MODE",
                        "cut_off", raising=False)

    fake_fal = MagicMock()
    fake_fal.upload_file.side_effect = ["http://v", "http://a"]
    fake_fal.subscribe.return_value = {"video": {"url": "http://out.mp4"}}
    monkeypatch.setattr(lipsync_client, "fal_client", fake_fal)

    # backoff を潰してテストを高速化
    monkeypatch.setattr(lipsync_client, "BACKOFF_SECONDS", [0, 0, 0, 0, 0])

    call_count = {"n": 0}
    fake_resp = MagicMock()
    fake_resp.content = b"recovered"
    fake_resp.raise_for_status.return_value = None

    def flaky_get(url, **kw):
        # 1 回目 = timeout、2 回目以降 = 成功 (retry が走った証拠)
        call_count["n"] += 1
        assert kw.get("timeout") is not None, "timeout 引数が抜けている"
        if call_count["n"] == 1:
            raise requests.Timeout("simulated timeout")
        return fake_resp

    monkeypatch.setattr(lipsync_client.requests, "get", flaky_get)

    out = tmp_path / "out.mp4"
    lipsync_client._apply_fal_sync("/v.mp4", "/a.mp3", str(out))

    assert call_count["n"] >= 2
    assert out.read_bytes() == b"recovered"


def test_fal_video_client_download_timeout_passes_kwarg(monkeypatch, tmp_path):
    """Kling V3 の result DL が timeout kwarg 付きで呼ばれることを確認 (回帰防止)。"""
    import fal_video_client

    monkeypatch.setattr(fal_video_client.config, "FAL_API_KEY", "test-key")

    fake_fal = MagicMock()
    fake_fal.encode_image.return_value = "http://img"
    fake_fal.subscribe.return_value = {"video": {"url": "http://out.mp4"}}
    monkeypatch.setattr(fal_video_client, "fal_client", fake_fal)
    monkeypatch.setattr(fal_video_client.Image, "open", lambda p: MagicMock())

    captured: dict = {}
    fake_resp = MagicMock()
    fake_resp.content = b"video-bytes"
    fake_resp.raise_for_status.return_value = None

    def capture_get(url, **kw):
        captured["timeout"] = kw.get("timeout")
        return fake_resp

    monkeypatch.setattr(fal_video_client.requests, "get", capture_get)

    out = tmp_path / "kling.mp4"
    fal_video_client.generate_video(
        "/img.png", "prompt", str(out), audio_duration=4.0)

    assert captured["timeout"] is not None
    assert captured["timeout"] >= 30


# ──────────────── collect_scene_videos integrity ────────────────

def test_collect_scene_videos_rejects_truncated_mp4(tmp_path, monkeypatch):
    """0byte / 壊れた scene_<i>.mp4 が混じっていた時に hard fail する。"""
    monkeypatch.setattr(scene_gen.artifact_integrity, "is_enabled",
                        lambda: True)

    # scene 0 は valid、scene 1 は壊れている
    valid = tmp_path / "scene_000.mp4"
    _make_tiny_mp4(str(valid))
    broken = tmp_path / "scene_001.mp4"
    broken.write_bytes(b"not actually mp4")

    sp = {"scenes": [{"lines": []}, {"lines": []}]}

    with pytest.raises(RuntimeError, match="シーン動画が破損"):
        scene_gen.collect_scene_videos(sp, str(tmp_path))


def test_collect_scene_videos_passes_when_all_valid(tmp_path):
    """全 scene_<i>.mp4 が valid なら例外を出さず順序通り返す。"""
    for i in range(2):
        _make_tiny_mp4(str(tmp_path / f"scene_{i:03d}.mp4"))

    sp = {"scenes": [{"lines": []}, {"lines": []}]}
    paths = scene_gen.collect_scene_videos(sp, str(tmp_path))
    assert len(paths) == 2
    assert paths[0].endswith("scene_000.mp4")
    assert paths[1].endswith("scene_001.mp4")


# ──────────────── run_overlay cleanup ────────────────

def test_run_overlay_cleans_partial_outputs_on_failure(tmp_path, monkeypatch):
    """_apply_overlays が落ちたら merged.mp4 / overlaid.mp4 / output reels が
    残らずに消える (= 再開時に古い中間が紛れない)。"""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr(config, "OUTPUT_DIR", str(out_dir))

    ts_path = tmp_path / "ts"
    ts_path.mkdir()
    ts = ts_path.name

    # scene_000.mp4 を 1 本用意 + tts_full / progress を整えて scene を approved に
    scene_path = ts_path / "scene_000.mp4"
    _make_tiny_mp4(str(scene_path))

    # progress_store: script/tts/bg/kling/scene まで approved にして overlay を通す
    for stage in ("script", "tts", "bg", "kling", "scene"):
        progress_store.mark_generated(str(ts_path), stage)
        progress_store.mark_approved(str(ts_path), stage)

    sp = {
        "caption": "test",
        "scenes": [{
            "duration": 0.5,
            "background_prompt": "x",
            "animation_prompt": "y",
            "lines": [],
        }],
    }

    # _merge_scenes は成功させ、_apply_overlays だけ失敗させる
    fake_merge_path = str(ts_path / "merged.mp4")
    _make_tiny_mp4(fake_merge_path)

    monkeypatch.setattr(staged_pipeline, "_merge_scenes",
                        lambda *a, **kw: fake_merge_path)

    def boom(*a, **kw):
        # overlaid を一部書いてから落とす (= partial 模擬)
        out_path = a[3] if len(a) >= 4 else kw["output_path"]
        with open(out_path, "wb") as f:
            f.write(b"PARTIAL")
        raise RuntimeError("overlay boom")

    monkeypatch.setattr(staged_pipeline, "_apply_overlays", boom)
    # scene_videos collect も pass させる
    monkeypatch.setattr(scene_gen, "collect_scene_videos",
                        lambda sp, ts_path: [str(scene_path)])

    output_reels = out_dir / f"reels_{ts}.mp4"
    overlaid = ts_path / "overlaid.mp4"
    merged = ts_path / "merged.mp4"

    with pytest.raises(RuntimeError, match="overlay boom"):
        staged_pipeline.run_overlay(sp, "test_screenplay", str(ts_path))

    assert not output_reels.exists(), "output reels が残ってはいけない"
    assert not overlaid.exists(), "overlaid.mp4 が残ってはいけない"
    assert not merged.exists(), "merged.mp4 が残ってはいけない"


# ──────────────── preflight disk space ────────────────

def test_check_disk_space_raises_when_below_threshold(monkeypatch):
    """disk 空きが閾値未満なら PreflightError。"""
    Usage = namedtuple("usage", ["total", "used", "free"])
    monkeypatch.setattr(preflight.shutil, "disk_usage",
                        lambda p: Usage(100, 99, 10 * 1024 * 1024))  # 10MB

    with pytest.raises(preflight.PreflightError, match="空き容量が不足"):
        preflight.check_disk_space(100 * 1024 * 1024)  # 100MB 必要


def test_check_disk_space_passes_when_above_threshold(monkeypatch):
    """十分な空きがあれば例外を出さない。"""
    Usage = namedtuple("usage", ["total", "used", "free"])
    monkeypatch.setattr(preflight.shutil, "disk_usage",
                        lambda p: Usage(100, 1, 10 * 1024 * 1024 * 1024))

    preflight.check_disk_space(1 * 1024 * 1024 * 1024)  # 1GB 必要


def test_check_bg_includes_disk_check(monkeypatch):
    """check_bg は env チェック後に disk space も検査する (新規 regression)。"""
    monkeypatch.setattr(config, "GOOGLE_API_KEY", "fake-key")
    Usage = namedtuple("usage", ["total", "used", "free"])
    monkeypatch.setattr(preflight.shutil, "disk_usage",
                        lambda p: Usage(100, 99, 1024))  # 1KB

    with pytest.raises(preflight.PreflightError, match="空き容量が不足"):
        preflight.check_bg()


def test_disk_check_skips_silently_on_oserror(monkeypatch):
    """disk_usage が OSError を投げた場合は warning を出して通す
    (= 検査の不能で停止させない)。"""
    def boom(p):
        raise OSError("read-only or detached fs")
    monkeypatch.setattr(preflight.shutil, "disk_usage", boom)

    preflight.check_disk_space(1024 * 1024 * 1024)  # 例外なし
