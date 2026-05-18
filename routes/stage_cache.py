"""``/api/projects/<ts>/stages/{bg,kling}/*`` + ``/api/{bg,kling}-cache/*``。

preview_server.py から段階移行 (= §3.1.2)。Stage 3 (BG) と Stage 4 (Kling)
の cache フローは scan / use-cache / queue-fresh / rescan / decisions-bulk /
generate-remaining / blacklist / delete / preview と完全に対称。stage 別の
差分は ``_STAGE_CACHE_HANDLERS`` に集約し、各エンドポイントは 1 行で stage
を渡すだけ。
"""
from __future__ import annotations

import logging
import os
import re

from flask import Blueprint, abort, jsonify, request, send_file

import bg_cache
import kling_cache
import progress_store
import scene_gen
from job_runner import (
    JobAlreadyRunningError,
    job_already_running_response,
    spawn_job,
)

from routes._helpers import (
    api_error,
    load_screenplay_for_project,
    ts_path,
    validate_ts,
)

logger = logging.getLogger(__name__)

stage_cache_bp = Blueprint("stage_cache", __name__)

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


# ─── helper (= 各 endpoint は dispatch のみ) ─────────────────


def _stage_scan_cache(ts: str, stage: str):
    handler = _resolve_handler(stage)
    if handler is None:
        return api_error("STAGE_UNKNOWN", f"unknown stage: {stage}", 400, stage=stage)
    if not os.path.isdir(ts_path(ts)):
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
    sp, _ = load_screenplay_for_project(ts)
    try:
        decisions = handler.scan_fn(sp, ts_path(ts))
    except Exception as e:
        logger.exception("%s scan failed", stage)
        return api_error("STAGE_CACHE_SCAN_FAILED", str(e), 500, stage=stage)
    progress_store.set_scan_result(ts_path(ts), stage, decisions)
    return jsonify({
        "scene_decisions": decisions,
        "cache_scanned_at": progress_store.get_decisions(
            ts_path(ts), stage)["cache_scanned_at"],
    })


def _stage_get_decisions(ts: str, stage: str):
    handler = _resolve_handler(stage)
    if handler is None:
        return api_error("STAGE_UNKNOWN", f"unknown stage: {stage}", 400, stage=stage)
    if not os.path.isdir(ts_path(ts)):
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
    return jsonify(progress_store.get_decisions(ts_path(ts), stage))


def _stage_use_cache(ts: str, stage: str, scene_idx: int):
    handler = _resolve_handler(stage)
    if handler is None:
        return api_error("STAGE_UNKNOWN", f"unknown stage: {stage}", 400, stage=stage)
    if not os.path.isdir(ts_path(ts)):
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
    data = request.get_json(force=True) or {}
    cache_key = data.get("key")
    if not cache_key:
        return api_error("CACHE_KEY_REQUIRED", "key required", 400)
    sp, _ = load_screenplay_for_project(ts)
    scenes = sp.get("scenes") or []
    if scene_idx < 0 or scene_idx >= len(scenes):
        return api_error("SCENE_INDEX_OUT_OF_RANGE", "scene_idx out of range", 400, scene_idx=scene_idx)
    try:
        handler.commit_fn(scene_idx, scenes[scene_idx], sp,
                          ts_path(ts), cache_key)
    except FileNotFoundError as e:
        return api_error("CACHE_ENTRY_NOT_FOUND", str(e), 404, key=cache_key)
    except Exception as e:
        logger.exception("%s use_cache failed", stage)
        return api_error("STAGE_CACHE_USE_FAILED", str(e), 500, stage=stage)
    progress_store.set_scene_decision(
        ts_path(ts), stage, scene_idx, "cache", cache_key)
    return jsonify({"ok": True, "decision": "cache", "key": cache_key})


