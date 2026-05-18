"""scene_gen.py から audio 編集 helper を切り出した module。

将来 PR で _extract_audio_segment / _concat_audios_to_mp3 /
_apply_silenceremove_inplace / _detect_all_silences 等も同 module に
集約する (= 計画書 §3.1.1-d 段階移行)。

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.1.1
"""

from __future__ import annotations

import os
import subprocess as sp

import config


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
