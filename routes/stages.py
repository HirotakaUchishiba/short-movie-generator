"""``/api/projects/<ts>/{run-next,approve,reject,regen}`` の Blueprint。"""
from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify, request

import progress_store
import staged_pipeline
from job_runner import (
    JobAlreadyRunningError,
    job_already_running_response,
    spawn_job,
)

from routes._helpers import (
    api_error,
    is_analyze_pending,
    load_screenplay_for_project,
    ts_path,
    validate_ts,
)


def _analyze_stage_not_ready_response():
    return api_error(
        "ANALYZE_STAGE_NOT_READY",
        "Stage 0 (analyze) が完了するまで他のステージを実行できません",
        403,
    )


logger = logging.getLogger(__name__)

stages_bp = Blueprint("stages", __name__)

# 自由記述 note の上限文字数。誤ペーストによる肥大化を防ぐ。
# frontend (RejectModal.tsx) も同じ上限で警告を出す。
_REJECT_NOTE_MAX_LENGTH = 2000


@stages_bp.route("/api/projects/<ts>/approve", methods=["POST"])
def api_approve(ts):
    validate_ts(ts)
    data = request.get_json(force=True) or {}
    stage = data.get("stage")
    if stage not in progress_store.STAGES:
        return api_error("STAGE_INVALID", f"不正なstage: {stage}", 400, stage=stage)
    try:
        progress_store.mark_approved(ts_path(ts), stage)
    except ValueError as e:
        return api_error("STAGE_APPROVE_FAILED", str(e), 400)
    return jsonify({
        "ok": True,
        "approved_stage": stage,
        "next_stage": progress_store.next_stage(ts_path(ts)),
    })


@stages_bp.route("/api/projects/<ts>/reject", methods=["POST"])
def api_reject(ts):
    """reject は progress を変えない (= 単なる no-op + バリデーション)。"""
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
    data = request.get_json(force=True) or {}
    stage = data.get("stage")
    if stage not in progress_store.STAGES:
        return api_error("STAGE_INVALID", f"不正なstage: {stage}", 400, stage=stage)
    note = data.get("note")
    if note is not None:
        if not isinstance(note, str):
            return api_error("REJECT_NOTE_INVALID", "note は string または null", 400)
        if len(note) > _REJECT_NOTE_MAX_LENGTH:
            return api_error(
                "REJECT_NOTE_TOO_LONG",
                f"note は {_REJECT_NOTE_MAX_LENGTH} 文字以内 "
                f"(actual={len(note)})",
                400, max_length=_REJECT_NOTE_MAX_LENGTH, actual=len(note),
            )
    return jsonify({"ok": True})


@stages_bp.route("/api/projects/<ts>/run-next", methods=["POST"])
def api_run_next(ts):
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
    if is_analyze_pending(ts):
        return _analyze_stage_not_ready_response()
    sp, name = load_screenplay_for_project(ts)
    try:
        job_id = spawn_job(
            lambda: staged_pipeline.run_next_stage(sp, name, project_path),
            kind="run-next", ts=ts,
        )
    except JobAlreadyRunningError as e:
        return job_already_running_response(e)
    return jsonify({"job_id": job_id})


@stages_bp.route("/api/projects/<ts>/regen", methods=["POST"])
def api_regen(ts):
    validate_ts(ts)
    data = request.get_json(force=True) or {}
    stage = data.get("stage")
    scene_idx = data.get("scene_idx")
    line_idx = data.get("line_idx")
    force = bool(data.get("force", True))
    # bg ステージの「キャッシュ無視」再生成: 該当 scene に内部 hint を立てる
    force_no_cache = bool(data.get("force_no_cache", False))
    if stage not in {"tts", "bg", "kling", "scene", "overlay"}:
        return api_error("STAGE_NOT_REGENERABLE", f"このstageは再生成不可: {stage}", 400, stage=stage)
    if is_analyze_pending(ts):
        return _analyze_stage_not_ready_response()

    sp, name = load_screenplay_for_project(ts)
    if force_no_cache and stage == "bg":
        scenes = sp.get("scenes") or []
        if isinstance(scene_idx, int) and 0 <= scene_idx < len(scenes):
            scenes[scene_idx]["_bg_force_no_cache"] = True
        else:
            for s in scenes:
                s["_bg_force_no_cache"] = True

    project_path = ts_path(ts)

    def _regen():
        return staged_pipeline.regen(
            stage, sp, project_path, scene_idx, line_idx, force=force,
            screenplay_name=name)

    try:
        job_id = spawn_job(_regen, kind=f"regen-{stage}", ts=ts)
    except JobAlreadyRunningError as e:
        return job_already_running_response(e)
    return jsonify({"job_id": job_id})
