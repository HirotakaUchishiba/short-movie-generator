"""Phase 2: TTS audio の silence / 音量不足を per-line で検出する。

Phase 1 の `validators_provisional.check_tts_audio` を per-line に分解。
返り値が ``ValidationResult`` の list なので、auto_loop が「シーン X の
line Y だけ regen」できる粒度を提供する。

しきい値は Phase 1 から少し厳しめ (= Phase 0/1 で蓄積した qa_failures から
将来的に baseline する前提の暫定値)。
"""
from __future__ import annotations

import glob
import logging
import os
import re
import subprocess

from qa.validators.base import (
    ValidationResult,
    failed_result,
    passed_result,
)

logger = logging.getLogger(__name__)

SILENCE_RATIO_FAIL = 0.4
MEAN_VOLUME_DB_FAIL = -45.0

_MEAN_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
_SIL_DUR_RE = re.compile(r"silence_duration:\s*(\d+(?:\.\d+)?)")
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_TTS_FILE_RE = re.compile(r"tts_(\d+)_(\d+)\.mp3$")


def _ffmpeg_stderr(args: list[str], timeout: int = 60) -> str:
    proc = subprocess.run(
        ["ffmpeg", *args],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    return (proc.stderr or "") + (proc.stdout or "")


def _parse_duration(text: str) -> float:
    m = _DURATION_RE.search(text)
    if not m:
        return 0.0
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


def _validate_one(mp3_path: str, scene_idx: int,
                  line_idx: int) -> ValidationResult:
    try:
        out = _ffmpeg_stderr([
            "-hide_banner", "-i", mp3_path,
            "-af", "volumedetect,silencedetect=noise=-50dB:d=0.3",
            "-f", "null", "-",
        ])
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return failed_result(
            score=0.0, reason=f"ffmpeg failed: {e}",
            tag="audio_silence",
            scene_idx=scene_idx, line_idx=line_idx,
        )
    duration = _parse_duration(out)
    mean_match = _MEAN_RE.search(out)
    mean_db = float(mean_match.group(1)) if mean_match else -100.0
    silence_total = sum(float(d) for d in _SIL_DUR_RE.findall(out))
    silence_ratio = (silence_total / duration) if duration > 0 else 0.0
    metrics = {
        "duration_sec": duration,
        "mean_volume_db": mean_db,
        "silence_ratio": silence_ratio,
    }
    reasons: list[str] = []
    if mean_db < MEAN_VOLUME_DB_FAIL:
        reasons.append(f"mean_volume={mean_db:.1f}dB")
    if silence_ratio > SILENCE_RATIO_FAIL:
        reasons.append(f"silence_ratio={silence_ratio:.2%}")
    if reasons:
        return failed_result(
            score=0.0, reason="; ".join(reasons),
            tag="audio_silence", metrics=metrics,
            scene_idx=scene_idx, line_idx=line_idx,
        )
    return passed_result(
        score=max(0.0, 1.0 - silence_ratio),
        metrics=metrics,
        scene_idx=scene_idx, line_idx=line_idx,
    )


def check_audio_silence(ts_path: str, **_) -> list[ValidationResult]:
    """``ts_path`` 配下の全 ``tts_<S>_<L>.mp3`` を per-line で検査する。"""
    out: list[ValidationResult] = []
    for mp3 in sorted(glob.glob(os.path.join(ts_path, "tts_*_*.mp3"))):
        m = _TTS_FILE_RE.search(mp3)
        if not m:
            continue
        scene_idx = int(m.group(1))
        line_idx = int(m.group(2))
        out.append(_validate_one(mp3, scene_idx, line_idx))
    return out
