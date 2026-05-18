"""scene_gen.py から audio 編集 helper を切り出した module。

将来 PR で _apply_silenceremove_inplace / _detect_all_silences 等も同
module に集約する (= 計画書 §3.1.1-d 段階移行)。

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.1.1
"""

from __future__ import annotations

import os
import subprocess as sp

import config

# extract_audio_segment が duration を下限 clamp する閾値。
# scene_gen 側の MIN_SPEECH_DURATION_SEC と同値で運用する (= 1 箇所に集約)。
MIN_SPEECH_DURATION_SEC = 0.05


def natural_tail_silence_sec() -> float:
    """audio 末尾の自然な余白秒数 (= 全 line 共通、config.TTS_MAX_SILENCE_MS 由来)。

    上限 2.0 秒 / 下限 0.0 秒で clamp する (= TTS_MAX_SILENCE_MS が極端な値で
    上書きされても安全側に倒す)。
    """
    return max(0.0, min(2.0, float(config.TTS_MAX_SILENCE_MS) / 1000.0))


def apply_atempo_inplace(input_path: str, atempo: float) -> None:
    """ffmpeg atempo で速度補正 (in-place)。pitch 維持で時間軸のみ変化。

    atempo が 1.0 ± 0.001 以内なら何もしない (= 浮動小数誤差吸収)。
    """
    if abs(atempo - 1.0) < 0.001:
        return
    tmp_path = input_path + ".tempo.tmp.mp3"
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-af", f"atempo={atempo:.4f}",
        "-c:a", "libmp3lame", "-q:a", "4",
        tmp_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"atempo failed: {r.stderr[-500:]}")
    os.replace(tmp_path, input_path)


def extract_audio_segment(
    input_path: str, start_sec: float, duration: float,
    output_path: str, codec: str = "aac", bitrate: str = "192k",
) -> None:
    """ffmpeg で input_path から指定区間を切出して output_path に保存。

    -ss を -i の後ろに置く (output seeking) ことで frame-accurate なseekを保証。
    -ss を -i の前に置くと mp3 packet 境界 (~26ms) にスナップして語頭/語尾が削れる。
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-ss", f"{start_sec:.3f}",
        "-t", f"{max(duration, MIN_SPEECH_DURATION_SEC):.3f}",
        "-c:a", codec, "-b:a", bitrate,
        output_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {r.stderr[-500:]}")


def convert_to_aac(input_path: str, output_path: str,
                   bitrate: str = "192k") -> None:
    cmd = ["ffmpeg", "-y", "-i", input_path,
           "-c:a", "aac", "-b:a", bitrate, output_path]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"AAC convert failed: {r.stderr[-500:]}")


def concat_audios_to_aac(audio_paths: list[str], output_path: str) -> None:
    """複数 audio を ffmpeg で連結 → AAC m4a 出力。"""
    if not audio_paths:
        return
    if len(audio_paths) == 1:
        convert_to_aac(audio_paths[0], output_path)
        return
    inputs: list[str] = []
    for p in audio_paths:
        inputs.extend(["-i", p])
    chain = "".join(f"[{i}:a]" for i in range(len(audio_paths)))
    filter_str = f"{chain}concat=n={len(audio_paths)}:v=0:a=1[out]"
    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_str,
        "-map", "[out]",
        "-c:a", "aac", "-b:a", "192k",
        output_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Audio concat failed: {r.stderr[-500:]}")


def concat_audios_to_mp3(audio_paths: list[str], output_path: str) -> None:
    """複数 audio を ffmpeg で連結 → mp3 出力 (per-line speech body + trailing用)。"""
    if not audio_paths:
        return
    if len(audio_paths) == 1:
        os.replace(audio_paths[0], output_path)
        return
    inputs: list[str] = []
    for p in audio_paths:
        inputs.extend(["-i", p])
    chain = "".join(f"[{i}:a]" for i in range(len(audio_paths)))
    filter_str = f"{chain}concat=n={len(audio_paths)}:v=0:a=1[out]"
    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_str,
        "-map", "[out]",
        "-c:a", "libmp3lame", "-q:a", "4",
        output_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"mp3 concat failed: {r.stderr[-500:]}")
