#!/usr/bin/env python3
"""段階的ゲート方式のプレビューサーバ (REST API only)。

各 stage の生成・確認・承認・再生成 API を提供する。フロントは frontend/ の React を使用。
"""
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict
from flask import Flask, jsonify, request, send_file, abort, send_from_directory, Response
from flask_cors import CORS

import config
import elevenlabs_client
import fal_video_client
import imagen_client
import log_setup
import progress_store
import scene_gen
import staged_pipeline
import video_analyzer
from analyze import job as analyze_job
from analyze import progress as analyze_progress
from analyze import runner as analyze_runner
from analyze.cache import file_sha256
from analytics import db as _analytics_db
from cost_tracking import estimator as cost_estimator
from cost_tracking import pricebook as cost_pricebook
from cost_tracking import report as cost_report

log_setup.setup()
logger = logging.getLogger(__name__)

# 起動時に analytics DB schema を最新化する。
# analyze_jobs / analyze_phases / reference_videos テーブルが含まれていない
# 古い DB でも CREATE TABLE IF NOT EXISTS で安全に追加される。
_analytics_db.init_db()

app = Flask(__name__, static_folder=None)
# 動画アップロード上限 (1GB、analyze 用 reference video)。
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024
CORS(app)

TEMP_DIR = config.TEMP_DIR
SCREENPLAYS_DIR = config.SCREENPLAYS_DIR
OUTPUT_DIR = config.OUTPUT_DIR

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
# screenplay disk write の serialize 用 (per-name) は staged_pipeline に移動。
# 同じ Lock を REST patch ハンドラと TTS regen 後の永続化が共有する。
_screenplay_lock = staged_pipeline.screenplay_lock

FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")


def _tts_pricing() -> dict:
    """ElevenLabs の表示用設定 (= 文字単価倍率 + 単価情報)。

    ``usd_per_credit`` は ``data/pricebook.json`` から読む (= ハードコードしない)。
    実コスト見積もりは ``cost_tracking`` の履歴ベース算定が SSOT。
    """
    model = elevenlabs_client.MODEL_ID
    multiplier = elevenlabs_client.credit_multiplier(model)
    try:
        usd_per_credit = float(
            cost_pricebook.get_unit_prices("elevenlabs", model)
            .get("usd_per_credit", 0.0)
        )
    except KeyError:
        usd_per_credit = 0.0
    return {
        "model": model,
        "credit_multiplier": multiplier,
        "usd_per_credit": usd_per_credit,
        "available_models": elevenlabs_client.available_models(),
        "global_speed": float(config.TTS_GLOBAL_SPEED),
        "speed_min": 0.5,
        "speed_max": 2.0,
        "trim_silences": bool(getattr(config, "TTS_TRIM_LONG_SILENCES", False)),
        "max_silence_ms": float(getattr(config, "TTS_MAX_SILENCE_MS", 250)),
        "note": (
            f"{model} は1文字あたり {multiplier} credits 消費。"
            "実コストは data/cost_records.jsonl の履歴 median から算定。"
        ),
    }


@app.route("/api/config/model", methods=["POST"])
def api_set_model():
    """ランタイムでELEVENLABSモデルを切替える。サーバ再起動するとenv値に戻る。"""
    import elevenlabs_client
    data = request.get_json(force=True) or {}
    model = data.get("model")
    if not model:
        return jsonify({"error": "model required"}), 400
    try:
        elevenlabs_client.set_model(model)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "tts_pricing": _tts_pricing()})


@app.route("/api/config/speed", methods=["POST"])
def api_set_speed():
    """ランタイムでTTSグローバル速度を変更する (0.5〜2.0)。"""
    data = request.get_json(force=True) or {}
    speed = data.get("speed")
    if not isinstance(speed, (int, float)):
        return jsonify({"error": "speed (number) required"}), 400
    speed = float(speed)
    if speed < 0.5 or speed > 2.0:
        return jsonify({"error": "speed must be 0.5〜2.0"}), 400
    config.TTS_GLOBAL_SPEED = speed
    return jsonify({"ok": True, "tts_pricing": _tts_pricing()})


@app.route("/api/config/silences", methods=["POST"])
def api_set_silences():
    """ランタイムで無音圧縮設定を変更する。"""
    data = request.get_json(force=True) or {}
    if "enabled" in data:
        config.TTS_TRIM_LONG_SILENCES = bool(data["enabled"])
    if "max_ms" in data:
        v = data["max_ms"]
        if not isinstance(v, (int, float)) or v < 50 or v > 2000:
            return jsonify({"error": "max_ms must be 50〜2000"}), 400
        config.TTS_MAX_SILENCE_MS = float(v)
    return jsonify({"ok": True, "tts_pricing": _tts_pricing()})


@app.after_request
def _no_cache_for_assets(resp):
    """生成物 (/asset/) はブラウザにキャッシュさせない。再生成後即座に最新が見える。"""
    if request.path.startswith("/asset/"):
        resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


def _validate_ts(ts: str) -> str:
    if not re.match(r'^[\w\-]+$', ts):
        abort(400, "不正なタイムスタンプ")
    return ts


def _ts_path(ts: str) -> str:
    return os.path.join(TEMP_DIR, ts)


def _safe_join(base: str, *parts: str) -> str:
    """ディレクトリトラバーサル防止。"""
    p = os.path.realpath(os.path.join(base, *parts))
    if not p.startswith(os.path.realpath(base) + os.sep) and p != os.path.realpath(base):
        abort(400, "不正なパス")
    return p


def _list_screenplays() -> list[str]:
    if not os.path.isdir(SCREENPLAYS_DIR):
        return []
    return sorted(f for f in os.listdir(SCREENPLAYS_DIR) if f.endswith(".json"))


def _load_screenplay_for_project(ts: str) -> tuple[dict, str]:
    """temp_dir/screenplay.json (immutable snapshot) を読み込む。

    台本は project 作成時に temp/<TS>/screenplay.json にコピーされ、
    以後そのファイルだけが正となる。template (= screenplays/<name>.json)
    が外部で書き換わっても進行中 project には影響しない。
    """
    meta = staged_pipeline.read_metadata(_ts_path(ts))
    if not meta:
        abort(404, "プロジェクトのmetadataがありません")
    name = meta.get("screenplay_template_name") or meta.get("screenplay_name")
    if not name:
        abort(404, "metadataにscreenplay_template_name/nameがありません")
    try:
        sp = staged_pipeline.load_project_screenplay(_ts_path(ts))
    except FileNotFoundError:
        abort(404, "プロジェクトの screenplay.json snapshot が見つかりません")
    return sp, name


def _ffprobe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", path],
            capture_output=True, text=True,
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0


# ───────────────── プロジェクト一覧 / 作成 ─────────────────

@app.route("/api/projects", methods=["GET"])
def api_projects():
    items = []
    if not os.path.isdir(TEMP_DIR):
        return jsonify({"projects": items, "screenplays": _list_screenplays()})

    for ts in sorted(os.listdir(TEMP_DIR), reverse=True):
        ts_path = _ts_path(ts)
        if not os.path.isdir(ts_path):
            continue
        meta = staged_pipeline.read_metadata(ts_path)
        if not meta:
            continue
        progress = progress_store.load(ts_path)
        items.append({
            "timestamp": ts,
            "screenplay_name": meta.get("screenplay_name"),
            "created_at": meta.get("created_at"),
            "current_stage": progress_store.current_stage(ts_path),
            "progress": progress,
        })
    return jsonify({"projects": items, "screenplays": _list_screenplays()})


@app.route("/api/projects", methods=["POST"])
def api_create_project():
    """新規 project を作成する。

    screenplays/<name>.json (template) を読み、temp/<TS>/screenplay.json
    に immutable snapshot としてコピーする。以後の stage / UI 編集は
    snapshot のみを対象とし、template が外部で書き換わっても影響を受けない。
    """
    data = request.get_json(force=True) or {}
    name = data.get("screenplay_name")
    if not name:
        return jsonify({"error": "screenplay_name が必要です"}), 400
    analyze_job_id = data.get("analyze_job_id") or None
    if analyze_job_id and not _JOB_ID_RE.match(analyze_job_id):
        return jsonify({"error": "invalid analyze_job_id"}), 400
    try:
        screenplay = staged_pipeline.load_template(name)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404

    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_path = _ts_path(ts)
    os.makedirs(ts_path, exist_ok=True)

    try:
        staged_pipeline.run_script(
            screenplay, name, ts_path, analyze_job_id=analyze_job_id,
        )
    except Exception as e:
        logger.exception("script stage failed")
        return jsonify({"error": str(e)}), 500

    return jsonify({"timestamp": ts, "current_stage": "script"}), 201


