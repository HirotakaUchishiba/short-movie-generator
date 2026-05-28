"""Stage se の ffmpeg 効果音ミックス helper (純粋関数、staged_pipeline 非依存)。

overlaid.mp4 (TTS + 字幕) に効果音を指定時刻へ重ねて reels を書く。各 SE は
adelay で配置時刻にずらし volume 倍 + stereo/44100 に整えてから動画音声に amix する
(normalize=0 で元音量維持、duration=first で動画長に固定)。映像は copy。
"""
from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


def mix_se(
    video_in: str,
    placements: list[tuple],
    video_out: str,
) -> None:
    """video_in の音声に効果音を重ねて video_out を書く。

    placements は ``(se_path, time_sec, volume)`` の list (time_sec は動画先頭からの
    絶対秒)。各 SE を ``adelay`` で配置時刻にずらし volume 倍、stereo/44100 に整えて
    から ``[0:a]`` と ``amix`` (normalize=0 / duration=first)。映像は ``-c:v copy``。
    placements が空なら ValueError (= 呼び出し側が pass-through する想定)。
    """
    if not placements:
        raise ValueError("placements is empty")

    se_chains = []
    amix_labels = ["[0:a]"]
    for i, p in enumerate(placements):
        t, vol = p[1], p[2]
        clip_start = p[3] if len(p) > 3 else None
        clip_end = p[4] if len(p) > 4 else None
        ms = max(0, int(round(t * 1000)))
        label = f"se{i}"
        # clip 指定があれば atrim で SE 音源を切り出してから配置 (= trim)。
        trim = (
            f"atrim={clip_start:.3f}:{clip_end:.3f},asetpts=PTS-STARTPTS,"
            if clip_start is not None and clip_end is not None
            else ""
        )
        se_chains.append(
            f"[{i + 1}:a]{trim}adelay={ms}:all=1,volume={vol:.3f},"
            f"aformat=channel_layouts=stereo:sample_rates=44100[{label}]"
        )
        amix_labels.append(f"[{label}]")

    filter_complex = (
        ";".join(se_chains) + ";"
        + "".join(amix_labels)
        + f"amix=inputs={len(amix_labels)}:duration=first:"
        f"dropout_transition=0:normalize=0[aout]"
    )

    cmd = ["ffmpeg", "-y", "-i", video_in]
    for p in placements:
        cmd += ["-i", p[0]]
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        video_out,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"SE mix failed: {r.stderr[-600:]}")
    logger.info("[se] mix 完了: %s (%d SE)", video_out, len(placements))
