#!/usr/bin/env python3
"""段階的ゲート方式のプレビューサーバ (REST API only)。

各 stage の生成・確認・承認・再生成 API を提供する。フロントは frontend/ の React を使用。
"""
import json
import logging
import os
import re
import sys
import time
from flask import Flask, jsonify, request, send_file, abort, send_from_directory, Response
from flask_cors import CORS

import config
import job_store
import log_setup
import progress_store
import scene_gen
import staged_pipeline
from analyze import job as analyze_job
from analyze import progress as analyze_progress
from analyze import runner as analyze_runner
from analytics import db as _analytics_db

log_setup.setup()
logger = logging.getLogger(__name__)

# 起動時に analytics DB schema を最新化する。
# analyze_jobs / analyze_phases / reference_videos テーブルが含まれていない
# 古い DB でも CREATE TABLE IF NOT EXISTS で安全に追加される。
_analytics_db.init_db()


def _bootstrap_intent_suggestions_inbox() -> None:
    """旧 ``screenplays/*.suggested_intents.json`` を inbox に吸い上げる
    one-shot migration。inbox がすでに非空なら skip (= 起動毎の二重実行防止)。

    pytest 実行中は副作用回避のため skip (= 各 test は monkeypatch で
    INTENT_SUGGESTIONS_PATH を tmp_path に向けているが、import 時 bootstrap は
    本物の path を見てしまうため)。

    設計 doc: docs/plannings/2026-05-10_intent-suggestion-flow.md §6 Phase 4
    """

    if "pytest" in sys.modules or os.getenv("PYTEST_CURRENT_TEST"):
        return
    inbox_path = os.fspath(config.INTENT_SUGGESTIONS_PATH)
    # inbox に 1 entry でもあれば既に bootstrap 済みとみなす (= idempotent)
    try:
        if os.path.exists(inbox_path) and os.path.getsize(inbox_path) > 4:
            return
    except OSError:
        return
    try:
        from scripts.migrate_intent_suggestions import run as _migrate_run
        summary = _migrate_run()
        if int(summary.get("files_migrated", 0)) > 0:
            logger.info(
                "[bootstrap] intent_suggestions migrated: %d files / %d entries",
                summary["files_migrated"], summary["entries_upserted"],
            )
    except (ImportError, OSError, ValueError) as e:
        logger.warning("[bootstrap] intent_suggestions migration skipped: %s", e)


_bootstrap_intent_suggestions_inbox()

app = Flask(__name__, static_folder=None)
# 動画アップロード上限。既定 2GB、PREVIEW_MAX_UPLOAD_MB env で上書き可能。
_max_upload_mb = int(os.getenv("PREVIEW_MAX_UPLOAD_MB", "2048"))
app.config["MAX_CONTENT_LENGTH"] = _max_upload_mb * 1024 * 1024
CORS(app)

# Blueprint 段階移行: 残るのは preview_server に内在する screenplay PUT /
# stage cache (bg/kling) / analyze job / character_meta / location CRUD 系
# (= 別 PR で順次)。routes/__init__.py の roadmap 参照。
from routes.assets import assets_bp  # noqa: E402
from routes.config import config_bp  # noqa: E402
from routes.cost import cost_bp  # noqa: E402
from routes.final_publish import final_publish_bp  # noqa: E402
from routes.clip_library import clip_library_bp  # noqa: E402
from routes.intent_suggestions import intent_suggestions_bp  # noqa: E402
from routes.intent_catalog import intent_catalog_bp  # noqa: E402
from routes.analyze import analyze_bp  # noqa: E402
from routes.catalogs import catalogs_bp  # noqa: E402
from routes.character_metas import character_metas_bp  # noqa: E402
from routes.jobs import jobs_bp  # noqa: E402
from routes.locations import locations_bp  # noqa: E402
from routes.projects import projects_bp  # noqa: E402
from routes.reference_videos import reference_videos_bp  # noqa: E402
from routes.screenplay import screenplay_bp  # noqa: E402
from routes.stage_cache import stage_cache_bp  # noqa: E402
from routes.stages import stages_bp  # noqa: E402

app.register_blueprint(cost_bp)
app.register_blueprint(config_bp)
app.register_blueprint(projects_bp)
app.register_blueprint(intent_catalog_bp)
app.register_blueprint(clip_library_bp)
app.register_blueprint(intent_suggestions_bp)
app.register_blueprint(stages_bp)
app.register_blueprint(final_publish_bp)
app.register_blueprint(assets_bp)
app.register_blueprint(screenplay_bp)
app.register_blueprint(analyze_bp)
app.register_blueprint(reference_videos_bp)
app.register_blueprint(locations_bp)
app.register_blueprint(character_metas_bp)
app.register_blueprint(catalogs_bp)
app.register_blueprint(jobs_bp)
app.register_blueprint(stage_cache_bp)


