"""scene_gen.py から ffmpeg / ffprobe を直接叩く小 helper を切り出した module。

将来 PR で _trim_video / _extract_audio_segment / _concat_audios_* 等の
大きい ffmpeg helper も本 module に集約する (= 計画書 §3.1.1-c 段階移行)。

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.1.1
"""

from __future__ import annotations

import json
import subprocess as sp


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
