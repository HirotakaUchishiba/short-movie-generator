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

import atomic_assets
import config
import furigana_store
from analyze import cache as _cache
from analyze import character_meta as cmeta_mod
from analyze import location as loc_mod
from analyze.intent_resolver import (
    SceneIntentAssignment,
    detect_novel_intent_candidates,
    load_intent_catalog,
)
from analyze.suggestion_store import SuggestionInput, upsert as suggestion_upsert
from audio_features import (
    extract_phrase_features,
    wpm_from_text,
)
from screenplay_validator import validate_screenplay
from video_analyzer import ScreenplayParseError, build_screenplay
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


def _summarize_annotation_stats(screenplay: dict) -> dict:
    """各 scene の annotation を集計して SSE event 用 dict を返す。

    intent_resolver が catalog 渡しで normalize した結果として、各 scene には
    以下のいずれかの状態がある:

      - ``scene["annotation"]`` 自体が無い (= 全フィールド drop された / catalog
        未指定)。これは visual_intent_id も含めて全部 drop された状態
      - ``scene["annotation"]`` はあるが ``visual_intent_id`` が無い (= intent
        だけ drop、duration_bucket / motion_intensity は残った)
      - ``scene["annotation"]["visual_intent_id"]`` が string で残っている
        (= catalog hit + 高 confidence)

    UI の「N hit, M demoted, by intent」表示用に上記 3 状態を集計する。
    """
    scenes = screenplay.get("scenes") or []
    total_scenes = len(scenes)
    with_id = 0
    demoted = 0
    by_intent_id: dict[str, int] = {}
    for scene in scenes:
        ann = scene.get("annotation") if isinstance(scene, dict) else None
        intent_id = ann.get("visual_intent_id") if isinstance(ann, dict) else None
        if isinstance(intent_id, str) and intent_id:
            with_id += 1
            by_intent_id[intent_id] = by_intent_id.get(intent_id, 0) + 1
        else:
            demoted += 1
    return {
        "total_scenes": total_scenes,
        "with_visual_intent_id": with_id,
        "low_confidence_demoted": demoted,
        "by_intent_id": by_intent_id,
    }


def _collect_novel_intent_candidates(screenplay: dict) -> list[dict]:
    """設計 §8.2 の「novel intent 候補」を screenplay から抽出して dict 列で返す。

    intent_resolver は normalize 段階で低 confidence / 未知 id の scene から
    ``visual_intent_id`` を drop している。ここでは post-normalize の screenplay を
    走査し、

      - ``scene["annotation"]["visual_intent_id"]`` が string なら hit (= 既存 catalog
        とマッチ済み)
      - それ以外 (= annotation 自体無し / id だけ drop) は demoted (= 低 confidence)

    として ``SceneIntentAssignment`` の列に変換し、``detect_novel_intent_candidates``
    に流す。``confidence`` は post-normalize 時点で復元不能なので 1.0 / 0.0 の二値
    で渡す (= ``visual_intent_id is None`` だけが streak 判定に使われるので影響なし)。
    ``rationale`` は scene の ``background_prompt`` をフォールバック説明として使う
    (= Claude が intent rationale を別 field で返さない仕様のため)。

    返り値は SSE event / json file 両方で消費できる plain dict 列:
      ``[{"proposed_id", "description", "scene_indices", "rationale"}]``

    候補が無ければ空リスト。
    """
    scenes = screenplay.get("scenes") or []
    assignments: list[SceneIntentAssignment] = []
    for idx, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        ann = scene.get("annotation") if isinstance(scene, dict) else None
        intent_id = ann.get("visual_intent_id") if isinstance(ann, dict) else None
        has_id = isinstance(intent_id, str) and bool(intent_id)
        rationale = (
            scene.get("background_prompt")
            or scene.get("animation_prompt")
            or ""
        )
        assignments.append(
            SceneIntentAssignment(
                scene_idx=idx,
                visual_intent_id=intent_id if has_id else None,
                confidence=1.0 if has_id else 0.0,
                rationale=str(rationale) if rationale else None,
            )
        )

    candidates = detect_novel_intent_candidates(assignments)
    return [
        {
            "proposed_id": c.proposed_id,
            "description": c.description,
            "scene_indices": list(c.scene_indices),
            "rationale": c.rationale,
        }
        for c in candidates
    ]


