"""動画のシーン/サブショット境界を検出する。

優先順序:
  1. PySceneDetect (`pip install scenedetect[opencv]`) — 推奨
  2. ffmpeg select=gt(scene) フォールバック — PySceneDetectが無くても動く
"""
import json
import logging
import re
import subprocess

logger = logging.getLogger(__name__)


def _detect_with_pyscenedetect(video_path: str, threshold: float = 27.0) -> list[dict] | None:
    try:
        from scenedetect import detect, ContentDetector
    except ImportError:
        return None

    logger.info("PySceneDetectでショット境界検出中 (threshold=%.1f)", threshold)
    scenes = detect(video_path, ContentDetector(threshold=threshold))
    return [
        {
            "start": float(start.get_seconds()),
            "end": float(end.get_seconds()),
            "duration": float(end.get_seconds() - start.get_seconds()),
        }
        for start, end in scenes
    ]


def _detect_with_ffmpeg(video_path: str, threshold: float = 0.3) -> list[dict] | None:
    """ffmpegの`select='gt(scene,0.3)'`フィルタでシーン変化を検出。"""
    logger.info("ffmpeg scene detect実行中 (threshold=%.2f)", threshold)
    cmd = [
        "ffmpeg", "-i", video_path,
        "-filter:v", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 and "showinfo" not in (r.stderr or ""):
        logger.warning("ffmpeg scene detect失敗: %s", r.stderr[-300:])
        return None

    times = []
    for line in (r.stderr or "").splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            times.append(float(m.group(1)))
    if not times:
        return []

    duration = _ffprobe_duration(video_path)
    boundaries = [0.0] + times + [duration]
    scenes = []
    for i in range(len(boundaries) - 1):
        s = boundaries[i]
        e = boundaries[i + 1]
        if e - s > 0.3:
            scenes.append({
                "start": round(s, 3),
                "end": round(e, 3),
                "duration": round(e - s, 3),
            })
    return scenes


def _ffprobe_duration(video_path: str) -> float:
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
           "-show_format", video_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return float(json.loads(r.stdout)["format"]["duration"])


def detect_shots(video_path: str, threshold: float = 27.0) -> list[dict]:
    """ショット境界を検出し、各ショットの (start, end, duration) を返す。"""
    result = _detect_with_pyscenedetect(video_path, threshold)
    if result is not None:
        return result
    logger.info("PySceneDetect未インストール → ffmpegフォールバック")
    result = _detect_with_ffmpeg(video_path)
    return result or []


def shots_within(shots: list[dict], start: float, end: float) -> list[dict]:
    """与えられたshotリストから、指定区間内に重なるshotだけを抽出。"""
    out: list[dict] = []
    for s in shots:
        if s["end"] <= start or s["start"] >= end:
            continue
        clipped_start = max(s["start"], start) - start
        clipped_end = min(s["end"], end) - start
        if clipped_end - clipped_start > 0.2:
            out.append({
                "start": round(clipped_start, 3),
                "duration": round(clipped_end - clipped_start, 3),
                "global_start": s["start"],
                "global_end": s["end"],
            })
    return out
