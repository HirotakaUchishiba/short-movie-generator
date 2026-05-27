"""Stage bgm の ffmpeg BGM ミックス helper (純粋関数、staged_pipeline 非依存)。

overlaid.mp4 (TTS + 字幕) に BGM をミックスして reels を書く。BGM は volume 倍 +
頭尾フェード + 動画長までループ (-stream_loop)。ducking ON なら
sidechaincompress で発話中 BGM を下げる。映像は copy (再エンコードなし)。
詳細は docs/plannings/2026-05-27_bgm-overlay-stage.md。
"""
from __future__ import annotations

import json
import logging
import subprocess

import config

logger = logging.getLogger(__name__)


def _duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", path],
        capture_output=True, text=True,
    )
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return 0.0


def mix_bgm(
    video_in: str,
    bgm_path: str,
    video_out: str,
    *,
    volume: float,
    ducking: bool,
) -> None:
    """video_in の音声に BGM をミックスして video_out を書く。

    - BGM は ``-stream_loop -1`` で無限ループ input にし、atrim で動画長に切る
      (BGM が動画より短くてもループ、長くても切る)。
    - volume 倍 + afade (頭 BGM_FADE_IN_SEC / 尾 BGM_FADE_OUT_SEC)。
    - ducking かつ config.BGM_DUCKING_ENABLED なら sidechaincompress で
      TTS ([0:a]) を sidechain に BGM を圧縮 (発話中 BGM を下げる)。
    - 映像は ``-c:v copy`` で再エンコードしない。
    """
    dur = _duration(video_in)
    fade_out_st = max(0.0, dur - config.BGM_FADE_OUT_SEC)

    bgm_chain = (
        f"[1:a]atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,"
        f"volume={volume:.3f},"
        f"afade=t=in:st=0:d={config.BGM_FADE_IN_SEC:.3f},"
        f"afade=t=out:st={fade_out_st:.3f}:d={config.BGM_FADE_OUT_SEC:.3f}[bgm]"
    )

    if ducking and config.BGM_DUCKING_ENABLED:
        filter_complex = (
            f"{bgm_chain};"
            f"[0:a]asplit=2[sc][voice];"
            f"[bgm][sc]sidechaincompress="
            f"threshold={config.BGM_DUCKING_THRESHOLD}:"
            f"ratio={config.BGM_DUCKING_RATIO}:"
            f"attack={config.BGM_DUCKING_ATTACK_MS}:"
            f"release={config.BGM_DUCKING_RELEASE_MS}[bgmduck];"
            f"[voice][bgmduck]amix=inputs=2:duration=first:"
            f"dropout_transition=0:normalize=0[aout]"
        )
    else:
        filter_complex = (
            f"{bgm_chain};"
            f"[0:a][bgm]amix=inputs=2:duration=first:"
            f"dropout_transition=0:normalize=0[aout]"
        )

    cmd = [
        "ffmpeg", "-y",
        "-i", video_in,
        "-stream_loop", "-1", "-i", bgm_path,
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        video_out,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"BGM mix failed: {r.stderr[-600:]}")
    logger.info("[bgm] mix 完了: %s (volume=%.2f ducking=%s)",
                video_out, volume, ducking)
