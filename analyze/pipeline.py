"""参考動画から screenplay JSON を生成する純粋関数フロー。

CLI ラッパー (scripts/analyze_video.py) と UI ジョブ runner
(preview_server から呼ばれる) の両方が同じ run() を共有する。

各フェーズは on_progress(event, data) コールバックで境界を発信する。
cancel_token() が True を返すと AnalyzeCancelled が raise される。
"""
import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import config
import audio_separator
import furigana_store
import shot_detector
from audio_features import (
    extract_phrase_features,
    has_background_music,
    wpm_from_text,
)
from screenplay_validator import validate_screenplay
from video_analyzer import build_screenplay
from whisper_client import transcribe

logger = logging.getLogger(__name__)

DEFAULT_FPS = 2.0  # 0.5秒刻み

ProgressCallback = Callable[[str, dict[str, Any]], None]
CancelToken = Callable[[], bool]


class AnalyzeCancelled(Exception):
    """ジョブがキャンセル要求された時に raise される。"""


@dataclass
class AnalyzeOptions:
    """analyze pipeline の実行オプション。"""

    fps: float = DEFAULT_FPS
    instructions: str | None = None
    no_bgm_extract: bool = False
    no_shots: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AnalyzeOptions":
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in fields})


def _emit(cb: ProgressCallback | None, event: str, data: dict | None = None) -> None:
    if cb is None:
        return
    try:
        cb(event, dict(data or {}))
    except Exception:
        logger.exception("progress callback raised, ignoring")


def _check_cancel(token: CancelToken | None) -> None:
    if token is not None and token():
        raise AnalyzeCancelled()


def _extract_frames(video_path: str, fps: float, out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    pattern = os.path.join(out_dir, "frame_%04d.jpg")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps={fps},scale=882:-1",
        "-q:v", "3",
        pattern,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed: {r.stderr[-500:]}")
    return sorted(
        os.path.join(out_dir, f)
        for f in os.listdir(out_dir)
        if f.startswith("frame_") and f.endswith(".jpg")
    )


def _extract_audio(video_path: str, out_path: str) -> str:
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-ac", "1", "-ar", "16000",
        "-vn",
        out_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: {r.stderr[-500:]}")
    return out_path


def _has_audio_stream(video_path: str) -> bool:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a",
           "-show_entries", "stream=codec_type", "-of", "csv=p=0", video_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return "audio" in (r.stdout or "")


def default_output_path(video_path: str) -> str:
    """video_path から既定の出力先 screenplays/auto_<safe_stem>.json を返す。"""
    stem = Path(video_path).stem
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in stem)
    return str(Path(config.SCREENPLAYS_DIR) / f"auto_{safe}.json")


def _bgm_keep_path(video_path: str) -> str:
    stem = Path(video_path).stem
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in stem)
    bgm_dir = Path(config.BASE_DIR) / "assets" / "bgm"
    bgm_dir.mkdir(parents=True, exist_ok=True)
    return str(bgm_dir / f"{safe}_bgm.wav")


