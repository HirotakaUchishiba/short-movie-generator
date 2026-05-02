"""参考動画から screenplay JSON を生成する純粋関数フロー。

CLI ラッパー (scripts/analyze_video.py) と UI ジョブ runner
(preview_server から呼ばれる) の両方が同じ run() を共有する。

各フェーズは on_progress(event, data) コールバックで境界を発信し、
入力 sha256 ベースの content-addressed cache (analyze.cache) で
再分析時の再計算をスキップする。

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
from analyze import cache as _cache
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
# (frame_count, transcript, shot_count, known_furigana_count) -> proceed_with_claude
CostGate = Callable[[int, dict, int, int], bool]


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


def _emit_skip(cb: ProgressCallback | None, phase: str, reason: str) -> None:
    """スキップしたフェーズを明示的に通知する。

    skip しても phase_skipped を発火することで、SQLite / SSE / UI の
    三層すべてで "skipped" 状態を表現できる (発火がないと pending のまま
    取り残されて永遠に終わらないように見える問題への対処)。
    """
    _emit(cb, "phase_skipped", {"phase": phase, "reason": reason})


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


# screenplay_validator が要求する最低 scene duration。
# Kling V3 が 5 秒生成 -> trim する制約と整合 (3 秒未満は実用的でない)。
MIN_SCENE_DURATION = 3.0


def _ensure_min_duration(screenplay: dict,
                          min_sec: float = MIN_SCENE_DURATION) -> int:
    """SYSTEM_PROMPT の指示に反して Claude が出した短すぎるシーンを底上げする。

    duration < min_sec のシーンを min_sec に切り上げ、line.start / line.end が
    新しい duration を超えていれば clamp する。

    Returns:
        補正したシーン数。
    """
    n = 0
    for scene in screenplay.get("scenes") or []:
        d = scene.get("duration")
        if not isinstance(d, (int, float)) or d >= min_sec:
            continue
        scene["duration"] = float(min_sec)
        for line in scene.get("lines") or []:
            for k in ("start", "end"):
                v = line.get(k)
                if isinstance(v, (int, float)) and v > min_sec:
                    line[k] = float(min_sec)
        n += 1
    return n


def run(
    *,
    video_path: str,
    output_path: str | None = None,
    options: AnalyzeOptions | None = None,
    work_dir: str | None = None,
    keep_tmp: bool = False,
    on_progress: ProgressCallback | None = None,
    cancel_token: CancelToken | None = None,
    on_cost_gate: CostGate | None = None,
    use_cache: bool = True,
) -> dict:
    """参考動画から screenplay JSON を生成する。

    フェーズ順 (各境界で on_progress("phase_start"|"phase_complete", {phase, ...})):
        frames → audio → whisper → acoustic → bgm_detect
        → shots (optional) → bgm_separate (optional) → claude → save

    Args:
        video_path: 入力動画パス
        output_path: 出力 JSON パス。None なら screenplays/auto_<stem>.json
        options: 実行オプション (fps / instructions / no_bgm_extract / no_shots)
        work_dir: 中間ファイルの作業ディレクトリ。None なら tempfile で確保
        keep_tmp: True なら work_dir を削除しない
        on_progress: フェーズ進捗コールバック
        cancel_token: 各フェーズ境界で呼ばれ、True を返すと AnalyzeCancelled
        use_cache: False なら content-addressed cache を一切使わない

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

        # ─── Phase: frames (cache: video_sha + fps) ──────
        _emit(on_progress, "phase_start", {"phase": "frames"})
        video_sha = _cache.file_sha256(video_path)
        restored = _cache.restore_frames(video_sha, options.fps, frames_dir) if use_cache else None
        if restored is not None:
            frame_paths = restored
            _emit(on_progress, "phase_complete", {
                "phase": "frames",
                "frame_count": len(frame_paths),
                "from_cache": True,
            })
        else:
            frame_paths = _extract_frames(video_path, options.fps, frames_dir)
            if use_cache:
                _cache.store_frames(video_sha, options.fps, frames_dir)
            _emit(on_progress, "phase_complete", {
                "phase": "frames",
                "frame_count": len(frame_paths),
                "from_cache": False,
            })
        _check_cancel(cancel_token)

        transcript: dict = {"text": "", "segments": [], "words": [], "duration": 0.0}
        phrase_features: list[dict] = []
        bgm_info: dict | None = None
        has_audio = _has_audio_stream(video_path)
        audio_sha: str | None = None

        if has_audio:
            # ─── Phase: audio (cache 対象外) ─────────
            _emit(on_progress, "phase_start", {"phase": "audio"})
            _extract_audio(video_path, audio_path)
            audio_sha = _cache.file_sha256(audio_path)
            _emit(on_progress, "phase_complete", {"phase": "audio"})
            _check_cancel(cancel_token)

            # ─── Phase: whisper (cache: audio_sha) ───
            _emit(on_progress, "phase_start", {"phase": "whisper"})
            cached = _cache.get_json("transcript", audio_sha) if use_cache else None
            if cached is not None:
                transcript = cached
                from_cache = True
            else:
                transcript = transcribe(audio_path, language=config.LANGUAGE)
                if use_cache:
                    _cache.put_json("transcript", audio_sha, transcript)
                from_cache = False
            _emit(on_progress, "phase_complete", {
                "phase": "whisper",
                "segments": len(transcript["segments"]),
                "words": len(transcript["words"]),
                "duration_sec": transcript["duration"],
                "from_cache": from_cache,
            })
            _check_cancel(cancel_token)

            # ─── Phase: acoustic (cache: audio_sha + segments_sig) ──
            _emit(on_progress, "phase_start", {"phase": "acoustic"})
            ac_key = _cache.acoustic_key(audio_sha, transcript)
            cached_ac = _cache.get_json("acoustic", ac_key) if use_cache else None
            if cached_ac is not None:
                phrase_features = cached_ac.get("features", [])
                from_cache = True
            else:
                for seg in transcript["segments"]:
                    feat = extract_phrase_features(audio_path, seg["start"], seg["end"])
                    feat["wpm"] = wpm_from_text(seg["text"], seg["end"] - seg["start"])
                    phrase_features.append(feat)
                if use_cache:
                    _cache.put_json("acoustic", ac_key, {"features": phrase_features})
                from_cache = False
            _emit(on_progress, "phase_complete", {
                "phase": "acoustic",
                "count": len(phrase_features),
                "from_cache": from_cache,
            })
            _check_cancel(cancel_token)

            # ─── Phase: bgm_detect (cache: audio_sha) ────
            _emit(on_progress, "phase_start", {"phase": "bgm_detect"})
            cached_bgm = _cache.get_json("bgm", audio_sha) if use_cache else None
            if cached_bgm is not None:
                bgm_info = cached_bgm
                from_cache = True
            else:
                bgm_info = has_background_music(audio_path)
                if use_cache:
                    _cache.put_json("bgm", audio_sha, bgm_info)
                from_cache = False
            _emit(on_progress, "phase_complete", {
                "phase": "bgm_detect",
                "present": bgm_info.get("present"),
                "confidence": bgm_info.get("confidence", 0),
                "from_cache": from_cache,
            })
            _check_cancel(cancel_token)
        else:
            logger.warning("動画に音声ストリームがありません。silent modeで分析します")
            for skipped in ("audio", "whisper", "acoustic", "bgm_detect"):
                _emit_skip(on_progress, skipped, "音声ストリームなし")

        # ─── Phase: shots (optional, cache: video_sha) ───
        shot_boundaries: list[dict] = []
        if not options.no_shots:
            _emit(on_progress, "phase_start", {"phase": "shots"})
            cached_shots = _cache.get_json("shots", video_sha) if use_cache else None
            if cached_shots is not None:
                shot_boundaries = cached_shots.get("shots", [])
                from_cache = True
            else:
                shot_boundaries = shot_detector.detect_shots(video_path)
                if use_cache:
                    _cache.put_json("shots", video_sha, {"shots": shot_boundaries})
                from_cache = False
            _emit(on_progress, "phase_complete", {
                "phase": "shots",
                "count": len(shot_boundaries),
                "from_cache": from_cache,
            })
            _check_cancel(cancel_token)
        else:
            _emit_skip(on_progress, "shots", "--no-shots オプションでスキップ")

        # ─── Phase: bgm_separate (cache 対象外、assets/bgm/ に永続) ──
        bgm_present = bool(bgm_info and bgm_info.get("present"))
        if has_audio and bgm_present and not options.no_bgm_extract:
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
        else:
            if not has_audio:
                reason = "音声ストリームなし"
            elif not bgm_present:
                reason = "BGM 未検出"
            else:
                reason = "--no-bgm-extract オプションでスキップ"
            _emit_skip(on_progress, "bgm_separate", reason)

        # ─── Cost gate (Phase 5 で SSE 経由ユーザー confirm 待ち) ──
        known_furigana = furigana_store.load()
        if on_cost_gate is not None:
            proceed = on_cost_gate(
                len(frame_paths),
                transcript,
                len(shot_boundaries),
                len(known_furigana),
            )
            if not proceed:
                raise AnalyzeCancelled()
            _check_cancel(cancel_token)

        # ─── Phase: claude (cache 対象外、毎回呼ぶ) ──────
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

        # Claude が SYSTEM_PROMPT の指示を守らず duration<3 を出力するケースが
        # あるので、validate 前に底上げする。プロジェクト作成時の strict
        # validate (minimum: 3) を通せるようにするため。
        adjusted = _ensure_min_duration(screenplay)
        if adjusted:
            logger.info(
                "duration<%.1fs のシーンを %d 件補正しました (validator 制約)",
                MIN_SCENE_DURATION, adjusted,
            )

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