_AUTH_TOKEN = os.getenv("PREVIEW_AUTH_TOKEN", "").strip() or None
# CORS preflight (OPTIONS) と asset / index 配信は <video>, <img> の直叩きで
# Authorization ヘッダを付けられないので bypass。Tailscale が外側を守っている前提
_AUTH_BYPASS_PREFIXES = ("/asset/", "/static/")


@app.before_request
def _check_auth_token():
    if _AUTH_TOKEN is None:
        return None
    if request.method == "OPTIONS":
        return None
    p = request.path or ""
    if any(p.startswith(prefix) for prefix in _AUTH_BYPASS_PREFIXES):
        return None
    if p in ("/", "/healthz"):
        return None
    auth = request.headers.get("Authorization", "")
    if auth == f"Bearer {_AUTH_TOKEN}":
        return None
    return api_error("UNAUTHORIZED", "unauthorized", 401)


@app.before_request
def _assign_request_id() -> None:
    incoming = request.headers.get("X-Request-ID")
    log_setup.set_request_id(incoming or None)


@app.after_request
def _emit_request_id_header(resp: Response) -> Response:
    resp.headers["X-Request-ID"] = log_setup.get_request_id()
    return resp

TEMP_DIR = config.TEMP_DIR
SCREENPLAYS_DIR = config.SCREENPLAYS_DIR
OUTPUT_DIR = config.OUTPUT_DIR

# 共有 job state は job_runner.py を SSOT とする。Blueprint 化される routes
# (= routes/stages.py / routes/publish.py 等) からも安全に呼べる。
import job_runner  # noqa: E402

_jobs = job_runner._jobs
_jobs_lock = job_runner._jobs_lock
# screenplay disk write の serialize 用 (per-name) は staged_pipeline に移動。
# 同じ Lock を REST patch ハンドラと TTS regen 後の永続化が共有する。
_screenplay_lock = staged_pipeline.screenplay_lock

FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")


# /api/config/* は routes/config.py の Blueprint に移管済み
# (= /api/config, /api/config/{model,speed,silences,qa-tags} の 5 routes)。


@app.after_request
def _no_cache_for_assets(resp):
    """生成物 (/asset/) はブラウザにキャッシュさせない。再生成後即座に最新が見える。"""
    if request.path.startswith("/asset/"):
        resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


# Blueprint 分割の段階移行 (= routes/__init__.py 参照) のため、検証ヘルパは
# routes/_helpers.py を SSOT とし、ここでは shim を残す (= 既存 import 互換)。
from routes import _helpers as _route_helpers  # noqa: E402
from routes._helpers import api_error  # noqa: E402


def _validate_ts(ts: str) -> str:
    return _route_helpers.validate_ts(ts)


def _ts_path(ts: str) -> str:
    return _route_helpers.ts_path(ts, temp_dir=TEMP_DIR)


def _safe_join(base: str, *parts: str) -> str:
    return _route_helpers.safe_join(base, *parts)


def _load_screenplay_for_project(ts: str) -> tuple[dict, str]:
    """互換 shim: routes._helpers.load_screenplay_for_project に移管済み。"""
    return _route_helpers.load_screenplay_for_project(ts, temp_dir=TEMP_DIR)


def _ffprobe_duration(path: str) -> float:
    """互換 shim: routes._helpers.ffprobe_duration に移管済み。"""
    return _route_helpers.ffprobe_duration(path)


# /api/projects (= 一覧 + 作成 + 詳細) は routes/projects.py の Blueprint に
# 移管済み。互換 shim で _list_screenplays / _split_caption /
# _project_display_title を re-export し、既存テストを温存。
from routes.projects import (  # noqa: E402, F401
    _list_screenplays,
    _project_display_title,
    _split_caption,
)


# ElevenLabs に実際に送信される原文を返す。
# scene_gen._build_screenplay_text を呼んで line を separator で連結した結果と、
# 各 line の char range (char_start, char_end) を返す。UI 透明性のため。
@app.route("/api/projects/<ts>/tts-source", methods=["GET"])
def api_tts_source(ts):
    _validate_ts(ts)
    if not os.path.isdir(_ts_path(ts)):
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
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
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
    sp, _ = _load_screenplay_for_project(ts)
    scenes = sp.get("scenes") or []
    if scene_idx >= len(scenes):
        return api_error(
            "SCENE_INDEX_OUT_OF_RANGE",
            f"scene_idx範囲外: {scene_idx}", 400,
            scene_idx=scene_idx, scene_count=len(scenes),
        )
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
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
    return jsonify({
        "progress": progress_store.load(_ts_path(ts)),
        "current_stage": progress_store.current_stage(_ts_path(ts)),
    })


