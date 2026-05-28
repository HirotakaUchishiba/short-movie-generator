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
from analyze import store as _analyze_store

log_setup.setup()
logger = logging.getLogger(__name__)

# 起動時に analyze ジョブ DB の schema を最新化する。
_analyze_store.ensure_schema()


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
from routes.clip_library import clip_library_bp  # noqa: E402
from routes.intent_suggestions import intent_suggestions_bp  # noqa: E402
from routes.intent_catalog import intent_catalog_bp  # noqa: E402
from routes.analyze import analyze_bp  # noqa: E402
from routes.catalogs import catalogs_bp  # noqa: E402
from routes.character_metas import character_metas_bp  # noqa: E402
from routes.jobs import jobs_bp  # noqa: E402
from routes.locations import locations_bp  # noqa: E402
from routes.project_queries import project_queries_bp  # noqa: E402
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
app.register_blueprint(assets_bp)
app.register_blueprint(screenplay_bp)
app.register_blueprint(analyze_bp)
app.register_blueprint(reference_videos_bp)
app.register_blueprint(locations_bp)
app.register_blueprint(character_metas_bp)
app.register_blueprint(catalogs_bp)
app.register_blueprint(jobs_bp)
app.register_blueprint(stage_cache_bp)
app.register_blueprint(project_queries_bp)


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
# (= routes/stages.py 等) からも安全に呼べる。
import job_runner  # noqa: E402

_jobs = job_runner._jobs
_jobs_lock = job_runner._jobs_lock
# screenplay disk write の serialize 用 (per-name) は staged_pipeline に移動。
# 同じ Lock を REST patch ハンドラと TTS regen 後の永続化が共有する。
_screenplay_lock = staged_pipeline.screenplay_lock

FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")


# /api/config/* は routes/config.py の Blueprint に移管済み。


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


# _validate_ts は preview_server 側で未使用のため削除済 (= §3.1.2)。
# 外部から必要な場合は routes._helpers.validate_ts を直接 import する。


def _ts_path(ts: str) -> str:
    """test 互換 shim: tests/test_preview_server_lost_cleanup.py が
    `preview_server._ts_path()` で TS path を組み立てるため残す。
    Blueprint 移管済の各 endpoint からは未使用。"""
    return _route_helpers.ts_path(ts, temp_dir=TEMP_DIR)


# _safe_join / _load_screenplay_for_project は preview_server 側で未使用のため
# 削除済 (= §3.1.2)。外部から必要な場合は routes._helpers から直接 import する。


def _ffprobe_duration(path: str) -> float:
    """互換 shim: tests/test_preview_server_analyze.py が
    `monkeypatch.setattr(preview_server, "_ffprobe_duration", ...)` で
    patch するため、shim を残す (= 全 endpoint が Blueprint 移管済の今は
    preview_server 内部からは呼ばれない)。"""
    return _route_helpers.ffprobe_duration(path)


# /api/projects (= 一覧 + 作成 + 詳細) は routes/projects.py の Blueprint に
# 移管済み。互換 shim で _list_screenplays / _split_caption /
# _project_display_title を re-export し、既存テストを温存。
from routes.projects import (  # noqa: E402, F401
    _list_screenplays,
    _project_display_title,
    _split_caption,
)


# tts-source / composed-prompts / progress は routes/project_queries.py に移管済 (= §3.1.2)。


# /api/projects/<ts>/{run-next,approve,reject,regen} は routes/stages.py の
# Blueprint に移管済み。
from routes.stages import _REJECT_NOTE_MAX_LENGTH  # noqa: E402, F401


# ───────────────── 台本書き戻し ─────────────────

# PUT /api/projects/<ts>/screenplay は routes/screenplay.py に移管済 (§3.1.2-a)。


# bg-cache-info は routes/project_queries.py に移管済 (= §3.1.2)。


# PATCH /api/projects/<ts>/lines/<s>/<l> および /screenplay-meta は
# routes/screenplay.py に移管済 (§3.1.2-a)。


# characters / presets endpoint は routes/catalogs.py に移管済 (= §3.1.2)。


# ───────────────── ジョブステータス ─────────────────
# 共有 state / spawn ロジックは job_runner.py に移管済み。互換 shim を残す。
JobAlreadyRunningError = job_runner.JobAlreadyRunningError
_active_ts = job_runner._active_ts


def _spawn_job(fn, *, kind: str, ts: str, exclusive_ts: bool = True) -> str:
    """test 互換 shim: tests/test_preview_server_concurrent_jobs.py が
    `preview_server._spawn_job()` で並行起動の整合性を検証するため残す。"""
    return job_runner.spawn_job(fn, kind=kind, ts=ts, exclusive_ts=exclusive_ts)


# _job_already_running_response は preview_server 側で未使用のため削除済
# (= §3.1.2)。外部から必要な場合は job_runner.job_already_running_response
# を直接 import する。


# /api/jobs/<job_id> は routes/jobs.py に移管済 (= §3.1.2)。


# ───────────────── アセット配信 ─────────────────
# /asset/<ts>/* (= TTS / BG / Kling / scene / overlay) と /asset/character/* /
# /asset/reference-video/* / /asset/location/* は routes/assets.py の
# Blueprint に移管済み。


# reference_videos endpoints は routes/reference_videos.py に移管済 (= §3.1.2)。


# locations CRUD は routes/locations.py に移管済 (= §3.1.2)。
# /asset/location/<loc_id>/preview は routes/assets.py に移管済み。


# character-metas CRUD は routes/character_metas.py に移管済 (= §3.1.2)。


# _JOB_ID_RE / _TS_RE / _job_to_dict は routes/analyze.py 移管後は preview_server
# 側では未使用のため削除済 (= §3.1.2-b)。


# GET /api/screenplay/analyze/<job_id> は routes/analyze.py に移管済 (§3.1.2-b)。


# GET /api/screenplay/analyze/<job_id>/events は routes/analyze.py に移管済 (= §3.1.2-b)。


# POST /api/screenplay/analyze/<job_id>/confirm は routes/analyze.py に移管済
# (§3.1.2-b)。


# abstract GET/PUT は routes/screenplay.py に移管済 (= §3.1.2-a)。


# /api/projects/<ts>/scene-boundaries は routes/screenplay.py に移管済 (= §3.1.2-a)。


# DELETE /api/screenplay/analyze/<job_id> は routes/analyze.py に移管済 (= §3.1.2-b)。


# /api/config は routes/config.py の Blueprint に移管済み。


# stage cache (= bg / kling) は routes/stage_cache.py に移管済 (= §3.1.2)。
# ───────────────── コスト記録 / 動的見積もり / レポート ─────────────────
# /api/cost/* は routes/cost.py の Blueprint に移管済み (= app.register_blueprint)。
# Blueprint 完全移行は routes/__init__.py の roadmap 参照。


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
