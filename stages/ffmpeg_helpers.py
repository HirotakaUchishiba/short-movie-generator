"""scene_gen.py から ffmpeg / ffprobe を直接叩く小 helper を切り出した module。

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.1.1
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess as sp

logger = logging.getLogger(__name__)


def get_duration(path: str) -> float:
    """ffprobe で path の format duration (秒) を返す。"""
    result = sp.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", path],
        capture_output=True, text=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def apply_volume(input_path: str, db: float, output_path: str) -> None:
    """input_path の audio に音量補正 (db dB) を適用して output_path に書く。

    libmp3lame -q:a 4 で再エンコード。db は正負どちらも可 (例: +3.0 / -2.5)。
    """
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter:a", f"volume={db:+.1f}dB",
        "-c:a", "libmp3lame", "-q:a", "4",
        output_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Volume apply failed: {r.stderr[-300:]}")


def trim_video(input_path: str, duration: float, output_path: str) -> None:
    """input_path を duration 秒で切り詰めて output_path に書く (映像のみ、音声破棄)。"""
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Video trim failed: {r.stderr[-500:]}")


def extend_video_to_duration(
    input_path: str, target_duration: float, output_path: str,
) -> None:
    """slow_mo で映像を target_duration まで引き伸ばす (音声破棄)。

    setpts=PTS*ratio で全フレームを等倍にスローモーション化する。
    ratio < 1.0 + 1e-3 (= 既に十分長い) なら単純コピー。
    """
    cur = get_duration(input_path)
    if cur <= 0.0:
        raise RuntimeError(f"動画尺取得に失敗: {input_path}")

    ratio = target_duration / cur
    if ratio <= 1.0 + 1e-3:
        shutil.copyfile(input_path, output_path)
        return

    if ratio > 2.0:
        logger.warning(
            "slow_mo ratio が大きすぎます (%.2fx)。動画 %.2fs → %.2fs に延長します",
            ratio, cur, target_duration,
        )

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter_complex", f"[0:v]setpts=PTS*{ratio:.6f}[v]",
        "-map", "[v]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Video slow_mo extension failed: {r.stderr[-500:]}")


def replace_audio(video_path: str, audio_path: str, output_path: str) -> None:
    """video_path の映像 + audio_path の音声を結合して output_path に書く。"""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Audio replace failed: {r.stderr[-500:]}")