def _stage_queue_fresh(ts: str, stage: str, scene_idx: int):
    handler = _resolve_handler(stage)
    if handler is None:
        return api_error("STAGE_UNKNOWN", f"unknown stage: {stage}", 400, stage=stage)
    if not os.path.isdir(ts_path(ts)):
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
    sp, _ = load_screenplay_for_project(ts)
    scenes = sp.get("scenes") or []
    if scene_idx < 0 or scene_idx >= len(scenes):
        return api_error("SCENE_INDEX_OUT_OF_RANGE", "scene_idx out of range", 400, scene_idx=scene_idx)
    progress_store.set_scene_decision(
        ts_path(ts), stage, scene_idx, "fresh", None)
    return jsonify({"ok": True, "decision": "fresh"})


def _stage_scene_rescan(ts: str, stage: str, scene_idx: int):
    handler = _resolve_handler(stage)
    if handler is None:
        return api_error("STAGE_UNKNOWN", f"unknown stage: {stage}", 400, stage=stage)
    if not os.path.isdir(ts_path(ts)):
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
    sp, _ = load_screenplay_for_project(ts)
    scenes = sp.get("scenes") or []
    if scene_idx < 0 or scene_idx >= len(scenes):
        return api_error("SCENE_INDEX_OUT_OF_RANGE", "scene_idx out of range", 400, scene_idx=scene_idx)
    try:
        decisions_all = handler.scan_fn(sp, ts_path(ts))
    except Exception as e:
        return api_error("STAGE_CACHE_SCAN_FAILED", str(e), 500, stage=stage)
    new_rec = decisions_all.get(str(scene_idx)) or {}
    cur = progress_store.get_decisions(ts_path(ts), stage)
    decisions = dict(cur.get("scene_decisions") or {})
    decisions[str(scene_idx)] = new_rec
    progress_store.set_scan_result(ts_path(ts), stage, decisions)
    return jsonify({"ok": True, "scene_decision": new_rec})


def _stage_decisions_bulk(ts: str, stage: str):
    handler = _resolve_handler(stage)
    if handler is None:
        return api_error("STAGE_UNKNOWN", f"unknown stage: {stage}", 400, stage=stage)
    if not os.path.isdir(ts_path(ts)):
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
    data = request.get_json(force=True) or {}
    action = data.get("action")
    if action not in ("all-cache", "all-fresh"):
        return api_error(
            "STAGE_DECISIONS_BULK_INVALID_ACTION",
            "action must be all-cache or all-fresh", 400, action=action,
        )
    sp, _ = load_screenplay_for_project(ts)
    scenes = sp.get("scenes") or []
    cur = progress_store.get_decisions(ts_path(ts), stage)
    decisions = dict(cur.get("scene_decisions") or {})
    summary = {"adopted": 0, "queued_fresh": 0, "errors": []}
    for i, scene in enumerate(scenes):
        rec = dict(decisions.get(str(i)) or {})
        if action == "all-cache":
            cands = rec.get("candidates") or []
            if cands:
                key = cands[0]["key"]
                try:
                    handler.commit_fn(i, scene, sp, ts_path(ts), key)
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
                handler.clear_downstream_fn(i, ts_path(ts))
            except Exception as e:
                logger.warning(
                    "[stage-decisions] downstream clear 失敗 ts=%s scene=%d: %s",
                    ts, i, e,
                )
            rec["decision"] = "fresh"
            rec["decided_key"] = None
            rec["decided_at"] = _now_iso()
            summary["queued_fresh"] += 1
        decisions[str(i)] = rec
    progress_store.set_scan_result(ts_path(ts), stage, decisions)
    return jsonify({"ok": True, "summary": summary,
                    "scene_decisions": decisions})


def _stage_generate_remaining(ts: str, stage: str):
    handler = _resolve_handler(stage)
    if handler is None:
        return api_error("STAGE_UNKNOWN", f"unknown stage: {stage}", 400, stage=stage)
    if not os.path.isdir(ts_path(ts)):
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
    sp, _ = load_screenplay_for_project(ts)
    n_scenes = len(sp.get("scenes") or [])
    cur = progress_store.get_decisions(ts_path(ts), stage)
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
        return api_error(
            "STAGE_DECISIONS_PENDING",
            "未判断のシーンがあります", 400,
            pending_scenes=pending,
        )

    try:
        job_id = spawn_job(
            lambda: _generate_fresh_and_mark(stage, sp, ts_path(ts), fresh_queue),
            kind=handler.generate_kind, ts=ts,
        )
    except JobAlreadyRunningError as e:
        return job_already_running_response(e)
    return jsonify({"job_id": job_id, "fresh_scenes": fresh_queue})