# ───────────────── プロジェクト詳細 / 進捗 ─────────────────

@app.route("/api/projects/<ts>", methods=["GET"])
def api_project_detail(ts):
    _validate_ts(ts)
    if not os.path.isdir(_ts_path(ts)):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    sp, name = _load_screenplay_for_project(ts)
    progress = progress_store.load(_ts_path(ts))
    meta = staged_pipeline.read_metadata(_ts_path(ts)) or {}
    return jsonify({
        "timestamp": ts,
        "screenplay_name": name,
        "screenplay": sp,
        "progress": progress,
        "current_stage": progress_store.current_stage(_ts_path(ts)),
        "analyze_job_id": meta.get("analyze_job_id"),
    })


# ElevenLabs に実際に送信される原文を返す。
# scene_gen._build_screenplay_text を呼んで line を separator で連結した結果と、
# 各 line の char range (char_start, char_end) を返す。UI 透明性のため。
@app.route("/api/projects/<ts>/tts-source", methods=["GET"])
def api_tts_source(ts):
    _validate_ts(ts)
    if not os.path.isdir(_ts_path(ts)):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    sp, _ = _load_screenplay_for_project(ts)
    full_text, line_specs = scene_gen._build_screenplay_text(sp)
    return jsonify({
        "text": full_text,
        "char_count": len(full_text),
        "separator": scene_gen.SCREENPLAY_TEXT_SEPARATOR,
        "line_specs": line_specs,
    })


# scene 単位の合成済みプロンプト (BG/Kling 用) を返す。
# scene_gen._build_background_prompt / _get_animation_prompt の出力をそのまま返す。
@app.route("/api/projects/<ts>/scenes/<int:scene_idx>/composed-prompts",
            methods=["GET"])
def api_composed_prompts(ts, scene_idx):
    _validate_ts(ts)
    if not os.path.isdir(_ts_path(ts)):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    sp, _ = _load_screenplay_for_project(ts)
    scenes = sp.get("scenes") or []
    if scene_idx >= len(scenes):
        return jsonify({"error": f"scene_idx範囲外: {scene_idx}"}), 400
    scene = scenes[scene_idx]
    bg_prompt = scene_gen._build_background_prompt(
        scene, sp, ts_path=_ts_path(ts), s_idx=scene_idx)
    anim_prompt = scene_gen._get_animation_prompt(
        scene, ts_path=_ts_path(ts), s_idx=scene_idx)
    return jsonify({
        "scene_idx": scene_idx,
        "background_prompt": bg_prompt,
        "animation_prompt": anim_prompt,
    })


@app.route("/api/projects/<ts>/progress", methods=["GET"])
def api_project_progress(ts):
    _validate_ts(ts)
    if not os.path.isdir(_ts_path(ts)):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    return jsonify({
        "progress": progress_store.load(_ts_path(ts)),
        "current_stage": progress_store.current_stage(_ts_path(ts)),
    })


# ───────────────── 承認 / 次stage実行 ─────────────────

@app.route("/api/projects/<ts>/approve", methods=["POST"])
def api_approve(ts):
    _validate_ts(ts)
    data = request.get_json(force=True) or {}
    stage = data.get("stage")
    if stage not in progress_store.STAGES:
        return jsonify({"error": f"不正なstage: {stage}"}), 400
    try:
        progress_store.mark_approved(_ts_path(ts), stage)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({
        "ok": True,
        "approved_stage": stage,
        "next_stage": progress_store.next_stage(_ts_path(ts)),
    })


@app.route("/api/projects/<ts>/run-next", methods=["POST"])
def api_run_next(ts):
    _validate_ts(ts)
    if not os.path.isdir(_ts_path(ts)):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    sp, name = _load_screenplay_for_project(ts)
    job_id = _spawn_job(
        lambda: staged_pipeline.run_next_stage(sp, name, _ts_path(ts)),
        kind="run-next", ts=ts,
    )
    return jsonify({"job_id": job_id})


# ───────────────── 再生成 ─────────────────

@app.route("/api/projects/<ts>/regen", methods=["POST"])
def api_regen(ts):
    _validate_ts(ts)
    data = request.get_json(force=True) or {}
    stage = data.get("stage")
    scene_idx = data.get("scene_idx")
    line_idx = data.get("line_idx")
    force = bool(data.get("force", True))
    # bg ステージの「キャッシュ無視」再生成: 該当 scene に内部 hint を立てる
    force_no_cache = bool(data.get("force_no_cache", False))
    if stage not in {"tts", "bg", "kling", "scene", "overlay"}:
        return jsonify({"error": f"このstageは再生成不可: {stage}"}), 400

    sp, name = _load_screenplay_for_project(ts)
    if force_no_cache and stage == "bg":
        scenes = sp.get("scenes") or []
        if isinstance(scene_idx, int) and 0 <= scene_idx < len(scenes):
            scenes[scene_idx]["_bg_force_no_cache"] = True
        else:
            for s in scenes:
                s["_bg_force_no_cache"] = True

    job_id = _spawn_job(
        lambda: staged_pipeline.regen(
            stage, sp, _ts_path(ts), scene_idx, line_idx, force=force),
        kind=f"regen-{stage}", ts=ts,
    )
    return jsonify({"job_id": job_id})


# ───────────────── 台本書き戻し ─────────────────

@app.route("/api/projects/<ts>/screenplay", methods=["PUT"])
def api_save_screenplay(ts):
    _validate_ts(ts)
    if not os.path.isdir(_ts_path(ts)):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    data = request.get_json(force=True) or {}
    sp = data.get("screenplay")
    if not isinstance(sp, dict):
        return jsonify({"error": "screenplayが必要です"}), 400
    try:
        from screenplay_validator import validate_screenplay
        errors = validate_screenplay(sp, strict=False)
        if errors:
            return jsonify({"error": "validator失敗", "details": errors}), 400
        with _screenplay_lock(ts):
            staged_pipeline.save_project_screenplay(_ts_path(ts), sp)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


# bg_cache 情報取得: 該当 scene の合成入力からキャッシュキーを派生し、
# キャッシュに同 key の画像が存在するかを返す (= UI のバッジ表示用)。
@app.route("/api/projects/<ts>/scenes/<int:scene_idx>/bg-cache-info",
           methods=["GET"])
def api_bg_cache_info(ts, scene_idx):
    _validate_ts(ts)
    ts_path = _ts_path(ts)
    if not os.path.isdir(ts_path):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    try:
        sp = staged_pipeline.load_project_screenplay(ts_path)
    except FileNotFoundError:
        return jsonify({"error": "snapshot not found"}), 404
    scenes = sp.get("scenes") or []
    if scene_idx < 0 or scene_idx >= len(scenes):
        return jsonify({"error": "scene_idx out of range"}), 400
    import bg_cache
    try:
        key = bg_cache.compute_bg_cache_key(scenes[scene_idx], sp)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    cached = bg_cache.lookup(key)
    info: dict = {"cache_key": key, "cached": cached is not None}
    if cached is not None:
        try:
            with open(str(cached.with_suffix(".json")), encoding="utf-8") as f:
                meta = json.load(f)
            info["hit_count"] = int(meta.get("hit_count", 0))
            info["created_at"] = meta.get("created_at")
            info["last_used_at"] = meta.get("last_used_at")
        except Exception:
            pass
    return jsonify(info)


# Server-side merge: line 単位の field patch。
# 全 screenplay を投げる PUT と異なり、複数 client が並行 patch しても他 line を上書きしない。
@app.route("/api/projects/<ts>/lines/<int:scene_idx>/<int:line_idx>",
            methods=["PATCH"])
