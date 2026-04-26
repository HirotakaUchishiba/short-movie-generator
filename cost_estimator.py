import json
import logging
import math
import os
from typing import Any

import config

logger = logging.getLogger(__name__)

COST_PER_IMAGE = 0.134
COST_VIDEO_PER_SECOND = 0.084

DEFAULT_BG_SECONDS = 15.0
DEFAULT_VIDEO_SECONDS_PER_SEGMENT_SECOND = 6.0
DEFAULT_COMPOSE_SECONDS_PER_SEGMENT = 3.0
DEFAULT_AVG_SEGMENT_SECONDS = 4.0
DEFAULT_LIPSYNC_SECONDS_PER_SEGMENT_SECOND = 44.0

HISTORY_LIMIT = 20


def _load_history() -> list[dict[str, Any]]:
    if not os.path.exists(config.COST_HISTORY_PATH):
        return []
    entries: list[dict[str, Any]] = []
    with open(config.COST_HISTORY_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries[-HISTORY_LIMIT:]


def _calibrated_rates() -> dict[str, float]:
    history = _load_history()
    if not history:
        return {
            "bg_seconds": DEFAULT_BG_SECONDS,
            "video_seconds_per_segment_second": DEFAULT_VIDEO_SECONDS_PER_SEGMENT_SECOND,
            "compose_seconds_per_segment": DEFAULT_COMPOSE_SECONDS_PER_SEGMENT,
        }

    bg_rates = []
    video_rates = []
    compose_rates = []
    for e in history:
        actual = e.get("actual", {})
        n_bg = e.get("backgrounds", 0) or 0
        video_secs = e.get("video_seconds", 0) or 0
        n_units = e.get("scenes") or e.get("segments", 0) or 0
        time_video = actual.get("video_time", 0) or 0
        time_compose = actual.get("compose_time", 0) or 0

        if n_bg > 0 and time_video > 0 and video_secs > 0:
            bg_share = n_bg * DEFAULT_BG_SECONDS
            video_share = max(time_video - bg_share, 0.0)
            if video_share > 0:
                video_rates.append(video_share / video_secs)
            bg_rates.append(min(time_video / n_bg, DEFAULT_BG_SECONDS * 2))
        if n_units > 0 and time_compose > 0:
            compose_rates.append(time_compose / n_units)

    avg = lambda xs, fb: (sum(xs) / len(xs)) if xs else fb
    return {
        "bg_seconds": avg(bg_rates, DEFAULT_BG_SECONDS),
        "video_seconds_per_segment_second": avg(video_rates, DEFAULT_VIDEO_SECONDS_PER_SEGMENT_SECOND),
        "compose_seconds_per_segment": avg(compose_rates, DEFAULT_COMPOSE_SECONDS_PER_SEGMENT),
    }


def estimate(screenplay: dict) -> dict[str, Any]:
    scenes = screenplay.get("scenes", [])
    n_scenes = len(scenes)
    n_backgrounds = n_scenes
    silent = screenplay.get("audio_mode") == "silent"

    est_video_seconds = sum(
        max(3, math.ceil(float(sc.get("duration", DEFAULT_AVG_SEGMENT_SECONDS))))
        for sc in scenes
    )

    lipsync_seconds = 0
    if not silent and config.LIPSYNC_ENABLED:
        lipsync_seconds = sum(
            max(3, math.ceil(float(sc.get("duration", DEFAULT_AVG_SEGMENT_SECONDS))))
            for sc in scenes
            if sc.get("lipsync", True) and (sc.get("lines") or [])
        )

    rates = _calibrated_rates()
    est_time = (
        n_backgrounds * rates["bg_seconds"]
        + est_video_seconds * rates["video_seconds_per_segment_second"]
        + n_scenes * rates["compose_seconds_per_segment"]
        + lipsync_seconds * DEFAULT_LIPSYNC_SECONDS_PER_SEGMENT_SECOND
    )

    est_cost = (
        n_backgrounds * COST_PER_IMAGE
        + est_video_seconds * COST_VIDEO_PER_SECOND
        + lipsync_seconds * config.LIPSYNC_COST_PER_SECOND
    )

    return {
        "backgrounds": n_backgrounds,
        "scenes": n_scenes,
        "video_seconds": est_video_seconds,
        "lipsync_seconds": lipsync_seconds,
        "time_seconds": est_time,
        "cost_usd": est_cost,
        "rates": rates,
    }


def record(ts: str, screenplay: dict, actual: dict[str, Any],
           estimated: dict[str, Any]) -> None:
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    entry = {
        "ts": ts,
        "backgrounds": estimated["backgrounds"],
        "scenes": estimated["scenes"],
        "video_seconds": actual.get("video_seconds", estimated["video_seconds"]),
        "estimated": {
            "time_seconds": estimated["time_seconds"],
            "cost_usd": estimated["cost_usd"],
        },
        "actual": actual,
    }
    with open(config.COST_HISTORY_PATH, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def format_estimate(est: dict[str, Any]) -> str:
    minutes = est["time_seconds"] / 60
    lipsync_part = ""
    if est.get("lipsync_seconds", 0) > 0:
        lipsync_part = f" + リップシンク{est['lipsync_seconds']}秒"
    return (
        f"予想: 背景{est['backgrounds']}枚 × {est['rates']['bg_seconds']:.0f}秒 "
        f"+ 動画{est['video_seconds']}秒生成"
        f"{lipsync_part} "
        f"= 合計 {minutes:.1f}分 / ${est['cost_usd']:.2f}"
    )


def format_comparison(estimated: dict[str, Any], actual: dict[str, Any]) -> str:
    est_time = estimated["time_seconds"]
    act_time = actual.get("total_time", 0)
    est_cost = estimated["cost_usd"]
    act_cost = actual.get("total_cost", 0)

    time_diff_pct = ((act_time - est_time) / est_time * 100) if est_time else 0
    cost_diff_pct = ((act_cost - est_cost) / est_cost * 100) if est_cost else 0

    return (
        f"| 項目 | 予測 | 実績 | 差異 |\n"
        f"|------|------|------|------|\n"
        f"| 時間 | {est_time/60:.1f}分 | {act_time/60:.1f}分 | {time_diff_pct:+.1f}% |\n"
        f"| コスト | ${est_cost:.2f} | ${act_cost:.2f} | {cost_diff_pct:+.1f}% |\n"
    )