def _generate_fresh_and_mark(stage: str, sp: dict, td: str,
                             scene_indices: list[int]) -> None:
    """fresh queue を生成し、stage を generated とマークする。"""
    handler = _resolve_handler(stage)
    if handler is None:
        raise RuntimeError(f"unknown stage: {stage}")
    if scene_indices:
        handler.generate_fresh_fn(sp, td, scene_indices)
    progress_store.mark_generated(td, stage)


def _stage_cache_entries(stage: str):
    handler = _resolve_handler(stage)
    if handler is None:
        return api_error("STAGE_UNKNOWN", f"unknown stage: {stage}", 400, stage=stage)
    return jsonify({"entries": handler.cache_module.list_entries()})


def _stage_cache_blacklist(stage: str, key: str):
    handler = _resolve_handler(stage)
    if handler is None:
        return api_error("STAGE_UNKNOWN", f"unknown stage: {stage}", 400, stage=stage)
    if not _HASH16_RE.match(key):
        return api_error("CACHE_INVALID_KEY", "invalid key", 400, key=key)
    data = request.get_json(force=True) or {}
    reason = data.get("reason") or ""
    ok = handler.cache_module.blacklist(key, reason)
    if not ok:
        return api_error("CACHE_ENTRY_NOT_FOUND", "entry not found", 404, key=key)
    return jsonify({"ok": True})


def _stage_cache_delete(stage: str, key: str):
    handler = _resolve_handler(stage)
    if handler is None:
        return api_error("STAGE_UNKNOWN", f"unknown stage: {stage}", 400, stage=stage)
    if not _HASH16_RE.match(key):
        return api_error("CACHE_INVALID_KEY", "invalid key", 400, key=key)
    mp4_or_png, meta = handler.cache_module._entry_paths(key)
    is_deleted = False
    for p in (mp4_or_png, meta):
        if p.exists():
            try:
                os.remove(p)
                is_deleted = True
            except Exception as e:
                return api_error("CACHE_ENTRY_DELETE_FAILED", str(e), 500, key=key)
    if not is_deleted:
        return api_error("CACHE_ENTRY_NOT_FOUND", "entry not found", 404, key=key)
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


@stage_cache_bp.route("/api/projects/<ts>/stages/bg/scan-cache", methods=["POST"])
def api_bg_scan_cache(ts):
    """Stage 3a: 全シーンの cache を scan して判断状態を初期化する (同期)。"""
    validate_ts(ts)
    return _stage_scan_cache(ts, "bg")


@stage_cache_bp.route("/api/projects/<ts>/stages/bg/decisions", methods=["GET"])
def api_bg_decisions(ts):
    validate_ts(ts)
    return _stage_get_decisions(ts, "bg")


@stage_cache_bp.route(
    "/api/projects/<ts>/stages/bg/scenes/<int:scene_idx>/use-cache",
    methods=["POST"])
def api_bg_use_cache(ts, scene_idx):
    """Stage 3b: 1 scene の cache 採用 (= PNG copy + 下流クリア)。"""
    validate_ts(ts)
    return _stage_use_cache(ts, "bg", scene_idx)


@stage_cache_bp.route(
    "/api/projects/<ts>/stages/bg/scenes/<int:scene_idx>/queue-fresh",
    methods=["POST"])
def api_bg_queue_fresh(ts, scene_idx):
    validate_ts(ts)
    return _stage_queue_fresh(ts, "bg", scene_idx)


@stage_cache_bp.route(
    "/api/projects/<ts>/stages/bg/scenes/<int:scene_idx>/rescan",
    methods=["POST"])
def api_bg_scene_rescan(ts, scene_idx):
    validate_ts(ts)
    return _stage_scene_rescan(ts, "bg", scene_idx)


