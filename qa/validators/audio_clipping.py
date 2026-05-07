"""Phase 2: TTS audio の clipping (= 音割れ) を peak amplitude で検出する。

librosa があれば PCM サンプルから真の peak を計算、無ければ ffmpeg
volumedetect の max_volume にフォールバックする (= dev / CI 環境で
重い ML 依存を強制しないため)。
"""
from __future__ import annotations

import glob
import logging
import math
import os
import re
import subprocess

from qa.validators.base import (
    ValidationResult,
    failed_result,
    passed_result,
)

logger = logging.getLogger(__name__)

CLIP_PEAK_DBFS_FAIL = -0.1
_MAX_VOL_RE = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
_TTS_FILE_RE = re.compile(r"tts_(\d+)_(\d+)\.mp3$")


def _peak_dbfs_via_librosa(mp3_path: str) -> float:
    import librosa  # type: ignore[import-not-found]
    y, _sr = librosa.load(mp3_path, sr=None, mono=True)
    if len(y) == 0:
        return -100.0
    peak = float(max(abs(y.max()), abs(y.min())))
    if peak <= 0:
        return -100.0
    return 20.0 * math.log10(peak)


def _peak_dbfs_via_ffmpeg(mp3_path: str) -> float:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", mp3_path,
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=False, timeout=30,
    )
    out = proc.stderr or ""
    m = _MAX_VOL_RE.search(out)
    return float(m.group(1)) if m else -100.0


def _peak_dbfs(mp3_path: str) -> float:
    try:
        return _peak_dbfs_via_librosa(mp3_path)
    except (ImportError, ModuleNotFoundError):
        return _peak_dbfs_via_ffmpeg(mp3_path)


def check_audio_clipping(ts_path: str, **_) -> list[ValidationResult]:
    out: list[ValidationResult] = []
    for mp3 in sorted(glob.glob(os.path.join(ts_path, "tts_*_*.mp3"))):
        m = _TTS_FILE_RE.search(mp3)
        if not m:
            continue
        scene_idx = int(m.group(1))
        line_idx = int(m.group(2))
        try:
            peak_db = _peak_dbfs(mp3)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            out.append(failed_result(
                score=0.0, reason=f"clipping check failed: {e}",
                tag="audio_clipping",
                scene_idx=scene_idx, line_idx=line_idx,
            ))
            continue
        metrics = {"peak_dbfs": peak_db}
        if peak_db > CLIP_PEAK_DBFS_FAIL:
            # 6 dB を超えると score=0 で完全 fail。境界 (-0.1 dBFS) で
            # score≈1.0、+5.9 dBFS で score≈0。
            severity = (peak_db - CLIP_PEAK_DBFS_FAIL) / 6.0
            out.append(failed_result(
                score=max(0.0, 1.0 - severity),
                reason=f"peak={peak_db:.2f}dBFS > {CLIP_PEAK_DBFS_FAIL}",
                tag="audio_clipping", metrics=metrics,
                scene_idx=scene_idx, line_idx=line_idx,
            ))
        else:
            out.append(passed_result(
                score=1.0,
                metrics=metrics,
                scene_idx=scene_idx, line_idx=line_idx,
            ))
    return out