def _run_frames_phase(
    *,
    video_path: str,
    fps: float,
    frames_dir: str,
    use_cache: bool,
    on_progress: ProgressCallback | None,
    cancel_token: CancelToken | None,
) -> list[str]:
    """frames phase: video_sha 計算 + cache restore or 新規 extract + event 発火。

    330 行の ``run()`` から最初の phase を独立化 (= §3.3 段階移行)。
    video_sha は本関数内に閉じ込めて caller には返さない (= 後段で参照なし)。
    """
    _emit(on_progress, "phase_start", {"phase": "frames"})
    video_sha = _cache.file_sha256(video_path)
    restored = (
        _cache.restore_frames(video_sha, fps, frames_dir) if use_cache else None
    )
    if restored is not None:
        frame_paths = restored
        _emit(on_progress, "phase_complete", {
            "phase": "frames",
            "frame_count": len(frame_paths),
            "from_cache": True,
        })
    else:
        frame_paths = _extract_frames(video_path, fps, frames_dir)
        if use_cache:
            _cache.store_frames(video_sha, fps, frames_dir)
        _emit(on_progress, "phase_complete", {
            "phase": "frames",
            "frame_count": len(frame_paths),
            "from_cache": False,
        })
    _check_cancel(cancel_token)
    return frame_paths


def _run_audio_phase(
    *,
    video_path: str,
    audio_path: str,
    on_progress: ProgressCallback | None,
    cancel_token: CancelToken | None,
) -> str:
    """audio phase: 音声抽出 + sha 計算 + event 発火 → audio_sha を返す。

    330 行の ``run()`` の 2 番目 phase を独立化 (= §3.3)。cache 対象外
    (= 動画ごとに毎回抽出する)。
    """
    _emit(on_progress, "phase_start", {"phase": "audio"})
    _extract_audio(video_path, audio_path)
    audio_sha = _cache.file_sha256(audio_path)
    _emit(on_progress, "phase_complete", {"phase": "audio"})
    _check_cancel(cancel_token)
    return audio_sha


def _run_whisper_phase(
    *,
    audio_path: str,
    audio_sha: str,
    use_cache: bool,
    on_progress: ProgressCallback | None,
    cancel_token: CancelToken | None,
) -> dict:
    """whisper phase: 音声 → transcript (text/segments/words/duration)。

    cache key は audio_sha 単一 (= 同じ音声なら言語 / モデルが同じ前提で
    完全に同じ transcript)。faster-whisper か OpenAI Whisper API のいずれかが
    transcribe() の内部で選択される (OPENAI_API_KEY の有無)。
    """
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
    return transcript


def _run_acoustic_phase(
    *,
    audio_path: str,
    audio_sha: str,
    transcript: dict,
    use_cache: bool,
    on_progress: ProgressCallback | None,
    cancel_token: CancelToken | None,
) -> list[dict]:
    """acoustic phase: 各 segment ごとに pitch / rms / wpm を抽出する。

    cache key は audio_sha + segments_sig (= 同じ音声 + 同じ segment 境界なら
    完全に同じ feature)。librosa による分析を seg ごとに走らせるため、長い
    音声では cache hit のメリットが大きい。
    """
    _emit(on_progress, "phase_start", {"phase": "acoustic"})
    ac_key = _cache.acoustic_key(audio_sha, transcript)
    cached_ac = _cache.get_json("acoustic", ac_key) if use_cache else None
    if cached_ac is not None:
        phrase_features = cached_ac.get("features", [])
        from_cache = True
    else:
        phrase_features = []
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
    return phrase_features