@stage_cache_bp.route("/api/projects/<ts>/stages/bg/decisions/bulk", methods=["POST"])
def api_bg_decisions_bulk(ts):
    validate_ts(ts)
    return _stage_decisions_bulk(ts, "bg")


@stage_cache_bp.route("/api/projects/<ts>/stages/bg/generate-remaining", methods=["POST"])
def api_bg_generate_remaining(ts):
    validate_ts(ts)
    return _stage_generate_remaining(ts, "bg")


@stage_cache_bp.route("/api/bg-cache/entries", methods=["GET"])
def api_bg_cache_entries():
    return _stage_cache_entries("bg")


@stage_cache_bp.route("/api/bg-cache/<key>/blacklist", methods=["POST"])
def api_bg_cache_blacklist(key):
    return _stage_cache_blacklist("bg", key)


@stage_cache_bp.route("/api/bg-cache/<key>", methods=["DELETE"])
def api_bg_cache_delete(key):
    return _stage_cache_delete("bg", key)


@stage_cache_bp.route("/api/bg-cache/<key>/preview.png", methods=["GET"])
def api_bg_cache_preview(key):
    return _stage_cache_preview("bg", key)


# ─── Kling (Stage 4) endpoints ─────────────────


@stage_cache_bp.route("/api/projects/<ts>/stages/kling/scan-cache", methods=["POST"])
def api_kling_scan_cache(ts):
    """Stage 4a: 全シーンの cache を scan して判断状態を初期化する (同期)。"""
    validate_ts(ts)
    return _stage_scan_cache(ts, "kling")


@stage_cache_bp.route("/api/projects/<ts>/stages/kling/decisions", methods=["GET"])
def api_kling_decisions(ts):
    validate_ts(ts)
    return _stage_get_decisions(ts, "kling")


@stage_cache_bp.route(
    "/api/projects/<ts>/stages/kling/scenes/<int:scene_idx>/use-cache",
    methods=["POST"])
def api_kling_use_cache(ts, scene_idx):
    """Stage 4b: 1 scene の cache 採用 (= raw mp4 copy + trim 同期実行)。"""
    validate_ts(ts)
    return _stage_use_cache(ts, "kling", scene_idx)


@stage_cache_bp.route(
    "/api/projects/<ts>/stages/kling/scenes/<int:scene_idx>/queue-fresh",
    methods=["POST"])
def api_kling_queue_fresh(ts, scene_idx):
    validate_ts(ts)
    return _stage_queue_fresh(ts, "kling", scene_idx)


@stage_cache_bp.route(
    "/api/projects/<ts>/stages/kling/scenes/<int:scene_idx>/rescan",
    methods=["POST"])
def api_kling_scene_rescan(ts, scene_idx):
    validate_ts(ts)
    return _stage_scene_rescan(ts, "kling", scene_idx)


@stage_cache_bp.route("/api/projects/<ts>/stages/kling/decisions/bulk", methods=["POST"])
def api_kling_decisions_bulk(ts):
    validate_ts(ts)
    return _stage_decisions_bulk(ts, "kling")


@stage_cache_bp.route("/api/projects/<ts>/stages/kling/generate-remaining",
                      methods=["POST"])
def api_kling_generate_remaining(ts):
    validate_ts(ts)
    return _stage_generate_remaining(ts, "kling")


@stage_cache_bp.route("/api/kling-cache/entries", methods=["GET"])
def api_kling_cache_entries():
    return _stage_cache_entries("kling")


@stage_cache_bp.route("/api/kling-cache/<key>/blacklist", methods=["POST"])
def api_kling_cache_blacklist(key):
    return _stage_cache_blacklist("kling", key)


@stage_cache_bp.route("/api/kling-cache/<key>", methods=["DELETE"])
def api_kling_cache_delete(key):
    return _stage_cache_delete("kling", key)


@stage_cache_bp.route("/api/kling-cache/<key>/preview.mp4", methods=["GET"])
def api_kling_cache_preview(key):
    return _stage_cache_preview("kling", key)
