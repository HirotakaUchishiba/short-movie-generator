"""``/api/projects/<ts>/{run-next,approve,reject,regen}`` の Blueprint。

`preview_server.py` から段階移行 (= cost / analytics / config / projects に
続く 5 番目)。job_runner と routes/_helpers を活用し、循環参照を避ける。
"""
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
from qa import artifact_paths as qa_artifact_paths
from qa import recorder as qa_recorder

from routes._helpers import (
    is_analyze_pending,
    load_screenplay_for_project,
    ts_path,
    validate_ts,
)


def _analyze_stage_not_ready_response():
    return jsonify({
        "error_code": "ANALYZE_STAGE_NOT_READY",
        "message": "Stage 0 (analyze) が完了するまで他のステージを実行できません",
    }), 403

logger = logging.getLogger(__name__)

stages_bp = Blueprint("stages", __name__)

# 自由記述 note の上限文字数。誤ペーストによる DB 肥大化 / 検索のばらつきを防ぐ。
# frontend (RejectModal.tsx) も同じ上限で警告を出す。
_REJECT_NOTE_MAX_LENGTH = 2000


def _stage_artifact_paths(project_path: str, stage: str,
                          scene_idx: int | None,
                          line_idx: int | None) -> list[str]:
    """qa.artifact_paths.stage_artifact_paths への薄いラッパ。"""
    return qa_artifact_paths.stage_artifact_paths(
        project_path, stage, scene_idx, line_idx)


def _archive_before_regen(ts: str, stage: str,
                          scene_idx: int | None,
                          line_idx: int | None) -> None:
    """regen 実行直前に前世代の artifact を ``regenerate_implicit`` で archive。

    artifact が無ければ何もしない (= 初回生成)。失敗は warn で握りつぶす
    (= 主目的の regen をブロックさせない)。"""
    project_path = ts_path(ts)
    artifact_p = _stage_artifact_paths(project_path, stage,
                                       scene_idx, line_idx)
    if not any(os.path.exists(p) for p in artifact_p):
        return
    snapshot_path = staged_pipeline.project_screenplay_path(project_path)
    snapshot_for_archive = (
        snapshot_path if os.path.exists(snapshot_path) else None
    )
    try:
        qa_recorder.record_failure(
            ts=ts, stage=stage, source="regenerate_implicit",
            tags=None, note=None,
            scene_idx=scene_idx, line_idx=line_idx,
            artifact_paths=artifact_p,
            screenplay_snapshot_path=snapshot_for_archive,
        )
    except Exception as e:
        logger.warning(
            "[qa archive] regen archive failed (ts=%s stage=%s): %s",
            ts, stage, e,
        )


@stages_bp.route("/api/projects/<ts>/approve", methods=["POST"])
def api_approve(ts):
    validate_ts(ts)
    data = request.get_json(force=True) or {}
    stage = data.get("stage")
    if stage not in progress_store.STAGES:
        return jsonify({"error": f"不正なstage: {stage}"}), 400
    try:
        progress_store.mark_approved(ts_path(ts), stage)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({
        "ok": True,
        "approved_stage": stage,
        "next_stage": progress_store.next_stage(ts_path(ts)),
    })


@stages_bp.route("/api/projects/<ts>/reject", methods=["POST"])
def api_reject(ts):
    """Phase 0: reject しても progress (generated_at / approved_at) は触らない。

    「不良サンプルとして記録だけ取る」割り切り。再生成したい場合は別途 /regen
    を叩く (= regenerate 経路で前世代も自動 archive される)。
    """
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    data = request.get_json(force=True) or {}
    stage = data.get("stage")
    if stage not in progress_store.STAGES:
        return jsonify({"error": f"不正なstage: {stage}"}), 400
    tags = data.get("tags") or []
    if not isinstance(tags, list):
        return jsonify({"error": "tags は list でなければなりません"}), 400
    note = data.get("note")
    if note is not None:
        if not isinstance(note, str):
            return jsonify({"error": "note は string または null"}), 400
        if len(note) > _REJECT_NOTE_MAX_LENGTH:
            return jsonify({
                "error": f"note は {_REJECT_NOTE_MAX_LENGTH} 文字以内 "
                         f"(actual={len(note)})",
            }), 400
    scene_idx = data.get("scene_idx")
    line_idx = data.get("line_idx")
    if scene_idx is not None and not isinstance(scene_idx, int):
        return jsonify({"error": "scene_idx は int または null"}), 400
    if line_idx is not None and not isinstance(line_idx, int):
        return jsonify({"error": "line_idx は int または null"}), 400

    artifact_p = _stage_artifact_paths(
        project_path, stage, scene_idx, line_idx,
    )
    snapshot_path = staged_pipeline.project_screenplay_path(project_path)
    snapshot_for_archive = (
        snapshot_path if os.path.exists(snapshot_path) else None
    )
    try:
        failure_id, archive_dir = qa_recorder.record_failure(
            ts=ts, stage=stage, source="human_reject",
            tags=tags, note=note,
            scene_idx=scene_idx, line_idx=line_idx,
            artifact_paths=artifact_p,
            screenplay_snapshot_path=snapshot_for_archive,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({
        "ok": True,
        "failure_id": failure_id,
        "archive_dir": archive_dir,
    })


@stages_bp.route("/api/projects/<ts>/run-next", methods=["POST"])
def api_run_next(ts):
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
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
        return jsonify({"error": f"このstageは再生成不可: {stage}"}), 400
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

    def _regen_with_archive():
        # 旧世代を qa_failures/ に regenerate_implicit で残してから上書きする。
        # データが揃えば validator のしきい値判定材料になる (= Phase 2 で再訓練)。
        _archive_before_regen(ts, stage, scene_idx, line_idx)
        return staged_pipeline.regen(
            stage, sp, project_path, scene_idx, line_idx, force=force,
            screenplay_name=name)

    try:
        job_id = spawn_job(_regen_with_archive,
                           kind=f"regen-{stage}", ts=ts)
    except JobAlreadyRunningError as e:
        return job_already_running_response(e)
    return jsonify({"job_id": job_id})