def _run_claude_phase(
    *,
    frame_paths: list[str],
    transcript: dict,
    phrase_features: list[dict],
    video_path: str,
    extra_instructions: str | None,
    frame_interval_sec: float,
    known_furigana: dict[str, str],
    on_progress: ProgressCallback | None,
    cancel_token: CancelToken | None,
) -> dict:
    """claude phase: visual_intents / locations / characters catalog 付きで
    Claude を呼び、abstract screenplay を生成する。

    catalog ロードは SSOT (= part_registry_loader / loc_mod / cmeta_mod 経由)
    なので yaml drift しない。Claude 課金は parse 失敗でも発生済みなので、
    `ScreenplayParseError` の `usage` も emit してから re-raise する。
    cache 対象外 (= 毎回呼ぶ)。
    """
    intent_catalog = load_intent_catalog()
    location_catalog = loc_mod.build_location_catalog()
    character_catalog = cmeta_mod.build_character_catalog()
    _emit(on_progress, "phase_start", {
        "phase": "claude",
        "frame_count": len(frame_paths),
        "known_furigana_count": len(known_furigana),
        "intent_catalog_size": len(intent_catalog),
        "location_catalog_size": len(location_catalog),
        "character_catalog_size": len(character_catalog),
    })
    try:
        screenplay, claude_usage = build_screenplay(
            frame_paths=frame_paths,
            transcript=transcript,
            phrase_features=phrase_features,
            source_video_path=video_path,
            extra_instructions=extra_instructions,
            frame_interval_sec=frame_interval_sec,
            known_furigana=known_furigana,
            atomic_menu=atomic_assets.build_prompt_menu(),
            intent_catalog=intent_catalog or None,
            location_catalog=location_catalog or None,
            character_catalog=character_catalog or None,
        )
    except ScreenplayParseError as e:
        if e.usage:
            _emit(on_progress, "claude_usage", e.usage)
        raise
    _emit(on_progress, "claude_usage", claude_usage)
    _emit(on_progress, "phase_complete", {"phase": "claude"})
    _check_cancel(cancel_token)
    return screenplay


def _run_rewrite_phase(
    screenplay: dict,
    *,
    on_progress: ProgressCallback | None,
    cancel_token: CancelToken | None,
) -> dict:
    """rewrite phase: Gemini で line.text + caption を言い換える (= 翻案権配慮)。

    設計 doc: docs/plannings/2026-05-17_gemini-dialogue-rewrite.md
    失敗しても analyze 全体は止めない (= original screenplay を save する)。
    status / fallback / token usage は phase_complete event + 専用
    rewrite_usage event で audit 可能にする (= cost 記録は呼出元 runner が
    rewrite_usage event を受けて DB に書く。claude_usage と同パターン)。
    """
    _emit(on_progress, "phase_start", {"phase": "rewrite"})
    try:
        import gemini_dialogue_rewriter as _rewriter
        rewrite_result = _rewriter.rewrite_screenplay(screenplay)
    except Exception as e:  # noqa: BLE001 — defensive (rewriter は本来内部 catch する)
        logger.warning("[rewrite] 想定外例外: %s → original 採用", e)
        rewrite_result = None
    if rewrite_result is not None:
        screenplay = rewrite_result.screenplay
        if (rewrite_result.input_tokens
                or rewrite_result.output_tokens):
            _emit(on_progress, "rewrite_usage", {
                "model": _rewriter.MODEL_ID,
                "input_tokens": rewrite_result.input_tokens,
                "output_tokens": rewrite_result.output_tokens,
                "status": rewrite_result.status,
            })
        _emit(on_progress, "phase_complete", {
            "phase": "rewrite",
            "status": rewrite_result.status,
            "reason": rewrite_result.reason,
            "per_line_fallback_count": (
                rewrite_result.per_line_fallback_count
            ),
            "input_tokens": rewrite_result.input_tokens,
            "output_tokens": rewrite_result.output_tokens,
        })
    else:
        _emit_skip(on_progress, "rewrite", "unexpected_error")
    _check_cancel(cancel_token)
    return screenplay


