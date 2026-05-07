"""Phase 1: 暫定 validator (= silence / 音量不足 / 黒フレーム検査)。

ffmpeg を subprocess で叩き、stderr の volumedetect / silencedetect /
blackdetect を regex でパースする。Phase 2 で多軸 validator スイートに
置き換えるが、Phase 1 ではまずこの 2 つで「明らかに壊れた成果物」を
auto_loop に発見させて retry する。

しきい値は Phase 0 の実データから baseline を取り直す前提で、ここでは
余裕を持った保守的な値に置く (= 直近 30 本の qa_failures から ROC で
チューニングするのは Phase 2 のタスク)。
"""
from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ───── しきい値 (Phase 2 で実データから baseline を取り直す)
SILENCE_RATIO_FAIL = 0.5
MEAN_VOLUME_DB_FAIL = -45.0
KLING_BLACK_RATIO_FAIL = 0.5

_MEAN_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
_MAX_RE = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
_SIL_DUR_RE = re.compile(r"silence_duration:\s*(\d+(?:\.\d+)?)")
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_BLACK_DURATION_RE = re.compile(r"black_duration:(\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class ValidationResult:
    """1 validator の判定。

    Attributes:
        passed: True なら ok、False なら fail。
        score: 0.0 (= 完全 fail) - 1.0 (= 完璧)。auto_loop の retry 順位付け用。
        reason: fail の場合の理由 (人間 / Slack 表示向け)。
        metrics: 検出した数値 (= silence_ratio / mean_volume_db / etc)。
    """
    passed: bool
    score: float
    reason: str
    metrics: dict[str, float] = field(default_factory=dict)


def _ffmpeg_run(args: list[str], timeout: int = 60) -> str:
    """ffmpeg を実行して stderr + stdout を結合して返す。

    volumedetect / silencedetect / blackdetect は stderr に出力される。
    """
    proc = subprocess.run(
        ["ffmpeg", *args],
        capture_output=True, text=True, timeout=timeout,
        check=False,
    )
    return (proc.stderr or "") + (proc.stdout or "")


def _parse_duration_sec(text: str) -> float:
    m = _DURATION_RE.search(text)
    if not m:
        return 0.0
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


def check_tts_audio(
    mp3_path: str,
    silence_noise_db: float = -50.0,
    min_silence_sec: float = 0.3,
) -> ValidationResult:
    """1 ファイルの TTS audio を volumedetect + silencedetect で検査する。

    fail 条件:
        - 全体平均音量 < ``MEAN_VOLUME_DB_FAIL``
        - silence の総和 / duration > ``SILENCE_RATIO_FAIL``
    """
    try:
        out = _ffmpeg_run([
            "-hide_banner", "-i", mp3_path,
            "-af",
            f"volumedetect,silencedetect=noise={silence_noise_db}dB:"
            f"d={min_silence_sec}",
            "-f", "null", "-",
        ])
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return ValidationResult(
            passed=False, score=0.0, reason=f"ffmpeg failed: {e}",
        )
    duration = _parse_duration_sec(out)
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
        reasons.append(f"mean_volume={mean_db:.1f}dB < {MEAN_VOLUME_DB_FAIL}")
    if silence_ratio > SILENCE_RATIO_FAIL:
        reasons.append(
            f"silence_ratio={silence_ratio:.2%} > {SILENCE_RATIO_FAIL:.0%}",
        )
    passed = not reasons
    score = max(0.0, min(1.0, 1.0 - silence_ratio)) if passed else 0.0
    return ValidationResult(
        passed=passed, score=score,
        reason="; ".join(reasons) or "ok",
        metrics=metrics,
    )


def check_kling_blackframes(
    mp4_path: str, min_black_sec: float = 0.3,
) -> ValidationResult:
    """Kling 動画で黒フレームの占める割合を検査する。

    fail 条件: 黒フレーム合計 / 動画長 > ``KLING_BLACK_RATIO_FAIL``。
    """
    try:
        out = _ffmpeg_run([
            "-hide_banner", "-i", mp4_path,
            "-vf", f"blackdetect=d={min_black_sec}:pix_th=0.10",
            "-an", "-f", "null", "-",
        ])
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return ValidationResult(
            passed=False, score=0.0, reason=f"ffmpeg failed: {e}",
        )
    duration = _parse_duration_sec(out)
    black_total = sum(float(d) for d in _BLACK_DURATION_RE.findall(out))
    black_ratio = (black_total / duration) if duration > 0 else 0.0

    metrics = {
        "duration_sec": duration,
        "black_ratio": black_ratio,
    }
    if black_ratio > KLING_BLACK_RATIO_FAIL:
        return ValidationResult(
            passed=False, score=0.0,
            reason=f"black_ratio={black_ratio:.2%} > {KLING_BLACK_RATIO_FAIL:.0%}",
            metrics=metrics,
        )
    return ValidationResult(
        passed=True, score=max(0.0, 1.0 - black_ratio),
        reason="ok", metrics=metrics,
    )
