"""TTS生成済み音声から、視覚プロンプト用の軽量な dynamics サマリを抽出する。

役割:
    Stage 2 (TTS) で確定した per-line 音声 (`tts_<S>_<L>.mp3`) を librosa で解析し、
    BG/Kling 生成時に **追加でプロンプトに乗せる** ための短い分類ラベル群を返す。

    Claude を呼ばずに、TTS の実音響変化を視覚に反映させるための層。

抽出指標:
    - intensity      : weak | moderate | strong  (RMS ピークから)
    - speed          : slow | medium | fast      (発話秒数 ÷ 文字数)
    - pitch_trend    : rising | falling | flat   (audio_features 由来)
    - silence_pattern: fluent | with_pauses | broken (line内の無音区間数)
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def _ffprobe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True,
        )
        s = r.stdout.strip()
        return float(s) if s else 0.0
    except Exception:
        return 0.0


def _classify_intensity(rms_peak: float) -> str:
    if rms_peak < 0.30:
        return "weak"
    if rms_peak > 0.55:
        return "strong"
    return "moderate"


def _classify_speed(text: str, duration_sec: float) -> str:
    if duration_sec <= 0:
        return "medium"
    chars = len(re.sub(r"\s+", "", text or ""))
    if chars == 0:
        return "medium"
    char_per_sec = chars / duration_sec
    if char_per_sec < 4.0:
        return "slow"
    if char_per_sec > 8.0:
        return "fast"
    return "medium"


def _classify_silence_pattern(audio_path: str, total_dur: float) -> str:
    """line 内の無音区間数で fluency を分類。"""
    try:
        cmd = [
            "ffmpeg", "-hide_banner", "-i", audio_path,
            "-af", "silencedetect=noise=-40dB:d=0.15",
            "-f", "null", "-",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        n_silences = r.stderr.count("silence_start:")
    except Exception:
        n_silences = 0

    if total_dur < 1.0:
        return "fluent"
    if n_silences == 0:
        return "fluent"
    if n_silences <= 2:
        return "with_pauses"
    return "broken"


def extract_line_dynamics(audio_path: str, text: str = "") -> dict[str, Any]:
    """1 line の audio から軽量 dynamics ラベルを抽出する。"""
    if not os.path.exists(audio_path):
        return {}

    duration = _ffprobe_duration(audio_path)
    if duration <= 0:
        return {}

    # pitch / rms は audio_features (librosa) を流用
    try:
        import audio_features
        feats = audio_features.extract_phrase_features(audio_path, 0.0, duration)
    except Exception as e:
        logger.warning("audio_features 抽出失敗: %s", e)
        feats = {}

    pitch_trend = feats.get("pitch_trend", "flat")
    rms_peak = float(feats.get("rms_peak", 0.0))

    return {
        "intensity": _classify_intensity(rms_peak),
        "speed": _classify_speed(text, duration),
        "pitch_trend": pitch_trend,
        "silence_pattern": _classify_silence_pattern(audio_path, duration),
        "duration": round(duration, 3),
    }


def summarize_scene_dynamics(
    scene_lines: list[dict],
    ts_path: str,
    s_idx: int,
) -> str:
    """シーン内の per-line dynamics を 1 行の prompt 断片にまとめる。

    例:
        "audio dynamics arc: line0 [strong fast rising fluent], "
        "line1 [moderate medium flat with_pauses]"

    BG/Kling 生成時に prompt 末尾に追加することで、TTS の実音響変化を反映させる。
    """
    rows: list[str] = []
    for l_idx, line in enumerate(scene_lines or []):
        path = os.path.join(ts_path, f"tts_{s_idx:03d}_{l_idx:03d}.mp3")
        if not os.path.exists(path):
            continue
        d = extract_line_dynamics(path, line.get("text", ""))
        if not d:
            continue
        bits = [d["intensity"], d["speed"], d["pitch_trend"], d["silence_pattern"]]
        rows.append(f"line{l_idx} [{' '.join(bits)}]")
    if not rows:
        return ""
    return "audio dynamics arc: " + ", ".join(rows)