def _run_save_phase(
    screenplay: dict,
    *,
    output_path: str,
    on_progress: ProgressCallback | None,
    analyze_job_id: str,
) -> None:
    """save phase: drift 後処理 + validate + 書き出し + suggested_intents upsert。

    330 行の ``run()`` 末尾から切り出した独立 phase。furigana_store merge、
    SYSTEM_PROMPT 違反 drift 集計、軽量 validation、screenplay 書き出し、
    novel intent 提案の aggregated inbox upsert、phase_complete event 発火を
    1 関数に集約する。
    """
    _emit(on_progress, "phase_start", {"phase": "save"})
    new_hints = furigana_store.collect_from_screenplay(screenplay)
    if new_hints:
        furigana_store.merge(new_hints)

    # Claude の SYSTEM_PROMPT 違反を吸収する後処理。発生件数は drift として
    # 集計し、phase_complete に乗せて SSE / UI / ジョブログから可視化する。
    drift = {
        "scene_pronunciation_hints_demoted": _normalize_scene_pronunciation_hints(
            screenplay,
        ),
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
    annotation_stats = _summarize_annotation_stats(screenplay)

    # 設計 §8.2: novel intent 候補を aggregated inbox に upsert
    # (= data/intent_suggestions.json)。SSE event にも全件含めて UI で
    # 「💡 提案」セクションに飛べるようにする。
    suggested_intents = _collect_novel_intent_candidates(screenplay)
    if suggested_intents:
        try:
            inputs = [
                SuggestionInput(
                    proposed_id=str(s["proposed_id"]),
                    description=str(s["description"]),
                    rationale=str(s.get("rationale") or ""),
                    scene_indices=tuple(
                        int(i) for i in s.get("scene_indices") or []
                    ),
                    source_screenplay=str(output_path),
                    source_analyze_job_id=analyze_job_id,
                )
                for s in suggested_intents
            ]
            suggestion_upsert(inputs)
        except (OSError, ValueError, TypeError) as e:
            logger.warning("[suggested_intents] inbox upsert failed: %s", e)
    _emit(on_progress, "phase_complete", {
        "phase": "save",
        "output_path": output_path,
        "claude_drift": drift,
        "validation_warnings": len(errors),
        "annotation_stats": annotation_stats,
        "suggested_intents": suggested_intents,
        "suggested_intents_path": None,  # 後方互換: 常に None
    })


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
    analyze_job_id: str | None = None,
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
        frame_paths = _run_frames_phase(
            video_path=video_path,
            fps=options.fps,
            frames_dir=frames_dir,
            use_cache=use_cache,
            on_progress=on_progress,
            cancel_token=cancel_token,
        )

        transcript: dict = {"text": "", "segments": [], "words": [], "duration": 0.0}
        phrase_features: list[dict] = []
        has_audio = _has_audio_stream(video_path)
        audio_sha: str | None = None

        if has_audio:
            # ─── Phase: audio (cache 対象外) ─────────
            audio_sha = _run_audio_phase(
                video_path=video_path,
                audio_path=audio_path,
                on_progress=on_progress,
                cancel_token=cancel_token,
            )

            # ─── Phase: whisper (cache: audio_sha) ───
            transcript = _run_whisper_phase(
                audio_path=audio_path,
                audio_sha=audio_sha,
                use_cache=use_cache,
                on_progress=on_progress,
                cancel_token=cancel_token,
            )

            # ─── Phase: acoustic (cache: audio_sha + segments_sig) ──
            phrase_features = _run_acoustic_phase(
                audio_path=audio_path,
                audio_sha=audio_sha,
                transcript=transcript,
                use_cache=use_cache,
                on_progress=on_progress,
                cancel_token=cancel_token,
            )
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
        screenplay = _run_claude_phase(
            frame_paths=frame_paths,
            transcript=transcript,
            phrase_features=phrase_features,
            video_path=video_path,
            extra_instructions=options.instructions,
            frame_interval_sec=frame_interval_sec,
            known_furigana=known_furigana,
            on_progress=on_progress,
            cancel_token=cancel_token,
        )

        # ─── Phase: rewrite (= Gemini で line.text + caption を言い換え) ─
        screenplay = _run_rewrite_phase(
            screenplay,
            on_progress=on_progress,
            cancel_token=cancel_token,
        )

        # ─── Phase: save ─────────────────────────────
        _run_save_phase(
            screenplay,
            output_path=output_path,
            on_progress=on_progress,
            analyze_job_id=analyze_job_id,
        )

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