def api_patch_line(ts, scene_idx, line_idx):
    """abstract snapshot の line に部分 patch を適用する。

    snapshot は abstract 形式のまま読み書きする (= live derivation を維持)。
    派生フィールド (voice_overrides の base 値・background_prompt 等) は
    Stage 2 以降が compose を介して読むので、ここでは触らない。
    """
    _validate_ts(ts)
    data = request.get_json(force=True) or {}
    patch = data.get("patch")
    if not isinstance(patch, dict):
        return jsonify({"error": "patch (object) が必要です"}), 400
    # abstract line schema に揃えた allowlist。start/end は **TTS が SSOT** で
    # ユーザー編集対象外 (analyze の Whisper 値 → Stage 2 で実音声長に上書き)
    # なので除外する。subtitles/hidden は字幕分割・抑止フラグとして残す。
    # voice_overrides は line 個別 override が compose で base に上書き優先される
    allowed = {
        "text", "tts_text", "rate", "emotion",
        "emotion_intensity", "delivery", "audio_tags", "speaker",
        "pronunciation_hints", "voice_overrides", "acoustic",
        "subtitles", "hidden",
    }
    unknown = set(patch.keys()) - allowed
    if unknown:
        return jsonify({"error": f"許可されていないフィールド: {sorted(unknown)}"}), 400

    ts_path = _ts_path(ts)
    if not os.path.isdir(ts_path):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    try:
        from screenplay_validator import validate_abstract
        with _screenplay_lock(ts):
            sp = staged_pipeline.load_project_abstract(ts_path)
            scenes = sp.get("scenes") or []
            if scene_idx >= len(scenes):
                return jsonify({"error": f"scene_idx範囲外: {scene_idx}"}), 400
            lines = scenes[scene_idx].get("lines") or []
            if line_idx >= len(lines):
                return jsonify({"error": f"line_idx範囲外: {line_idx}"}), 400
            line = lines[line_idx]
            for k, v in patch.items():
                if v is None:
                    line.pop(k, None)
                else:
                    line[k] = v
            errors = validate_abstract(sp, strict=False)
            if errors:
                return jsonify({"error": "validator失敗", "details": errors}), 400
            staged_pipeline.save_project_screenplay(ts_path, sp)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


# scene 単位の patch (location_ref / camera_distance / animation_style /
# character_selection 等の abstract フィールドのみ)。派生フィールド
# (background_prompt / animation_prompt / character_refs / lipsync) は
# compose が毎回再生成するので patch 不可。
@app.route("/api/projects/<ts>/scenes/<int:scene_idx>", methods=["PATCH"])
def api_patch_scene(ts, scene_idx):
    _validate_ts(ts)
    data = request.get_json(force=True) or {}
    patch = data.get("patch")
    if not isinstance(patch, dict):
        return jsonify({"error": "patch (object) が必要です"}), 400
    # duration は Stage 2 (TTS) が SSOT で snapshot 上書き経路を持たない (= α)。
    # patch_scene からも除外し、UI が触れない設計を徹底する。
    allowed = {
        "location_ref", "camera_distance", "animation_style",
        "character_selection",
    }
    unknown = set(patch.keys()) - allowed
    if unknown:
        return jsonify({"error": f"許可されていないフィールド: {sorted(unknown)}"}), 400

    ts_path = _ts_path(ts)
    if not os.path.isdir(ts_path):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    try:
        from screenplay_validator import validate_abstract
        with _screenplay_lock(ts):
            sp = staged_pipeline.load_project_abstract(ts_path)
            scenes = sp.get("scenes") or []
            if scene_idx >= len(scenes):
                return jsonify({"error": f"scene_idx範囲外: {scene_idx}"}), 400
            scene = scenes[scene_idx]
            for k, v in patch.items():
                if v is None:
                    scene.pop(k, None)
                else:
                    scene[k] = v
            errors = validate_abstract(sp, strict=False)
            if errors:
                return jsonify({"error": "validator失敗", "details": errors}), 400
            staged_pipeline.save_project_screenplay(ts_path, sp)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


# screenplay-level patch (subtitle_y_from_bottom 等)。
@app.route("/api/projects/<ts>/screenplay-meta", methods=["PATCH"])
def api_patch_screenplay_meta(ts):
    _validate_ts(ts)
    data = request.get_json(force=True) or {}
    patch = data.get("patch")
    if not isinstance(patch, dict):
        return jsonify({"error": "patch (object) が必要です"}), 400
    allowed = {"subtitle_y_from_bottom"}
    unknown = set(patch.keys()) - allowed
    if unknown:
        return jsonify({"error": f"許可されていないフィールド: {sorted(unknown)}"}), 400

    ts_path = _ts_path(ts)
    if not os.path.isdir(ts_path):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    try:
        from screenplay_validator import validate_abstract
        with _screenplay_lock(ts):
            sp = staged_pipeline.load_project_abstract(ts_path)
            for k, v in patch.items():
                if v is None:
                    sp.pop(k, None)
                else:
                    sp[k] = v
            errors = validate_abstract(sp, strict=False)
            if errors:
                return jsonify({"error": "validator失敗", "details": errors}), 400
            staged_pipeline.save_project_screenplay(ts_path, sp)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


# characters/ 配下の画像 ref 一覧 (拡張子なし)。Stage 1 の登場人物選択 UI 用。
@app.route("/api/characters", methods=["GET"])
def api_list_characters():
    """利用可能な resolved id (= <base>__<wardrobe> / <base>) 一覧。
    新ネスト構造 (characters/<base>/<wardrobe>.png) と旧 flat レイアウトの
    両方に対応 (analyze.character_meta.list_character_images)。"""
    from analyze import character_meta as cmeta_mod
    return jsonify({"characters": cmeta_mod.list_character_images()})


# preset ライブラリ全部をフロントに返す。UI dropdown 用。
@app.route("/api/presets", methods=["GET"])
def api_presets():
    import config as _config
    return jsonify({
        "libraries": _config.PROMPT_PRESET_LIBRARIES,
        "labels_ja": _config.PRESET_LABELS_JA,
        "category_labels_ja": _config.PRESET_CATEGORY_LABELS_JA,
        "emotion_default_preset_ids": _config.EMOTION_DEFAULT_PRESET_IDS,
    })


# ───────────────── ジョブステータス ─────────────────

def _spawn_job(fn, *, kind: str, ts: str) -> str:
    job_id = str(uuid.uuid4())[:8]
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id, "kind": kind, "ts": ts,
            "status": "running", "log": [], "started_at": time.time(),
            "error": None,
        }

    def runner():
        try:
            fn()
            with _jobs_lock:
                _jobs[job_id]["status"] = "completed"
        except Exception as e:
            logger.exception("job %s failed", job_id)
            with _jobs_lock:
                _jobs[job_id]["status"] = "failed"
                _jobs[job_id]["error"] = str(e)
    threading.Thread(target=runner, daemon=True).start()
    return job_id


@app.route("/api/jobs/<job_id>", methods=["GET"])
def api_job(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "ジョブが見つかりません"}), 404
    return jsonify({
        "id": job["id"],
        "kind": job["kind"],
        "ts": job["ts"],
        "status": job["status"],
        "elapsed": round(time.time() - job["started_at"], 1),
        "error": job.get("error"),
    })


# ───────────────── アセット配信 ─────────────────

@app.route("/asset/<ts>/tts/<int:scene_idx>/<int:line_idx>")
def asset_tts(ts, scene_idx, line_idx):
    _validate_ts(ts)
    base = _ts_path(ts)
    adj = _safe_join(base, f"tts_{scene_idx:03d}_{line_idx:03d}.adj.mp3")
    raw = _safe_join(base, f"tts_{scene_idx:03d}_{line_idx:03d}.mp3")
    if os.path.exists(adj):
        return send_file(adj, mimetype="audio/mpeg")
    if os.path.exists(raw):
        return send_file(raw, mimetype="audio/mpeg")
    return "", 404


@app.route("/asset/<ts>/tts-merged")
def asset_tts_merged(ts):
    _validate_ts(ts)
    if not os.path.isdir(_ts_path(ts)):
        return "", 404
    sp, _name = _load_screenplay_for_project(ts)
    try:
        path = scene_gen.build_merged_tts_preview(sp, _ts_path(ts))
    except Exception as e:
        logger.exception("merged TTS build failed")
        return jsonify({"error": str(e)}), 500
    if not path or not os.path.exists(path):
        return "", 404
    mimetype = "audio/mp4" if path.endswith(".m4a") else "audio/mpeg"
    return send_file(path, mimetype=mimetype)


