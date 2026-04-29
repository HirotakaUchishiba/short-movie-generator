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
from flask import Flask, jsonify, request, send_file, abort, send_from_directory
from flask_cors import CORS

import config
import log_setup
import progress_store
import scene_gen
import staged_pipeline

log_setup.setup()
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder=None)
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
    import elevenlabs_client
    model = elevenlabs_client.MODEL_ID
    multiplier = elevenlabs_client.credit_multiplier(model)
    return {
        "model": model,
        "credit_multiplier": multiplier,
        "usd_per_credit": 0.000198,
        "plan_label": "Pro plan ($99/500k credits)",
        "available_models": elevenlabs_client.available_models(),
        "global_speed": float(config.TTS_GLOBAL_SPEED),
        "speed_min": 0.5,
        "speed_max": 2.0,
        "trim_silences": bool(getattr(config, "TTS_TRIM_LONG_SILENCES", False)),
        "max_silence_ms": float(getattr(config, "TTS_MAX_SILENCE_MS", 250)),
        "note": (
            f"{model} は1文字あたり {multiplier} credits 消費。"
            "他プランの場合は usd_per_credit を上書き。"
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
    """temp_dir/metadata.json から台本名を取得し台本JSONを読み込む。"""
    meta = staged_pipeline.read_metadata(_ts_path(ts))
    if not meta:
        abort(404, "プロジェクトのmetadataがありません")
    name = meta.get("screenplay_name")
    if not name:
        abort(404, "metadataにscreenplay_nameがありません")
    sp = staged_pipeline.load_screenplay(name)
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
    data = request.get_json(force=True) or {}
    name = data.get("screenplay_name")
    if not name:
        return jsonify({"error": "screenplay_name が必要です"}), 400
    try:
        staged_pipeline.load_screenplay(name)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404

    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_path = _ts_path(ts)
    os.makedirs(ts_path, exist_ok=True)

    screenplay = staged_pipeline.load_screenplay(name)
    try:
        staged_pipeline.run_script(screenplay, name, ts_path)
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
    return jsonify({
        "timestamp": ts,
        "screenplay_name": name,
        "screenplay": sp,
        "progress": progress,
        "current_stage": progress_store.current_stage(_ts_path(ts)),
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


# 日本語の修正指示で background_prompt / animation_prompt を書き換える。
# action="preview" → 修正後 prompt を返すだけ (保存しない、UI で diff 確認用)
# action="apply"   → 修正後 prompt を screenplay に保存 (regen は呼出側 UI で実施)
@app.route("/api/projects/<ts>/scenes/<int:scene_idx>/revise-prompt",
            methods=["POST"])
def api_revise_prompt(ts, scene_idx):
    _validate_ts(ts)
    if not os.path.isdir(_ts_path(ts)):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    sp, name = _load_screenplay_for_project(ts)
    scenes = sp.get("scenes") or []
    if scene_idx >= len(scenes):
        return jsonify({"error": f"scene_idx範囲外: {scene_idx}"}), 400

    body = request.get_json(silent=True) or {}
    field = body.get("field")
    instruction_ja = body.get("instruction_ja")
    action = body.get("action", "preview")
    if field not in ("background_prompt", "animation_prompt"):
        return jsonify({"error": "field は background_prompt または animation_prompt"}), 400
    if not isinstance(instruction_ja, str) or not instruction_ja.strip():
        return jsonify({"error": "instruction_ja (日本語の修正指示) が必要"}), 400

    if action == "preview":
        revised_text = body.get("revised")
        # 「適用」ボタン押下時に preview で得た revised を渡してくる場合は LLM を再実行しない。
        # ただし通常 preview は LLM を呼ぶ。ここでは preview = LLM 呼出 と固定する。
        scene = scenes[scene_idx]
        if field == "background_prompt":
            current = scene_gen._build_background_prompt(
                scene, sp, ts_path=_ts_path(ts), s_idx=scene_idx)
        else:
            current = scene_gen._get_animation_prompt(
                scene, ts_path=_ts_path(ts), s_idx=scene_idx)

        import prompt_revise
        try:
            result = prompt_revise.revise(
                current_prompt=current,
                instruction_ja=instruction_ja,
                field=field,
            )
        except (ValueError, RuntimeError) as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            logger.exception("prompt_revise failed")
            return jsonify({"error": f"修正生成失敗: {e}"}), 500
        return jsonify({
            "scene_idx": scene_idx,
            "field": field,
            "previous": current,
            "revised": result["revised"],
            "model": result["model"],
        })

    if action == "apply":
        revised = body.get("revised")
        if not isinstance(revised, str) or not revised.strip():
            return jsonify({"error": "revised (適用する prompt) が必要"}), 400
        from screenplay_validator import validate_screenplay
        with _screenplay_lock(name):
            disk_sp = staged_pipeline.load_screenplay(name)
            disk_scenes = disk_sp.get("scenes") or []
            if scene_idx >= len(disk_scenes):
                return jsonify({"error": "scene_idx範囲外"}), 400
            disk_scenes[scene_idx][field] = revised
            errors = validate_screenplay(disk_sp, strict=False)
            if errors:
                return jsonify({"error": "validator失敗", "details": errors}), 400
            staged_pipeline.save_screenplay(name, disk_sp)
        return jsonify({
            "scene_idx": scene_idx,
            "field": field,
            "applied": True,
            "revised": revised,
        })

    return jsonify({"error": f"未知のaction: {action}"}), 400


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
    if stage not in {"tts", "bg", "kling", "scene", "overlay"}:
        return jsonify({"error": f"このstageは再生成不可: {stage}"}), 400

    sp, name = _load_screenplay_for_project(ts)
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
    data = request.get_json(force=True) or {}
    sp = data.get("screenplay")
    if not isinstance(sp, dict):
        return jsonify({"error": "screenplayが必要です"}), 400
    _, name = _load_screenplay_for_project(ts)
    try:
        from screenplay_validator import validate_screenplay
        errors = validate_screenplay(sp, strict=False)
        if errors:
            return jsonify({"error": "validator失敗", "details": errors}), 400
        with _screenplay_lock(name):
            staged_pipeline.save_screenplay(name, sp)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


# Server-side merge: line 単位の field patch。
# 全 screenplay を投げる PUT と異なり、複数 client が並行 patch しても他 line を上書きしない。
@app.route("/api/projects/<ts>/lines/<int:scene_idx>/<int:line_idx>",
            methods=["PATCH"])
def api_patch_line(ts, scene_idx, line_idx):
    _validate_ts(ts)
    data = request.get_json(force=True) or {}
    patch = data.get("patch")
    if not isinstance(patch, dict):
        return jsonify({"error": "patch (object) が必要です"}), 400
    # 許可フィールドの allowlist (誤更新防止)
    allowed = {"silence_after_ms", "text", "tts_text", "rate", "emotion",
                "emotion_intensity", "delivery", "audio_tags",
                "pronunciation_hints", "voice_overrides"}
    unknown = set(patch.keys()) - allowed
    if unknown:
        return jsonify({"error": f"許可されていないフィールド: {sorted(unknown)}"}), 400

    _, name = _load_screenplay_for_project(ts)
    try:
        from screenplay_validator import validate_screenplay
        with _screenplay_lock(name):
            sp = staged_pipeline.load_screenplay(name)
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
            errors = validate_screenplay(sp, strict=False)
            if errors:
                return jsonify({"error": "validator失敗", "details": errors}), 400
            staged_pipeline.save_screenplay(name, sp)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


# scene 単位の patch (emotion_cue_overrides / tags / wardrobe.identifier 等)。
# enum 制約は schema 側で担保される。
@app.route("/api/projects/<ts>/scenes/<int:scene_idx>", methods=["PATCH"])
def api_patch_scene(ts, scene_idx):
    _validate_ts(ts)
    data = request.get_json(force=True) or {}
    patch = data.get("patch")
    if not isinstance(patch, dict):
        return jsonify({"error": "patch (object) が必要です"}), 400
    allowed = {"emotion_cue_overrides", "tags", "wardrobe", "background_prompt",
                "animation_prompt", "lipsync", "duration", "label",
                "character_refs"}
    unknown = set(patch.keys()) - allowed
    if unknown:
        return jsonify({"error": f"許可されていないフィールド: {sorted(unknown)}"}), 400

    _, name = _load_screenplay_for_project(ts)
    try:
        from screenplay_validator import validate_screenplay
        with _screenplay_lock(name):
            sp = staged_pipeline.load_screenplay(name)
            scenes = sp.get("scenes") or []
            if scene_idx >= len(scenes):
                return jsonify({"error": f"scene_idx範囲外: {scene_idx}"}), 400
            scene = scenes[scene_idx]
            for k, v in patch.items():
                if v is None:
                    scene.pop(k, None)
                else:
                    scene[k] = v
            errors = validate_screenplay(sp, strict=False)
            if errors:
                return jsonify({"error": "validator失敗", "details": errors}), 400
            staged_pipeline.save_screenplay(name, sp)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


# screenplay-level patch (scoped_augmentations / wardrobe_continuity 等)。
@app.route("/api/projects/<ts>/screenplay-meta", methods=["PATCH"])
def api_patch_screenplay_meta(ts):
    _validate_ts(ts)
    data = request.get_json(force=True) or {}
    patch = data.get("patch")
    if not isinstance(patch, dict):
        return jsonify({"error": "patch (object) が必要です"}), 400
    allowed = {"scoped_augmentations", "wardrobe_continuity",
                "bgm_path", "bgm_volume_db", "audio_mode",
                "subtitle_y_from_bottom"}
    unknown = set(patch.keys()) - allowed
    if unknown:
        return jsonify({"error": f"許可されていないフィールド: {sorted(unknown)}"}), 400

    _, name = _load_screenplay_for_project(ts)
    try:
        from screenplay_validator import validate_screenplay
        with _screenplay_lock(name):
            sp = staged_pipeline.load_screenplay(name)
            for k, v in patch.items():
                if v is None:
                    sp.pop(k, None)
                else:
                    sp[k] = v
            errors = validate_screenplay(sp, strict=False)
            if errors:
                return jsonify({"error": "validator失敗", "details": errors}), 400
            staged_pipeline.save_screenplay(name, sp)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


# preset ライブラリ全部をフロントに返す。UI dropdown 用。
@app.route("/api/presets", methods=["GET"])
def api_presets():
    import config as _config
    return jsonify({
        "libraries": _config.PROMPT_PRESET_LIBRARIES,
        "labels_ja": _config.PRESET_LABELS_JA,
        "category_labels_ja": _config.PRESET_CATEGORY_LABELS_JA,
        "scene_tags": _config.SCENE_TAGS,
        "scene_tag_labels_ja": _config.SCENE_TAG_LABELS_JA,
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
    if not re.match(r'^[\w\-]+$', name):
        abort(400)
    p = os.path.join(config.CHARACTERS_DIR, f"{name}.png")
    if os.path.exists(p):
        return send_file(p, mimetype="image/png")
    return "", 404


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
    })


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