# /api/projects/<ts>/{run-next,approve,reject,regen} は routes/stages.py
# の Blueprint に移管済み。互換 shim で _archive_before_regen /
# _stage_artifact_paths / _REJECT_NOTE_MAX_LENGTH を re-export し、既存テスト
# (= test_preview_server_reject.py) の import path を保つ。
from routes.stages import (  # noqa: E402, F401
    _REJECT_NOTE_MAX_LENGTH,
    _archive_before_regen,
    _stage_artifact_paths,
)


# ───────────────── 台本書き戻し ─────────────────

# PUT /api/projects/<ts>/screenplay は routes/screenplay.py に移管済 (§3.1.2-a)。


# bg_cache 情報取得: 該当 scene の合成入力からキャッシュキーを派生し、
# キャッシュに同 key の画像が存在するかを返す (= UI のバッジ表示用)。
@app.route("/api/projects/<ts>/scenes/<int:scene_idx>/bg-cache-info",
           methods=["GET"])
def api_bg_cache_info(ts, scene_idx):
    _validate_ts(ts)
    ts_path = _ts_path(ts)
    if not os.path.isdir(ts_path):
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
    try:
        sp = staged_pipeline.load_project_screenplay(ts_path)
    except FileNotFoundError:
        return api_error("BG_CACHE_SNAPSHOT_NOT_FOUND", "snapshot not found", 404)
    scenes = sp.get("scenes") or []
    if scene_idx < 0 or scene_idx >= len(scenes):
        return api_error(
            "BG_CACHE_SCENE_OUT_OF_RANGE", "scene_idx out of range", 400,
        )
    import bg_cache
    try:
        key = bg_cache.compute_bg_cache_key(scenes[scene_idx], sp)
    except Exception as e:
        return api_error("BG_CACHE_KEY_FAILED", str(e), 500)
    cached = bg_cache.lookup(key)
    info: dict = {"cache_key": key, "cached": cached is not None}
    if cached is not None:
        try:
            with open(str(cached.with_suffix(".json")), encoding="utf-8") as f:
                meta = json.load(f)
            info["hit_count"] = int(meta.get("hit_count", 0))
            info["created_at"] = meta.get("created_at")
            info["last_used_at"] = meta.get("last_used_at")
        except (OSError, ValueError) as e:
            logger.warning(
                "[bg-cache-info] meta load 失敗 cache=%s: %s", cached, e,
            )
    return jsonify(info)


# PATCH /api/projects/<ts>/lines/<s>/<l> および /screenplay-meta は
# routes/screenplay.py に移管済 (§3.1.2-a)。


# characters / presets endpoint は routes/catalogs.py に移管済 (= §3.1.2)。


# ───────────────── ジョブステータス ─────────────────
# 共有 state / spawn ロジックは job_runner.py に移管済み。互換 shim を残す。
JobAlreadyRunningError = job_runner.JobAlreadyRunningError
_active_ts = job_runner._active_ts


def _spawn_job(fn, *, kind: str, ts: str, exclusive_ts: bool = True) -> str:
    return job_runner.spawn_job(fn, kind=kind, ts=ts, exclusive_ts=exclusive_ts)


def _job_already_running_response(e: JobAlreadyRunningError):
    return job_runner.job_already_running_response(e)


# /api/jobs/<job_id> は routes/jobs.py に移管済 (= §3.1.2)。


# ───────────────── アセット配信 ─────────────────
# /asset/<ts>/* (= TTS / BG / Kling / scene / overlay) と /asset/character/* /
# /asset/reference-video/* / /asset/location/* は routes/assets.py の
# Blueprint に移管済み。


# reference_videos endpoints は routes/reference_videos.py に移管済 (= §3.1.2)。


# locations CRUD は routes/locations.py に移管済 (= §3.1.2)。
# /asset/location/<loc_id>/preview は routes/assets.py に移管済み。


# character-metas CRUD は routes/character_metas.py に移管済 (= §3.1.2)。


# ───────────────── analyze ジョブ ─────────────────

_JOB_ID_RE = re.compile(r"^analyze_[\w]+$")
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


# GET /api/screenplay/analyze/<job_id> は routes/analyze.py に移管済 (§3.1.2-b)。


