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
import furigana_store
from analyze import cache as _cache
from audio_features import (
    extract_phrase_features,
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


# Claude Vision API の入力上限 (画像 100 枚 / 32MB ペイロード)。
# これを超えると 413 request_too_large が返るため、超過時は均等間引きする。
MAX_FRAMES_FOR_CLAUDE = 100


def _downsample_frames(frame_paths: list[str],
                        max_frames: int = MAX_FRAMES_FOR_CLAUDE,
                        ) -> list[str]:
    """フレーム数が max_frames を超えていたら均等間引きする。

    最初と最後のフレームを必ず含み、間を等間隔でサンプリングする。
    動画長 / fps から計算されるフレーム数が API 上限を超えるケース
    (例: 100 秒動画 + fps=2.0 = 200 枚) で 413 を未然に防ぐ。
    """
    n = len(frame_paths)
    if n <= max_frames:
        return frame_paths
    indices = [
        int(round(i * (n - 1) / (max_frames - 1))) for i in range(max_frames)
    ]
    return [frame_paths[i] for i in indices]


def _normalize_scene_pronunciation_hints(screenplay: dict) -> int:
    """scene 直下の pronunciation_hints を各 line に展開して scene からは削除する。

    Claude は SYSTEM_PROMPT の指示に反して scene 直下に
    pronunciation_hints を出すケースがあるため (シーン全体の読み方辞書を
    まとめる意図と思われる)、validator が scenes の additionalProperties:
    False で拒否する前にここで吸収する。

    line 個別の pronunciation_hints が既にある場合は line 側を優先する
    (より具体的な指定を尊重)。

    Returns: 正規化したシーン数。
    """
    n = 0
    for scene in screenplay.get("scenes") or []:
        scene_hints = scene.pop("pronunciation_hints", None)
        if not scene_hints or not isinstance(scene_hints, dict):
            continue
        n += 1
        for line in scene.get("lines") or []:
            existing = line.get("pronunciation_hints") or {}
            # scene 由来の hints は base、line 個別指定があれば line を優先
            line["pronunciation_hints"] = {**scene_hints, **existing}
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
        frames → audio → whisper → acoustic → claude → save

    Args:
        video_path: 入力動画パス
        output_path: 出力 JSON パス。None なら screenplays/auto_<stem>.json
        options: 実行オプション (fps / instructions)
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
        else:
            logger.warning("動画に音声ストリームがありません。silent modeで分析します")
            for skipped in ("audio", "whisper", "acoustic"):
                _emit_skip(on_progress, skipped, "音声ストリームなし")

        # ─── Claude API の入力上限を超える場合は frames を間引く ──
        original_frame_count = len(frame_paths)
        frame_paths = _downsample_frames(frame_paths)
        if len(frame_paths) < original_frame_count:
            logger.warning(
                "Claude API の上限超過のため frames を %d → %d 枚に間引きました",
                original_frame_count, len(frame_paths),
            )
            _emit(on_progress, "frames_downsampled", {
                "original": original_frame_count,
                "downsampled": len(frame_paths),
                "max_frames": MAX_FRAMES_FOR_CLAUDE,
                "reason": (
                    f"Claude Vision API の入力上限 "
                    f"({MAX_FRAMES_FOR_CLAUDE} 枚) を超えたため均等間引き"
                ),
            })

        # ─── Cost gate (Phase 5 で SSE 経由ユーザー confirm 待ち) ──
        known_furigana = furigana_store.load()
        if on_cost_gate is not None:
            proceed = on_cost_gate(
                len(frame_paths),
                transcript,
                0,  # shot_count: pipeline で算出しない
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
            known_furigana=known_furigana,
        )
        _emit(on_progress, "phase_complete", {"phase": "claude"})
        _check_cancel(cancel_token)

        # ─── Phase: save ─────────────────────────────
        _emit(on_progress, "phase_start", {"phase": "save"})
        new_hints = furigana_store.collect_from_screenplay(screenplay)
        if new_hints:
            furigana_store.merge(new_hints)

        # Claude の SYSTEM_PROMPT 違反を吸収する後処理。発生件数は drift として
        # 集計し、phase_complete に乗せて SSE / UI / ジョブログから可視化する。
        # 件数が多い (= プロンプトと出力の乖離が広がっている) なら CLAUDE.md
        # / SYSTEM_PROMPT / ANALYZER_MODEL の調整サインになる。
        drift = {
            "scene_pronunciation_hints_demoted": _normalize_scene_pronunciation_hints(screenplay),
        }
        if drift["scene_pronunciation_hints_demoted"]:
            logger.warning(
                "[claude_drift] scene 直下の pronunciation_hints を %d シーン分 "
                "line に展開しました (= SYSTEM_PROMPT 違反)",
                drift["scene_pronunciation_hints_demoted"],
            )

        # abstract 形式は composed 必須項目を満たさないので require_composed=False
        # で軽量検証する。compose 後の strict 検証は staged_pipeline 側が担当。
        errors = validate_screenplay(
            screenplay, strict=False, require_composed=False,
        )
        if errors:
            logger.warning("バリデーション警告:")
            for e in errors:
                logger.warning("  - %s", e)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(screenplay, f, ensure_ascii=False, indent=2)
        _emit(on_progress, "phase_complete", {
            "phase": "save",
            "output_path": output_path,
            "claude_drift": drift,
            "validation_warnings": len(errors),
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