def run(
    *,
    video_path: str,
    output_path: str | None = None,
    options: AnalyzeOptions | None = None,
    work_dir: str | None = None,
    keep_tmp: bool = False,
    on_progress: ProgressCallback | None = None,
    cancel_token: CancelToken | None = None,
) -> dict:
    """参考動画から screenplay JSON を生成する。

    フェーズ順:
        frames → audio → whisper → acoustic → bgm_detect
        → shots (optional) → bgm_separate (optional) → claude → save

    各フェーズの境界で on_progress(event, data) を発信する:
        - ("phase_start",    {"phase": <name>, ...})
        - ("phase_complete", {"phase": <name>, ...})
        - ("completed",      {"output_path": ..., "scenes": ..., "lines": ..., "duration_sec": ...})

    Args:
        video_path: 入力動画パス (絶対 or 相対)
        output_path: 出力 JSON パス。None なら screenplays/auto_<stem>.json
        options: 実行オプション (fps / instructions / no_bgm_extract / no_shots)
        work_dir: 中間ファイルの作業ディレクトリ。None なら tempfile で確保
        keep_tmp: True なら work_dir を削除しない (cache 利用 / デバッグ用)
        on_progress: フェーズ進捗コールバック
        cancel_token: 各フェーズ境界で呼ばれ、True を返すと AnalyzeCancelled を raise

    Returns:
        生成された screenplay 辞書 (output_path にも書き出される)
    """
    options = options or AnalyzeOptions()
    video_path = os.path.abspath(video_path)
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"動画が見つかりません: {video_path}")

    if output_path is None:
        output_path = default_output_path(video_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if work_dir:
        os.makedirs(work_dir, exist_ok=True)
        cleanup_tmp = False
    else:
        work_dir = tempfile.mkdtemp(prefix="analyze_")
        cleanup_tmp = not keep_tmp
    logger.info("作業ディレクトリ: %s", work_dir)

    bgm_kept_path: str | None = None
    try:
        frames_dir = os.path.join(work_dir, "frames")
        audio_path = os.path.join(work_dir, "audio.wav")
        frame_interval_sec = 1.0 / options.fps

        # ─── Phase: frames ───────────────────────────
        _emit(on_progress, "phase_start", {"phase": "frames"})
        frame_paths = _extract_frames(video_path, options.fps, frames_dir)
        _emit(on_progress, "phase_complete", {
            "phase": "frames",
            "frame_count": len(frame_paths),
        })
        _check_cancel(cancel_token)

        transcript: dict = {"text": "", "segments": [], "words": [], "duration": 0.0}
        phrase_features: list[dict] = []
        bgm_info: dict | None = None
        has_audio = _has_audio_stream(video_path)

        if has_audio:
            # ─── Phase: audio ────────────────────────
            _emit(on_progress, "phase_start", {"phase": "audio"})
            _extract_audio(video_path, audio_path)
            _emit(on_progress, "phase_complete", {"phase": "audio"})
            _check_cancel(cancel_token)

            # ─── Phase: whisper ──────────────────────
            _emit(on_progress, "phase_start", {"phase": "whisper"})
            transcript = transcribe(audio_path, language=config.LANGUAGE)
            _emit(on_progress, "phase_complete", {
                "phase": "whisper",
                "segments": len(transcript["segments"]),
                "words": len(transcript["words"]),
                "duration_sec": transcript["duration"],
            })
            _check_cancel(cancel_token)

            # ─── Phase: acoustic ─────────────────────
            _emit(on_progress, "phase_start", {"phase": "acoustic"})
            for seg in transcript["segments"]:
                feat = extract_phrase_features(audio_path, seg["start"], seg["end"])
                feat["wpm"] = wpm_from_text(seg["text"], seg["end"] - seg["start"])
                phrase_features.append(feat)
            _emit(on_progress, "phase_complete", {
                "phase": "acoustic",
                "count": len(phrase_features),
            })
            _check_cancel(cancel_token)

            # ─── Phase: bgm_detect ───────────────────
            _emit(on_progress, "phase_start", {"phase": "bgm_detect"})
            bgm_info = has_background_music(audio_path)
            _emit(on_progress, "phase_complete", {
                "phase": "bgm_detect",
                "present": bgm_info.get("present"),
                "confidence": bgm_info.get("confidence", 0),
            })
            _check_cancel(cancel_token)
        else:
            logger.warning("動画に音声ストリームがありません。silent modeで分析します")

        # ─── Phase: shots (optional) ─────────────────
        shot_boundaries: list[dict] = []
        if not options.no_shots:
            _emit(on_progress, "phase_start", {"phase": "shots"})
            shot_boundaries = shot_detector.detect_shots(video_path)
            _emit(on_progress, "phase_complete", {
                "phase": "shots",
                "count": len(shot_boundaries),
            })
            _check_cancel(cancel_token)

        # ─── Phase: bgm_separate (optional) ──────────
        if has_audio and bgm_info and bgm_info.get("present") and not options.no_bgm_extract:
            _emit(on_progress, "phase_start", {"phase": "bgm_separate"})
            sep_dir = os.path.join(work_dir, "separated")
            sep = audio_separator.separate(audio_path, sep_dir)
            if sep:
                bgm_kept_path = _bgm_keep_path(video_path)
                shutil.copyfile(sep["no_vocals"], bgm_kept_path)
                _emit(on_progress, "phase_complete", {
                    "phase": "bgm_separate",
                    "method": sep["method"],
                    "output": bgm_kept_path,
                })
            else:
                _emit(on_progress, "phase_complete", {
                    "phase": "bgm_separate",
                    "method": None,
                    "skipped_reason": "demucs/HPSS両方失敗",
                })
            _check_cancel(cancel_token)

        # ─── Phase: claude ───────────────────────────
        known_furigana = furigana_store.load()
        _emit(on_progress, "phase_start", {
            "phase": "claude",
            "frame_count": len(frame_paths),
            "known_furigana_count": len(known_furigana),
        })
        screenplay = build_screenplay(
            frame_paths=frame_paths,
            transcript=transcript,
            phrase_features=phrase_features,
            source_video_path=video_path,
            extra_instructions=options.instructions,
            frame_interval_sec=frame_interval_sec,
            shot_boundaries=shot_boundaries,
            bgm_info=bgm_info,
            known_furigana=known_furigana,
        )
        _emit(on_progress, "phase_complete", {"phase": "claude"})
        _check_cancel(cancel_token)

        # ─── Phase: save ─────────────────────────────
        _emit(on_progress, "phase_start", {"phase": "save"})
        new_hints = furigana_store.collect_from_screenplay(screenplay)
        if new_hints:
            furigana_store.merge(new_hints)

        if bgm_kept_path:
            screenplay["bgm_path"] = bgm_kept_path
            screenplay.setdefault("bgm_volume_db", -18)

        errors = validate_screenplay(screenplay, strict=False)
        if errors:
            logger.warning("バリデーション警告:")
            for e in errors:
                logger.warning("  - %s", e)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(screenplay, f, ensure_ascii=False, indent=2)
        _emit(on_progress, "phase_complete", {
            "phase": "save",
            "output_path": output_path,
        })

        scenes_count = len(screenplay.get("scenes", []))
        lines_count = sum(len(s.get("lines") or []) for s in screenplay.get("scenes", []))
        total_duration = sum(s.get("duration", 0) for s in screenplay.get("scenes", []))
        _emit(on_progress, "completed", {
            "output_path": output_path,
            "scenes": scenes_count,
            "lines": lines_count,
            "duration_sec": total_duration,
        })
        return screenplay
    finally:
        if cleanup_tmp:
            shutil.rmtree(work_dir, ignore_errors=True)