@app.route("/asset/<ts>/bg/<int:scene_idx>")
def asset_bg(ts, scene_idx):
    _validate_ts(ts)
    p = _safe_join(_ts_path(ts), f"bg_{scene_idx:03d}.png")
    if os.path.exists(p):
        return send_file(p, mimetype="image/png")
    return "", 404


@app.route("/asset/<ts>/kling/<int:scene_idx>")
def asset_kling(ts, scene_idx):
    _validate_ts(ts)
    p = _safe_join(_ts_path(ts), f"kling_{scene_idx:03d}.mp4")
    if os.path.exists(p):
        return send_file(p, mimetype="video/mp4")
    return "", 404


@app.route("/asset/<ts>/scene-trim/<int:scene_idx>")
def asset_scene_trim(ts, scene_idx):
    _validate_ts(ts)
    p = _safe_join(_ts_path(ts), f"scene_{scene_idx:03d}.trim.mp4")
    if os.path.exists(p):
        return send_file(p, mimetype="video/mp4")
    return "", 404


@app.route("/asset/<ts>/scene/<int:scene_idx>")
def asset_scene(ts, scene_idx):
    _validate_ts(ts)
    p = _safe_join(_ts_path(ts), f"scene_{scene_idx:03d}.mp4")
    if os.path.exists(p):
        return send_file(p, mimetype="video/mp4")
    return "", 404


@app.route("/asset/<ts>/scene-audio/<int:scene_idx>")
def asset_scene_audio(ts, scene_idx):
    _validate_ts(ts)
    p = _safe_join(_ts_path(ts), f"audio_{scene_idx:03d}.m4a")
    if os.path.exists(p):
        return send_file(p, mimetype="audio/mp4")
    return "", 404


@app.route("/asset/<ts>/overlay")
def asset_overlay(ts):
    _validate_ts(ts)
    p = _safe_join(_ts_path(ts), "overlaid.mp4")
    if os.path.exists(p):
        return send_file(p, mimetype="video/mp4")
    return "", 404


@app.route("/asset/<ts>/final")
def asset_final(ts):
    _validate_ts(ts)
    p = os.path.join(OUTPUT_DIR, f"reels_{ts}.mp4")
    if os.path.exists(p):
        return send_file(p, mimetype="video/mp4")
    return "", 404


@app.route("/asset/character/<name>")
def asset_character(name):
    from analyze import character_meta as cmeta_mod
    if not re.match(r'^[\w\-]+$', name):
        abort(400)
    p = cmeta_mod.image_path(name)
    if p is not None and p.exists():
        return send_file(str(p), mimetype="image/png")
    return "", 404


@app.route("/asset/reference-video/<sha>")
def asset_reference_video(sha):
    """analyze ジョブの参考動画を Stage 1「素材編集」UI でプレビューさせる。"""
    if not _SHA256_RE.match(sha):
        abort(400)
    p = analyze_job.reference_video_path(sha)
    if not p or not os.path.exists(p):
        return "", 404
    ext = os.path.splitext(p)[1].lower()
    mimetype = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
    }.get(ext, "application/octet-stream")
    return send_file(p, mimetype=mimetype, conditional=True)


# ───────────────── reference videos (analyze 用) ─────────────────

@app.route("/api/reference_videos", methods=["POST"])
def api_upload_reference_video():
    """multipart で動画をアップロードし、content-addressed (sha256) で保存する。

    既存 sha256 と一致する場合は dedup され既存メタを返す (HTTP 200)。
    新規なら 201。
    """
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "file required (multipart 'file' field)"}), 400

    name = f.filename or "video"
    ext = os.path.splitext(name)[1].lower()
    if ext not in analyze_job.ALLOWED_VIDEO_EXTS:
        return jsonify({
            "error": f"unsupported extension: {ext}",
            "allowed": list(analyze_job.ALLOWED_VIDEO_EXTS),
        }), 400

    ref_dir = analyze_job.reference_videos_dir()
    tmp = ref_dir / f".tmp_{uuid.uuid4().hex}{ext}"
    try:
        f.save(str(tmp))
        sha = file_sha256(str(tmp))
        size = os.path.getsize(tmp)

        existing = analyze_job.get_reference_video(sha)
        if existing:
            tmp.unlink(missing_ok=True)
            analyze_job.touch_reference_video(sha)
            return jsonify({
                "sha256": sha,
                "size_bytes": existing["size_bytes"],
                "duration_sec": existing["duration_sec"],
                "original_name": existing["original_name"],
                "deduplicated": True,
            }), 200

        final_path = ref_dir / f"{sha}{ext}"
        tmp.replace(final_path)

        duration = _ffprobe_duration(str(final_path))
        original = os.path.basename(name)
        analyze_job.upsert_reference_video(
            sha, original_name=original,
            size_bytes=size, duration_sec=duration,
        )
        return jsonify({
            "sha256": sha,
            "size_bytes": size,
            "duration_sec": duration,
            "original_name": original,
            "deduplicated": False,
        }), 201
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


@app.route("/api/reference_videos", methods=["GET"])
def api_list_reference_videos():
    return jsonify({"reference_videos": analyze_job.list_reference_videos()})


@app.route("/api/reference_videos/<sha>", methods=["DELETE"])
def api_delete_reference_video(sha):
    if not re.match(r'^[a-f0-9]{64}$', sha):
        return jsonify({"error": "invalid sha256 (64 hex chars required)"}), 400

    force = request.args.get("force", "").lower() in ("1", "true", "yes")
    deleted = analyze_job.delete_reference_video(sha, force=force)
    if not deleted:
        n = analyze_job.count_jobs_for_video(sha)
        return jsonify({
            "error": (
                f"この動画は {n} 件の analyze ジョブから参照されています。"
                "?force=true を指定すると関連ジョブごと削除します。"
            ),
            "job_count": n,
        }), 409

    file_path = analyze_job.reference_video_path(sha)
    if file_path and os.path.exists(file_path):
        os.unlink(file_path)
        return jsonify({"sha256": sha, "deleted": True, "force": force}), 200
    return jsonify({
        "sha256": sha, "deleted": True, "force": force,
        "warning": "DB row deleted but file not found",
    }), 200


# ───────────────── VideoStyle (抽象台本合成用テンプレ) ─────────────────

# ───────────────── locations CRUD ─────────────────


@app.route("/api/locations", methods=["GET"])
def api_list_locations():
    from analyze import location as loc_mod
    items = []
    for lid in loc_mod.list_locations():
        try:
            items.append(loc_mod.load_location(lid).to_dict())
        except Exception as e:
            logger.warning("location %s 読み込み失敗: %s", lid, e)
    return jsonify({"locations": items})