@app.route("/api/screenplay/analyze/<job_id>/events", methods=["GET"])
def api_analyze_job_events(job_id):
    """SSE で event をストリーミング配信する。"""
    if not _JOB_ID_RE.match(job_id):
        return api_error("ANALYZE_INVALID_JOB_ID", "invalid job_id", 400)
    try:
        snapshot = _job_to_dict(analyze_job.get_job(job_id))
    except KeyError:
        return api_error("ANALYZE_JOB_NOT_FOUND", "job not found", 404)

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


# POST /api/screenplay/analyze/<job_id>/confirm は routes/analyze.py に移管済
# (§3.1.2-b)。


# abstract GET/PUT は routes/screenplay.py に移管済 (= §3.1.2-a)。


# /api/projects/<ts>/scene-boundaries は routes/screenplay.py に移管済 (= §3.1.2-a)。


@app.route("/api/screenplay/analyze/<job_id>", methods=["DELETE"])
def api_cancel_analyze_job(job_id):
    """ジョブのキャンセルを要求 (各フェーズ境界で読まれて中断)。"""
    if not _JOB_ID_RE.match(job_id):
        return api_error("ANALYZE_INVALID_JOB_ID", "invalid job_id", 400)
    try:
        analyze_job.get_job(job_id)
    except KeyError:
        return api_error("ANALYZE_JOB_NOT_FOUND", "job not found", 404)
    analyze_runner.cancel(job_id)
    return jsonify({"ok": True}), 202


# /api/config は routes/config.py の Blueprint に移管済み。


# stage cache (= bg / kling) は routes/stage_cache.py に移管済 (= §3.1.2)。
# ───────────────── コスト記録 / 動的見積もり / レポート ─────────────────
# /api/cost/* は routes/cost.py の Blueprint に移管済み (= app.register_blueprint)。
# Blueprint 完全移行は routes/__init__.py の roadmap 参照。


# Stage 7 (final import) + Stage 8 (publish) は routes/final_publish.py の
# Blueprint に移管済み。


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


_PARTIAL_ARTIFACT_PATTERNS = (
    "tts_full.tmp.mp3",
    "tts_full.tmp.json",
    "*.tmp",
    "*.tmp.mp3",
    "*.tmp.mp4",
    "*.tmp.json",
    "*.tmp.png",
)


def _cleanup_partial_artifacts(ts: str) -> list[str]:
    """ts の temp ディレクトリから ``.tmp`` 系の中間ファイルを掃除する。

    process kill / crash で stage runner が中断したとき、scene_gen が
    atomic write 用に書きかけた `.tmp` ファイルが残ることがある。
    次の resume が同じ stage を再実行する前に破棄しておく。
    """
    if not ts:
        return []
    ts_path = _ts_path(ts)
    if not os.path.isdir(ts_path):
        return []
    import glob as _glob
    removed: list[str] = []
    for pattern in _PARTIAL_ARTIFACT_PATTERNS:
        for p in _glob.glob(os.path.join(ts_path, pattern)):
            try:
                os.remove(p)
                removed.append(os.path.relpath(p, ts_path))
            except OSError as e:
                logger.warning("[lost-cleanup] %s 削除失敗: %s", p, e)
    return removed


def _recover_lost_jobs() -> None:
    try:
        lost = job_store.recover_lost()
    except Exception as e:
        logger.warning("job_store.recover_lost 失敗: %s", e)
        return
    if not lost:
        return
    job_ids = [j.get("id") or "?" for j in lost]
    logger.warning(
        "[起動時] running のままだった job %d 件を lost に書換: %s",
        len(lost), ", ".join(job_ids),
    )
    seen_ts: set[str] = set()
    for rec in lost:
        ts = rec.get("ts")
        if not ts or ts in seen_ts:
            continue
        seen_ts.add(ts)
        try:
            removed = _cleanup_partial_artifacts(ts)
        except Exception as e:
            logger.warning("[起動時] cleanup(%s) 失敗: %s", ts, e)
            continue
        if removed:
            logger.warning(
                "[起動時] %s の partial artifact を削除: %s",
                ts, ", ".join(removed),
            )


_recover_lost_jobs()


if __name__ == "__main__":
    def _parse_port(value: str | None, default: int) -> int:
        try:
            return int(value or "")
        except (TypeError, ValueError):
            logger.warning(
                "[startup] port '%s' を int 変換できません (default=%d)",
                value, default,
            )
            return default

    port = _parse_port(os.environ.get("PREVIEW_PORT"), 5555)
    if len(sys.argv) > 1:
        port = _parse_port(sys.argv[1], port)
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    logger.info("プレビューサーバー起動中: http://%s:%d", host, port)
    app.run(host=host, port=port, debug=debug)