@app.route("/api/locations/<loc_id>", methods=["GET"])
def api_get_location(loc_id):
    from analyze import location as loc_mod
    try:
        return jsonify(loc_mod.load_location(loc_id).to_dict())
    except FileNotFoundError:
        return jsonify({"error": f"location not found: {loc_id}"}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/locations", methods=["POST"])
def api_create_location():
    from analyze import location as loc_mod
    data = request.get_json(force=True) or {}
    if not data.get("id"):
        return jsonify({"error": "id required"}), 400
    try:
        loc = loc_mod.Location.from_dict(data)
        loc_mod.save_location(loc)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(loc.to_dict()), 201


@app.route("/api/locations/<loc_id>", methods=["PUT"])
def api_update_location(loc_id):
    from analyze import location as loc_mod
    if not loc_mod.ID_RE.match(loc_id):
        return jsonify({"error": "invalid id"}), 400
    data = request.get_json(force=True) or {}
    data["id"] = loc_id
    try:
        loc = loc_mod.Location.from_dict(data)
        loc_mod.save_location(loc)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(loc.to_dict())


@app.route("/api/locations/<loc_id>", methods=["DELETE"])
def api_delete_location(loc_id):
    from analyze import location as loc_mod
    try:
        deleted = loc_mod.delete_location(loc_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not deleted:
        return jsonify({"error": f"location not found: {loc_id}"}), 404
    return jsonify({"id": loc_id, "deleted": True})


@app.route("/asset/location/<loc_id>/preview")
def asset_location_preview(loc_id):
    from analyze import location as loc_mod
    if not loc_mod.ID_RE.match(loc_id or ""):
        abort(400)
    p = loc_mod.preview_path(loc_id)
    if p.exists():
        return send_file(str(p), mimetype="image/png")
    return "", 404


# ───────────────── character meta CRUD ─────────────────


@app.route("/api/character-metas", methods=["GET"])
def api_list_character_metas():
    from analyze import character_meta as cmeta_mod
    metas = []
    for cid in cmeta_mod.list_character_metas():
        try:
            metas.append(cmeta_mod.load_character_meta(cid).to_dict())
        except Exception as e:
            logger.warning("character_meta %s 読み込み失敗: %s", cid, e)
    images = cmeta_mod.list_character_images()
    return jsonify({"character_metas": metas, "image_ids": images})


@app.route("/api/character-metas/<char_id>", methods=["GET"])
def api_get_character_meta(char_id):
    from analyze import character_meta as cmeta_mod
    try:
        return jsonify(cmeta_mod.load_character_meta(char_id).to_dict())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/character-metas/<char_id>", methods=["PUT"])
def api_update_character_meta(char_id):
    from analyze import character_meta as cmeta_mod
    if not cmeta_mod.ID_RE.match(char_id):
        return jsonify({"error": "invalid id"}), 400
    data = request.get_json(force=True) or {}
    data["id"] = char_id
    try:
        meta = cmeta_mod.CharacterMeta.from_dict(data)
        cmeta_mod.save_character_meta(meta)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(meta.to_dict())


@app.route("/api/character-metas/<char_id>", methods=["DELETE"])
def api_delete_character_meta(char_id):
    from analyze import character_meta as cmeta_mod
    try:
        deleted = cmeta_mod.delete_character_meta(char_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not deleted:
        return jsonify({"error": f"character_meta not found: {char_id}"}), 404
    return jsonify({"id": char_id, "deleted": True})


# ───────────────── analyze ジョブ ─────────────────

_JOB_ID_RE = re.compile(r"^analyze_[\w]+$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_TS_RE = re.compile(r"^\d{8}_\d{6}$")


def _job_to_dict(j) -> dict:
    return {
        "id": j.id,
        "video_sha256": j.video_sha256,
        "options": json.loads(j.options_json),
        "status": j.status,
        "current_phase": j.current_phase,
        "error": j.error,
        "estimated_cost_usd": j.estimated_cost_usd,
        "actual_cost_usd": j.actual_cost_usd,
        "screenplay_path": j.screenplay_path,
        "style_name": j.style_name,
        "created_at": j.created_at,
        "started_at": j.started_at,
        "finished_at": j.finished_at,
        "cancellation_requested": bool(j.cancellation_requested),
    }


@app.route("/api/screenplay/analyze", methods=["POST"])
def api_create_analyze_job():
    """analyze ジョブを作成し、別 thread で起動する。"""
    data = request.get_json(force=True) or {}
    sha = data.get("video_sha256") or ""
    if not _SHA256_RE.match(sha):
        return jsonify({"error": "video_sha256 (64 hex chars) required"}), 400
    if not analyze_job.get_reference_video(sha):
        return jsonify({"error": f"reference video not found: {sha}"}), 404

    raw_options = data.get("options") or {}
    allowed = {"fps", "instructions"}
    options = {k: v for k, v in raw_options.items() if k in allowed}

    j = analyze_job.create_job(sha, options)
    analyze_runner.start(j.id)
    return jsonify({"job_id": j.id}), 201


@app.route("/api/screenplay/analyze", methods=["GET"])
def api_list_analyze_jobs():
    items = [_job_to_dict(j) for j in analyze_job.list_jobs()]
    return jsonify({"jobs": items})


@app.route("/api/screenplay/analyze/<job_id>", methods=["GET"])
def api_analyze_job_detail(job_id):
    if not _JOB_ID_RE.match(job_id):
        return jsonify({"error": "invalid job_id"}), 400
    try:
        j = analyze_job.get_job(job_id)
    except KeyError:
        return jsonify({"error": "job not found"}), 404
    phases = analyze_job.get_phases(job_id)
    return jsonify({**_job_to_dict(j), "phases": phases})


@app.route("/api/screenplay/analyze/<job_id>/events", methods=["GET"])
def api_analyze_job_events(job_id):
    """SSE で event をストリーミング配信する。"""
    if not _JOB_ID_RE.match(job_id):
        return jsonify({"error": "invalid job_id"}), 400
    try:
        snapshot = _job_to_dict(analyze_job.get_job(job_id))
    except KeyError:
        return jsonify({"error": "job not found"}), 404

    terminal_events = ("completed", "failed", "cancelled")
    is_terminal = snapshot["status"] in terminal_events
    # 既に終端状態でなければ、state event を yield する**前に** subscribe して
    # queue を確保する (state yield 中に publish された event を取りこぼさない)。
    sub_iter = None if is_terminal else analyze_progress.subscribe(job_id)

    def gen():
        try:
            yield (
                "event: state\n"
                f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            )
            if is_terminal:
                return
            for event, data in sub_iter:
                payload = json.dumps(data, ensure_ascii=False, default=str)
                yield f"event: {event}\ndata: {payload}\n\n"
                if event in terminal_events:
                    break
        finally:
            if sub_iter is not None:
                sub_iter.close()

    return Response(gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.route("/api/screenplay/analyze/<job_id>/confirm", methods=["POST"])
def api_confirm_analyze_job(job_id):
    """awaiting_confirm 状態のジョブを running に遷移させて Claude 続行。"""
    if not _JOB_ID_RE.match(job_id):
        return jsonify({"error": "invalid job_id"}), 400
    try:
        analyze_runner.confirm(job_id)
    except KeyError:
        return jsonify({"error": "job not found"}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify({"ok": True}), 200


@app.route("/api/projects/<ts>/abstract", methods=["GET"])
def api_get_project_abstract(ts):
    """project の現在 snapshot を生のまま返す (= 抽象台本、UI 編集対象)。

    completeness の判定は frontend が abstract から live 計算するので、
    diagnostics はレスポンスに含めない (`analyze.compose.diagnose_abstract` は
    関数として残しているため、CLI / 別ツールから引き続き利用可能)。
    """
    _validate_ts(ts)
    if not os.path.isdir(_ts_path(ts)):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    try:
        sp = staged_pipeline.load_project_abstract(_ts_path(ts))
    except FileNotFoundError:
        return jsonify({"error": "screenplay snapshot not found"}), 404
    return jsonify({
        "screenplay_path": staged_pipeline.project_screenplay_path(_ts_path(ts)),
        "abstract": sp,
    })


@app.route("/api/projects/<ts>/abstract", methods=["PUT"])
def api_put_project_abstract(ts):
    """project snapshot (= 抽象台本) を上書き保存し、Stage 1〜7 の承認を解除する。

    snapshot は抽象台本のまま保存される。Stage 2 以降が読むときに compose を
    都度走らせて派生フィールドを生成する (= staged_pipeline.load_project_screenplay)。
    保存は内容変更を意味するので承認は全解除 (assets は保持、再承認で続行可)。
    """
    _validate_ts(ts)
    ts_path = _ts_path(ts)
    if not os.path.isdir(ts_path):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    data = request.get_json(force=True) or {}
    abstract = data.get("abstract")
    if not isinstance(abstract, dict):
        return jsonify({"error": "abstract (object) is required"}), 400
    scenes = abstract.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return jsonify({"error": "abstract.scenes must be non-empty array"}), 400
    from screenplay_validator import validate_abstract
    errors = validate_abstract(abstract, strict=False)
    if errors:
        return jsonify({
            "error": "abstract のスキーマ検証に失敗しました",
            "errors": errors,
        }), 400
    with _screenplay_lock(ts):
        staged_pipeline.save_project_screenplay(ts_path, abstract)
    progress_store.revoke_all_approvals(ts_path)
    return jsonify({
        "screenplay_path": staged_pipeline.project_screenplay_path(ts_path),
        "scenes": len(scenes),
        "revoked_approvals": True,
    })


@app.route("/api/projects/<ts>/scene-boundaries", methods=["POST"])
def api_apply_scene_boundaries(ts):
    """TTS 完了後に scene 境界だけを再定義する。line のテキスト・順序は不変。

    body: {line_boundaries: [int, ...]}  scene 開始 line index (flat) 昇順、先頭は 0

    効果:
      - snapshot の scenes[] を再構築 (line は flat 順を保ち boundaries で再 group)
      - tts_full.mp3 から per-line / per-scene を新 scene index で再分割
      - bg / kling / scene / overlay 系の生成物を全削除し progress を reset
      - tts は generated 維持、approved 解除 (再確認させる)
      - **ElevenLabs API は呼ばれない** ので追加課金なし
    """
    _validate_ts(ts)
    ts_path = _ts_path(ts)
    if not os.path.isdir(ts_path):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    data = request.get_json(force=True) or {}
    raw = data.get("line_boundaries")
    if not isinstance(raw, list) or not all(isinstance(x, int) for x in raw):
        return jsonify({
            "error": "line_boundaries は int の list である必要があります",
        }), 400
    try:
        with _screenplay_lock(ts):
            result = staged_pipeline.apply_scene_boundaries(ts_path, raw)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("apply_scene_boundaries failed")
        return jsonify({"error": str(e)}), 500
    return jsonify({
        "ok": True,
        "scenes": result["scenes"],
        "lines": result["lines"],
    })


@app.route("/api/screenplay/analyze/<job_id>", methods=["DELETE"])
def api_cancel_analyze_job(job_id):
    """ジョブのキャンセルを要求 (各フェーズ境界で読まれて中断)。"""
    if not _JOB_ID_RE.match(job_id):
        return jsonify({"error": "invalid job_id"}), 400
    try:
        analyze_job.get_job(job_id)
    except KeyError:
        return jsonify({"error": "job not found"}), 404
    analyze_runner.cancel(job_id)
    return jsonify({"ok": True}), 202


# ───────────────── 静的設定 ─────────────────

@app.route("/api/config", methods=["GET"])
def api_config():
    """フロント表示用にconfig値を一部公開。"""
    voice_lib = [
        {"voice_id": v["voice_id"], "name": v.get("name"),
         "gender": v.get("gender"), "age": v.get("age"),
         "language": v.get("language")}
        for v in config.VOICE_LIBRARY
    ]
    return jsonify({
        "stages": progress_store.STAGES,
        "emotions": list(config.EMOTION_VOICE_PRESETS.keys()),
        "emotion_presets": config.EMOTION_VOICE_PRESETS,
        "emotion_intensities": list(config.EMOTION_INTENSITY_MULTIPLIERS.keys()),
        "available_audio_tags": config.AVAILABLE_AUDIO_TAGS,
        "emotion_audio_tags": config.EMOTION_AUDIO_TAGS,
        "voice_library": voice_lib,
        "default_voice_id": config.ELEVENLABS_VOICE_ID,
        "default_stability": config.ELEVENLABS_VOICE_STABILITY,
        "default_similarity_boost": config.ELEVENLABS_VOICE_SIMILARITY_BOOST,
        "default_style": config.ELEVENLABS_VOICE_STYLE,
        "video_width": config.VIDEO_WIDTH,
        "video_height": config.VIDEO_HEIGHT,
        "subtitle_y_from_bottom": config.SUBTITLE_Y_FROM_BOTTOM,
        "tts_pricing": _tts_pricing(),
        "cost_models": {
            "tts": elevenlabs_client.MODEL_ID,
            "bg": imagen_client.MODEL,
            "kling": fal_video_client.MODEL_ID,
            "lipsync": (
                config.SYNCSO_LIPSYNC_MODEL
                if config.LIPSYNC_PROVIDER == "syncso"
                else config.LIPSYNC_PROVIDER
            ),
            "analyze": video_analyzer.ANALYZER_MODEL,
        },
    })


# ───────────────── stage cache (Stage 3 BG / Stage 4 Kling) ─────────────────
#
# scan / use-cache / queue-fresh / rescan / decisions/bulk / generate-remaining /
# preview / blacklist / delete のロジックは bg / kling で共通。stage 別の差分は
# `_STAGE_CACHE_HANDLERS` に集約し、各エンドポイントは 1 行で stage を渡すだけ。

import bg_cache  # noqa: E402
import kling_cache  # noqa: E402

_HASH16_RE = re.compile(r'^[0-9a-f]{16}$')


def _now_iso() -> str:
    from datetime import datetime as _dt
    return _dt.now().isoformat(timespec="seconds")


class _StageCacheHandler:
    """1 stage 分の cache フローに必要な依存をひとまとめにする (= 単一責務)。"""

    def __init__(self, *, stage: str, cache_module, scan_fn, commit_fn,
                 generate_fresh_fn, clear_downstream_fn,
                 preview_mimetype: str, preview_ext: str,
                 generate_kind: str):
        self.stage = stage
        self.cache_module = cache_module
        self.scan_fn = scan_fn
        self.commit_fn = commit_fn
        self.generate_fresh_fn = generate_fresh_fn
        self.clear_downstream_fn = clear_downstream_fn
        self.preview_mimetype = preview_mimetype
        self.preview_ext = preview_ext
        self.generate_kind = generate_kind


_STAGE_CACHE_HANDLERS: dict[str, _StageCacheHandler] = {
    "bg": _StageCacheHandler(
        stage="bg",
        cache_module=bg_cache,
        scan_fn=lambda sp, td: scene_gen.bg_scan_cache(sp, td),
        commit_fn=lambda i, scene, sp, td, key: scene_gen.bg_commit_cache(
            i, scene, sp, td, key),
        generate_fresh_fn=lambda sp, td, indices: scene_gen.bg_generate_fresh(
            sp, td, indices),
        clear_downstream_fn=lambda i, td: scene_gen._clear_bg_downstream(i, td),
        preview_mimetype="image/png",
        preview_ext="png",
        generate_kind="bg-generate-remaining",
    ),
    "kling": _StageCacheHandler(
        stage="kling",
        cache_module=kling_cache,
        scan_fn=lambda sp, td: scene_gen.kling_scan_cache(sp, td),
        commit_fn=lambda i, scene, sp, td, key: scene_gen.kling_commit_cache(
            i, scene, sp, td, key),
        generate_fresh_fn=lambda sp, td, indices: scene_gen.kling_generate_fresh(
            sp, td, indices),
        clear_downstream_fn=lambda i, td: scene_gen._clear_kling_downstream(i, td),
        preview_mimetype="video/mp4",
        preview_ext="mp4",
        generate_kind="kling-generate-remaining",
    ),
}


def _resolve_handler(stage: str) -> _StageCacheHandler | None:
    return _STAGE_CACHE_HANDLERS.get(stage)


# ─── 各 endpoint は dispatch のみ。実体は _stage_* helper ─────────────


def _stage_scan_cache(ts: str, stage: str):
    handler = _resolve_handler(stage)
    if handler is None:
        return jsonify({"error": f"unknown stage: {stage}"}), 400
    if not os.path.isdir(_ts_path(ts)):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    sp, _ = _load_screenplay_for_project(ts)
    try:
        decisions = handler.scan_fn(sp, _ts_path(ts))
    except Exception as e:
        logger.exception("%s scan failed", stage)
        return jsonify({"error": str(e)}), 500
    progress_store.set_scan_result(_ts_path(ts), stage, decisions)
    return jsonify({
        "scene_decisions": decisions,
        "cache_scanned_at": progress_store.get_decisions(
            _ts_path(ts), stage)["cache_scanned_at"],
    })


def _stage_get_decisions(ts: str, stage: str):
    handler = _resolve_handler(stage)
    if handler is None:
        return jsonify({"error": f"unknown stage: {stage}"}), 400
    if not os.path.isdir(_ts_path(ts)):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    return jsonify(progress_store.get_decisions(_ts_path(ts), stage))


def _stage_use_cache(ts: str, stage: str, scene_idx: int):
    handler = _resolve_handler(stage)
    if handler is None:
        return jsonify({"error": f"unknown stage: {stage}"}), 400
    if not os.path.isdir(_ts_path(ts)):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    data = request.get_json(force=True) or {}
    cache_key = data.get("key")
    if not cache_key:
        return jsonify({"error": "key required"}), 400
    sp, _ = _load_screenplay_for_project(ts)
    scenes = sp.get("scenes") or []
    if scene_idx < 0 or scene_idx >= len(scenes):
        return jsonify({"error": "scene_idx out of range"}), 400
    try:
        handler.commit_fn(scene_idx, scenes[scene_idx], sp,
                           _ts_path(ts), cache_key)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.exception("%s use_cache failed", stage)
        return jsonify({"error": str(e)}), 500
    progress_store.set_scene_decision(
        _ts_path(ts), stage, scene_idx, "cache", cache_key)
    return jsonify({"ok": True, "decision": "cache", "key": cache_key})


def _stage_queue_fresh(ts: str, stage: str, scene_idx: int):
    handler = _resolve_handler(stage)
    if handler is None:
        return jsonify({"error": f"unknown stage: {stage}"}), 400
    if not os.path.isdir(_ts_path(ts)):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    sp, _ = _load_screenplay_for_project(ts)
    scenes = sp.get("scenes") or []
    if scene_idx < 0 or scene_idx >= len(scenes):
        return jsonify({"error": "scene_idx out of range"}), 400
    progress_store.set_scene_decision(
        _ts_path(ts), stage, scene_idx, "fresh", None)
    return jsonify({"ok": True, "decision": "fresh"})


def _stage_scene_rescan(ts: str, stage: str, scene_idx: int):
    handler = _resolve_handler(stage)
    if handler is None:
        return jsonify({"error": f"unknown stage: {stage}"}), 400
    if not os.path.isdir(_ts_path(ts)):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    sp, _ = _load_screenplay_for_project(ts)
    scenes = sp.get("scenes") or []
    if scene_idx < 0 or scene_idx >= len(scenes):
        return jsonify({"error": "scene_idx out of range"}), 400
    try:
        decisions_all = handler.scan_fn(sp, _ts_path(ts))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    new_rec = decisions_all.get(str(scene_idx)) or {}
    cur = progress_store.get_decisions(_ts_path(ts), stage)
    decisions = dict(cur.get("scene_decisions") or {})
    decisions[str(scene_idx)] = new_rec
    progress_store.set_scan_result(_ts_path(ts), stage, decisions)
    return jsonify({"ok": True, "scene_decision": new_rec})


def _stage_decisions_bulk(ts: str, stage: str):
    handler = _resolve_handler(stage)
    if handler is None:
        return jsonify({"error": f"unknown stage: {stage}"}), 400
    if not os.path.isdir(_ts_path(ts)):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    data = request.get_json(force=True) or {}
    action = data.get("action")
    if action not in ("all-cache", "all-fresh"):
        return jsonify({"error": "action must be all-cache or all-fresh"}), 400
    sp, _ = _load_screenplay_for_project(ts)
    scenes = sp.get("scenes") or []
    cur = progress_store.get_decisions(_ts_path(ts), stage)
    decisions = dict(cur.get("scene_decisions") or {})
    summary = {"adopted": 0, "queued_fresh": 0, "errors": []}
    for i, scene in enumerate(scenes):
        rec = dict(decisions.get(str(i)) or {})
        if action == "all-cache":
            cands = rec.get("candidates") or []
            if cands:
                key = cands[0]["key"]
                try:
                    handler.commit_fn(i, scene, sp, _ts_path(ts), key)
                    rec["decision"] = "cache"
                    rec["decided_key"] = key
                    rec["decided_at"] = _now_iso()
                    summary["adopted"] += 1
                except Exception as e:
                    summary["errors"].append({"scene": i, "error": str(e)})
            elif rec.get("decision") != "fresh":
                rec["decision"] = "fresh"
                rec["decided_at"] = _now_iso()
                summary["queued_fresh"] += 1
        else:  # all-fresh
            try:
                handler.clear_downstream_fn(i, _ts_path(ts))
            except Exception:
                pass
            rec["decision"] = "fresh"
            rec["decided_key"] = None
            rec["decided_at"] = _now_iso()
            summary["queued_fresh"] += 1
        decisions[str(i)] = rec
    progress_store.set_scan_result(_ts_path(ts), stage, decisions)
    return jsonify({"ok": True, "summary": summary,
                    "scene_decisions": decisions})


def _stage_generate_remaining(ts: str, stage: str):
    handler = _resolve_handler(stage)
    if handler is None:
        return jsonify({"error": f"unknown stage: {stage}"}), 400
    if not os.path.isdir(_ts_path(ts)):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    sp, _ = _load_screenplay_for_project(ts)
    n_scenes = len(sp.get("scenes") or [])
    cur = progress_store.get_decisions(_ts_path(ts), stage)
    decisions = cur.get("scene_decisions") or {}
    pending: list[int] = []
    fresh_queue: list[int] = []
    for i in range(n_scenes):
        rec = decisions.get(str(i)) or {}
        d = rec.get("decision")
        if d == "fresh":
            fresh_queue.append(i)
        elif d != "cache":
            pending.append(i)
    if pending:
        return jsonify({
            "error": "未判断のシーンがあります",
            "pending_scenes": pending,
        }), 400

    job_id = _spawn_job(
        lambda: _generate_fresh_and_mark(stage, sp, _ts_path(ts), fresh_queue),
        kind=handler.generate_kind, ts=ts,
    )
    return jsonify({"job_id": job_id, "fresh_scenes": fresh_queue})


def _generate_fresh_and_mark(stage: str, sp: dict, ts_path: str,
                              scene_indices: list[int]) -> None:
    """fresh queue を生成し、stage を generated とマークする。"""
    handler = _resolve_handler(stage)
    if handler is None:
        raise RuntimeError(f"unknown stage: {stage}")
    if scene_indices:
        handler.generate_fresh_fn(sp, ts_path, scene_indices)
    progress_store.mark_generated(ts_path, stage)


def _stage_cache_entries(stage: str):
    handler = _resolve_handler(stage)
    if handler is None:
        return jsonify({"error": f"unknown stage: {stage}"}), 400
    return jsonify({"entries": handler.cache_module.list_entries()})


def _stage_cache_blacklist(stage: str, key: str):
    handler = _resolve_handler(stage)
    if handler is None:
        return jsonify({"error": f"unknown stage: {stage}"}), 400
    if not _HASH16_RE.match(key):
        return jsonify({"error": "invalid key"}), 400
    data = request.get_json(force=True) or {}
    reason = data.get("reason") or ""
    ok = handler.cache_module.blacklist(key, reason)
    if not ok:
        return jsonify({"error": "entry not found"}), 404
    return jsonify({"ok": True})


def _stage_cache_delete(stage: str, key: str):
    handler = _resolve_handler(stage)
    if handler is None:
        return jsonify({"error": f"unknown stage: {stage}"}), 400
    if not _HASH16_RE.match(key):
        return jsonify({"error": "invalid key"}), 400
    mp4_or_png, meta = handler.cache_module._entry_paths(key)
    deleted = False
    for p in (mp4_or_png, meta):
        if p.exists():
            try:
                os.remove(p)
                deleted = True
            except Exception as e:
                return jsonify({"error": str(e)}), 500
    if not deleted:
        return jsonify({"error": "entry not found"}), 404
    return jsonify({"ok": True, "deleted": key})


def _stage_cache_preview(stage: str, key: str):
    handler = _resolve_handler(stage)
    if handler is None:
        abort(400)
    if not _HASH16_RE.match(key):
        abort(400)
    asset = handler.cache_module.lookup(key)
    if asset is None:
        return "", 404
    return send_file(str(asset), mimetype=handler.preview_mimetype,
                      conditional=True)


# ─── BG (Stage 3) endpoints ────────────────────


@app.route("/api/projects/<ts>/stages/bg/scan-cache", methods=["POST"])
def api_bg_scan_cache(ts):
    """Stage 3a: 全シーンの cache を scan して判断状態を初期化する (同期)。"""
    _validate_ts(ts)
    return _stage_scan_cache(ts, "bg")


@app.route("/api/projects/<ts>/stages/bg/decisions", methods=["GET"])
def api_bg_decisions(ts):
    _validate_ts(ts)
    return _stage_get_decisions(ts, "bg")


@app.route(
    "/api/projects/<ts>/stages/bg/scenes/<int:scene_idx>/use-cache",
    methods=["POST"])
def api_bg_use_cache(ts, scene_idx):
    """Stage 3b: 1 scene の cache 採用 (= PNG copy + 下流クリア)。"""
    _validate_ts(ts)
    return _stage_use_cache(ts, "bg", scene_idx)


@app.route(
    "/api/projects/<ts>/stages/bg/scenes/<int:scene_idx>/queue-fresh",
    methods=["POST"])
def api_bg_queue_fresh(ts, scene_idx):
    _validate_ts(ts)
    return _stage_queue_fresh(ts, "bg", scene_idx)


@app.route(
    "/api/projects/<ts>/stages/bg/scenes/<int:scene_idx>/rescan",
    methods=["POST"])
def api_bg_scene_rescan(ts, scene_idx):
    _validate_ts(ts)
    return _stage_scene_rescan(ts, "bg", scene_idx)


@app.route("/api/projects/<ts>/stages/bg/decisions/bulk", methods=["POST"])
def api_bg_decisions_bulk(ts):
    _validate_ts(ts)
    return _stage_decisions_bulk(ts, "bg")


@app.route("/api/projects/<ts>/stages/bg/generate-remaining", methods=["POST"])
def api_bg_generate_remaining(ts):
    _validate_ts(ts)
    return _stage_generate_remaining(ts, "bg")


@app.route("/api/bg-cache/entries", methods=["GET"])
def api_bg_cache_entries():
    return _stage_cache_entries("bg")


@app.route("/api/bg-cache/<key>/blacklist", methods=["POST"])
def api_bg_cache_blacklist(key):
    return _stage_cache_blacklist("bg", key)


@app.route("/api/bg-cache/<key>", methods=["DELETE"])
def api_bg_cache_delete(key):
    return _stage_cache_delete("bg", key)


@app.route("/api/bg-cache/<key>/preview.png", methods=["GET"])
def api_bg_cache_preview(key):
    return _stage_cache_preview("bg", key)


# ─── Kling (Stage 4) endpoints ─────────────────


@app.route("/api/projects/<ts>/stages/kling/scan-cache", methods=["POST"])
def api_kling_scan_cache(ts):
    """Stage 4a: 全シーンの cache を scan して判断状態を初期化する (同期)。"""
    _validate_ts(ts)
    return _stage_scan_cache(ts, "kling")


@app.route("/api/projects/<ts>/stages/kling/decisions", methods=["GET"])
def api_kling_decisions(ts):
    _validate_ts(ts)
    return _stage_get_decisions(ts, "kling")


@app.route(
    "/api/projects/<ts>/stages/kling/scenes/<int:scene_idx>/use-cache",
    methods=["POST"])
def api_kling_use_cache(ts, scene_idx):
    """Stage 4b: 1 scene の cache 採用 (= raw mp4 copy + trim 同期実行)。"""
    _validate_ts(ts)
    return _stage_use_cache(ts, "kling", scene_idx)


@app.route(
    "/api/projects/<ts>/stages/kling/scenes/<int:scene_idx>/queue-fresh",
    methods=["POST"])
def api_kling_queue_fresh(ts, scene_idx):
    _validate_ts(ts)
    return _stage_queue_fresh(ts, "kling", scene_idx)


@app.route(
    "/api/projects/<ts>/stages/kling/scenes/<int:scene_idx>/rescan",
    methods=["POST"])
def api_kling_scene_rescan(ts, scene_idx):
    _validate_ts(ts)
    return _stage_scene_rescan(ts, "kling", scene_idx)


@app.route("/api/projects/<ts>/stages/kling/decisions/bulk", methods=["POST"])
def api_kling_decisions_bulk(ts):
    _validate_ts(ts)
    return _stage_decisions_bulk(ts, "kling")


@app.route("/api/projects/<ts>/stages/kling/generate-remaining",
           methods=["POST"])
def api_kling_generate_remaining(ts):
    _validate_ts(ts)
    return _stage_generate_remaining(ts, "kling")


@app.route("/api/kling-cache/entries", methods=["GET"])
def api_kling_cache_entries():
    return _stage_cache_entries("kling")


@app.route("/api/kling-cache/<key>/blacklist", methods=["POST"])
def api_kling_cache_blacklist(key):
    return _stage_cache_blacklist("kling", key)


@app.route("/api/kling-cache/<key>", methods=["DELETE"])
def api_kling_cache_delete(key):
    return _stage_cache_delete("kling", key)


@app.route("/api/kling-cache/<key>/preview.mp4", methods=["GET"])
def api_kling_cache_preview(key):
    return _stage_cache_preview("kling", key)


# ───────────────── コスト記録 / 動的見積もり / レポート ─────────────────

@app.route("/api/cost/pricebook", methods=["GET"])
def api_cost_pricebook():
    """単価カタログ (運用者管理) を JSON で返す。"""
    return jsonify({
        "pricebook": cost_pricebook.load(),
        "jpy_per_usd": cost_pricebook.jpy_per_usd(),
    })


def _estimate_for_stage(stage: str, args) -> tuple[dict, int]:
    """``/api/cost/estimate/<stage>`` の stage 別ロジック (純粋関数)。"""
    model = args.get("model")
    if not model:
        return {"error": "model required"}, 400
    try:
        if stage == "tts":
            est = cost_estimator.estimate_tts(
                characters=int(args.get("characters", 0)),
                model=model,
            )
        elif stage == "bg":
            est = cost_estimator.estimate_imagen(
                image_count=int(args.get("image_count", 1)),
                model=model,
            )
        elif stage == "kling":
            est = cost_estimator.estimate_kling(
                duration_sec=float(args.get("duration_sec", 0)),
                model=model,
            )
        elif stage == "lipsync":
            est = cost_estimator.estimate_lipsync(
                duration_sec=float(args.get("duration_sec", 0)),
                model=model,
            )
        elif stage == "analyze":
            est = cost_estimator.estimate_analyze(
                input_tokens=int(args.get("input_tokens", 0)),
                output_tokens=int(args.get("output_tokens", 0)),
                model=model,
            )
        else:
            return {"error": f"unknown stage: {stage}"}, 400
    except (ValueError, TypeError) as e:
        return {"error": str(e)}, 400
    return asdict(est), 200


@app.route("/api/cost/estimate/<stage>", methods=["GET"])
def api_cost_estimate(stage):
    """動的見積もり (履歴 only)。履歴が ``MIN_HISTORY_SAMPLES`` 未満なら ``confidence=insufficient``。"""
    payload, status = _estimate_for_stage(stage, request.args)
    return jsonify(payload), status


@app.route("/api/cost/median/<stage>", methods=["GET"])
def api_cost_median(stage):
    """履歴から per-unit cost の median を返す (frontend で rate × units 計算用)。"""
    model = request.args.get("model")
    if not model:
        return jsonify({"error": "model required"}), 400
    try:
        rate = cost_estimator.median_rate(stage, model)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(asdict(rate))


@app.route("/api/cost/report/project/<ts>", methods=["GET"])
def api_cost_report_project(ts):
    """プロジェクト別の実コストレポート。"""
    return jsonify(asdict(cost_report.report_for_project(ts)))


@app.route("/api/cost/report", methods=["GET"])
def api_cost_report_overall():
    """全体レポート。``?since=<ISO8601>`` で期間絞り込み可。"""
    since = request.args.get("since")
    return jsonify(asdict(cost_report.report_overall(since=since)))


# ───────────────── React 静的配信 ─────────────────

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    """frontend/dist のSPAを配信。/api/ 以下は除外。"""
    if path.startswith("api/") or path.startswith("asset/"):
        abort(404)
    if not os.path.isdir(FRONTEND_DIST):
        return ("frontend未ビルド: `cd frontend && npm install && npm run build`",
                503)
    target = os.path.join(FRONTEND_DIST, path)
    if path and os.path.exists(target):
        return send_from_directory(FRONTEND_DIST, path)
    return send_from_directory(FRONTEND_DIST, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PREVIEW_PORT", "5555"))
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    logger.info("プレビューサーバー起動中: http://%s:%d", host, port)
    app.run(host=host, port=port, debug=debug)
