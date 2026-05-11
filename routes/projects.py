"""``/api/projects`` (= 一覧 + 作成 + 詳細) の Blueprint。

`preview_server.py` から段階移行 (= cost / analytics / config に続く 4 番目)。
title 整形 / list_screenplays 等の private helper も Blueprint 内へ。
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime

from flask import Blueprint, jsonify, request

import config
import io_utils
import progress_store
import staged_pipeline

from routes._helpers import (
    api_error,
    is_valid_ts,
    load_screenplay_for_project,
    save_reference_video,
    ts_path,
    validate_ts,
)

logger = logging.getLogger(__name__)

projects_bp = Blueprint("projects", __name__)

# project 作成時に optional で渡せる analyze ジョブ ID の format check
_JOB_ID_RE = re.compile(r"^analyze_[\w]+$")


def _list_screenplays() -> list[str]:
    if not os.path.isdir(config.SCREENPLAYS_DIR):
        return []
    return sorted(
        f for f in os.listdir(config.SCREENPLAYS_DIR) if f.endswith(".json")
    )


def _split_caption(caption: str) -> tuple[str, str]:
    """caption を「タイトル行」と「ハッシュタグ行」に分離する。

    タイトル = 先頭の非空・非ハッシュタグ行。caption が空・None の場合は
    両方空文字列を返す。プロジェクト一覧の friendly title 算出に使う。
    """
    if not caption:
        return "", ""
    title = ""
    hashtags: list[str] = []
    for raw in caption.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            hashtags.append(line)
        elif not title:
            title = line
    return title, " ".join(hashtags)


def _project_display_title(
    screenplay: dict | None, screenplay_name: str | None,
) -> str:
    """プロジェクト一覧用の friendly title。

    caption 1 行目 → 整形済み filename の順でフォールバック。
    """
    if screenplay:
        title, _ = _split_caption(str(screenplay.get("caption") or ""))
        if title:
            return title
    if screenplay_name:
        base = screenplay_name
        if base.endswith(".json"):
            base = base[:-5]
        if base.startswith("auto_") and len(base) > 13:
            base = "参考動画 " + base[5:13]
        return base
    return "(無題)"


@projects_bp.route("/api/projects", methods=["GET"])
def api_projects():
    items: list[dict] = []
    if not os.path.isdir(config.TEMP_DIR):
        return jsonify({
            "projects": items,
            "screenplays": _list_screenplays(),
        })

    for ts in sorted(os.listdir(config.TEMP_DIR), reverse=True):
        project_path = ts_path(ts)
        if not os.path.isdir(project_path):
            continue
        meta = staged_pipeline.read_metadata(project_path)
        if not meta:
            continue
        progress = progress_store.load(project_path)

        screenplay: dict | None = None
        try:
            screenplay = staged_pipeline.load_project_screenplay(project_path)
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(
                "project list: screenplay load failed for %s: %s", ts, e,
            )

        title = _project_display_title(screenplay, meta.get("screenplay_name"))
        _, hashtags = _split_caption(
            str((screenplay or {}).get("caption") or ""),
        )
        scene_count = len((screenplay or {}).get("scenes") or [])
        has_bg_thumbnail = os.path.exists(
            os.path.join(project_path, "bg_000.png"),
        )

        items.append({
            "timestamp": ts,
            "screenplay_name": meta.get("screenplay_name"),
            "display_title": title,
            "caption_hashtags": hashtags,
            "scene_count": scene_count,
            "has_bg_thumbnail": has_bg_thumbnail,
            "created_at": meta.get("created_at"),
            "current_stage": progress_store.current_stage(project_path),
            "progress": progress,
            # Stage 0 バッジ表示 (= ProjectCard の analyze 進行中 / 失敗)
            "analyze_status": progress_store.analyze_status(project_path),
            "analyze_job_id": meta.get("analyze_job_id"),
        })
    return jsonify({"projects": items, "screenplays": _list_screenplays()})


@projects_bp.route("/api/projects", methods=["POST"])
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

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_path = ts_path(ts)
    os.makedirs(project_path, exist_ok=True)

    try:
        staged_pipeline.run_script(
            screenplay, name, project_path, analyze_job_id=analyze_job_id,
        )
    except Exception as e:
        logger.exception("script stage failed")
        return jsonify({"error": str(e)}), 500

    return jsonify({"timestamp": ts, "current_stage": "script"}), 201


@projects_bp.route("/api/projects/from-reference-video", methods=["POST"])
def api_create_project_from_reference_video():
    """参考動画 + analyze ジョブを 1 トランザクションで起動する (= 主導フロー)。

    multipart/form-data:
      - reference_video: file (.mov / .mp4 / .webm / .mkv)
      - fps:             optional float (default analyze pipeline 既定)

    注: 旧「追加指示 (instructions)」multipart field は廃止 (= SYSTEM_PROMPT が
    プラットフォーム UI 無視をデフォルトで指示するため不要)。auto_loop の
    Phase 3 戦略注入は引き続き ``AnalyzeOptions.instructions`` を別経路で
    使用するが、UI / multipart からは受け取らない。

    Response (201): {"ts": "<TS>", "analyze_job_id": "analyze_..."}

    副作用:
      1. assets/reference_videos/<sha>.<ext> に dedup 保存
      2. analyze_jobs に project_ts=<TS> 付きで insert
      3. temp/<TS>/metadata.json を screenplay_name 不在で初期化
      4. progress_store.mark_analyze_started で Stage 0 = running
      5. analyze.runner.start で daemon thread 起動 (= save 完了で hook 発火)
    """
    from analyze import job as analyze_job
    from analyze import runner as analyze_runner

    f = request.files.get("reference_video")
    if not f:
        return jsonify({
            "error_code": "REFERENCE_VIDEO_REQUIRED",
            "message": "reference_video (multipart) is required",
        }), 400

    try:
        upload_result = save_reference_video(f)
    except ValueError as e:
        return jsonify({
            "error_code": "REFERENCE_VIDEO_UNSUPPORTED_EXT",
            "message": str(e),
            "allowed": list(analyze_job.ALLOWED_VIDEO_EXTS),
        }), 400

    options: dict = {}
    fps_raw = request.form.get("fps")
    if fps_raw:
        try:
            options["fps"] = float(fps_raw)
        except ValueError:
            return jsonify({
                "error_code": "ANALYZE_INVALID_FPS",
                "message": f"invalid fps: {fps_raw}",
            }), 400

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_path = ts_path(ts)
    os.makedirs(project_path, exist_ok=True)

    j = analyze_job.create_job(
        upload_result["sha256"], options, project_ts=ts,
    )
    staged_pipeline.init_pending_metadata(project_path, j.id)
    progress_store.mark_analyze_started(project_path)

    analyze_runner.start(j.id)

    return jsonify({"ts": ts, "analyze_job_id": j.id}), 201


@projects_bp.route("/api/projects/<ts>/retry-analyze", methods=["POST"])
def api_retry_analyze(ts):
    """Stage 0 (analyze) を再起動する。

    既存の analyze_job (= failed / cancelled) は **保持** (= 課金履歴のため)。
    新しい analyze_job を同じ video_sha256 + options + project_ts で作成し、
    metadata.analyze_job_id を新 ID に更新、progress.stages.analyze を
    running に戻して runner を起動。analyze cache (= content-addressed
    frames / audio / whisper) が効くので追加課金は最小。

    制約: 既存の analyze_status が "failed" の時のみ許可 (= "running"
    中の二重起動防止)。
    """
    from analyze import job as analyze_job
    from analyze import runner as analyze_runner

    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return jsonify({
            "error_code": "PROJECT_NOT_FOUND",
            "message": "プロジェクトが存在しません",
        }), 404

    meta = staged_pipeline.read_metadata(project_path) or {}
    old_job_id = meta.get("analyze_job_id")
    if not old_job_id:
        return jsonify({
            "error_code": "ANALYZE_JOB_ID_MISSING",
            "message": "このプロジェクトに analyze_job_id がありません (= legacy 経路)",
        }), 400

    status = progress_store.analyze_status(project_path)
    if status not in ("failed", None):
        return jsonify({
            "error_code": "ANALYZE_NOT_RETRYABLE",
            "message": f"current status={status}: failed のときのみ retry 可",
        }), 409

    try:
        old_job = analyze_job.get_job(old_job_id)
    except KeyError:
        return jsonify({
            "error_code": "ANALYZE_JOB_NOT_FOUND",
            "message": f"old job not found: {old_job_id}",
        }), 404

    new_job = analyze_job.create_job(
        old_job.video_sha256, old_job.options, project_ts=ts,
    )

    meta["analyze_job_id"] = new_job.id
    if "analyze_hook_error" in meta:
        del meta["analyze_hook_error"]
    io_utils.atomic_write_json(
        os.path.join(project_path, "metadata.json"), meta,
    )

    progress_store.mark_analyze_started(project_path)
    analyze_runner.start(new_job.id)

    return jsonify({"ok": True, "new_analyze_job_id": new_job.id}), 200


def _perform_project_delete(ts: str) -> dict:
    """1 project の削除を実施し、結果を dict で返す (= raise しない)。

    成功:
        ``{"ts": ts, "deleted": True}``
    失敗:
        ``{"ts": ts, "deleted": False, "error_code": "...", "message": "..."}``

    削除対象は ``temp/<TS>/`` ディレクトリのみ。reference_videos /
    screenplays/auto_*.json / analytics.db / cost_records.jsonl は **意図的に
    保持** (= SHA dedup 共有 / 課金 / 投稿履歴の保全)。in-flight analyze_job
    (= running / pending / dryrunning / awaiting_confirm) があれば cancel
    要求を立ててから ``shutil.rmtree`` する。

    本 helper は ``api_delete_project`` (= single) と ``api_bulk_delete_projects``
    (= 一括) の共通実装。bulk 側は raise されると partial success の集計が
    できないので、エラーも dict で返す。
    """
    import shutil

    from analyze import job as analyze_job
    from analyze import runner as analyze_runner

    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return {
            "ts": ts,
            "deleted": False,
            "error_code": "PROJECT_NOT_FOUND",
            "message": "プロジェクトが存在しません",
        }

    meta = staged_pipeline.read_metadata(project_path) or {}
    job_id = meta.get("analyze_job_id")
    if job_id:
        try:
            j = analyze_job.get_job(job_id)
            if j.status in (
                "running", "pending", "dryrunning", "awaiting_confirm",
            ):
                analyze_runner.cancel(job_id)
        except KeyError:
            pass

    try:
        shutil.rmtree(project_path)
    except OSError as e:
        logger.exception("project delete failed: %s", project_path)
        return {
            "ts": ts,
            "deleted": False,
            "error_code": "PROJECT_DELETE_FAILED",
            "message": f"directory delete failed: {e}",
        }

    return {"ts": ts, "deleted": True}


@projects_bp.route("/api/projects/<ts>", methods=["DELETE"])
def api_delete_project(ts):
    """project ディレクトリと in-flight analyze_job をキャンセルして削除する。

    本 endpoint は :func:`_perform_project_delete` の薄い HTTP wrapper。
    削除内容は同 helper の docstring を参照。
    """
    validate_ts(ts)
    result = _perform_project_delete(ts)
    if not result["deleted"]:
        status = 404 if result["error_code"] == "PROJECT_NOT_FOUND" else 500
        return jsonify({
            "error_code": result["error_code"],
            "message": result["message"],
        }), status
    return jsonify({"ts": ts, "deleted": True}), 200


_BULK_DELETE_MAX = 100


@projects_bp.route("/api/projects/bulk-delete", methods=["POST"])
def api_bulk_delete_projects():
    """複数 project を一括削除する。

    Body:
        ``{"ts_list": ["20260511_220521", "20260511_220522", ...]}``

    Response (200):
        ``{"deleted": ["..."], "failed": [{ts, error_code, message}, ...]}``

    入力検証:
        - ``ts_list`` 無し / 非 list → 400 BULK_DELETE_INVALID_LIST
        - 空 list → 400 BULK_DELETE_EMPTY_LIST
        - 長さ > 100 → 400 BULK_DELETE_TOO_MANY (= server timeout 防止)
        - 不正 ts format → 個別 ``failed`` に INVALID_TS で記録 (= 残りは続行)

    各 ts の削除は :func:`_perform_project_delete` を順次呼ぶ partial-success
    semantics。途中で 1 件失敗しても残りは続行する (= UI が `failed` 配列を
    見て個別に通知する想定)。
    """
    data = request.get_json(silent=True) or {}
    ts_list = data.get("ts_list")
    if not isinstance(ts_list, list):
        return api_error(
            "BULK_DELETE_INVALID_LIST",
            "ts_list (array) is required",
            400,
        )
    if len(ts_list) == 0:
        return api_error(
            "BULK_DELETE_EMPTY_LIST",
            "ts_list must contain at least 1 ts",
            400,
        )
    if len(ts_list) > _BULK_DELETE_MAX:
        return api_error(
            "BULK_DELETE_TOO_MANY",
            f"ts_list size must be <= {_BULK_DELETE_MAX}",
            400,
            limit=_BULK_DELETE_MAX,
            given=len(ts_list),
        )

    deleted: list[str] = []
    failed: list[dict] = []
    for ts in ts_list:
        if not is_valid_ts(ts):
            failed.append({
                "ts": str(ts),
                "error_code": "INVALID_TS",
                "message": "不正なタイムスタンプ",
            })
            continue
        result = _perform_project_delete(ts)
        if result["deleted"]:
            deleted.append(ts)
        else:
            failed.append({
                "ts": ts,
                "error_code": result["error_code"],
                "message": result["message"],
            })

    return jsonify({"deleted": deleted, "failed": failed}), 200


@projects_bp.route("/api/projects/<ts>", methods=["GET"])
def api_project_detail(ts):
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    meta = staged_pipeline.read_metadata(project_path) or {}
    progress = progress_store.load(project_path)
    analyze_status_val = progress_store.analyze_status(project_path)

    sp: dict | None = None
    name: str | None = None
    if meta.get("screenplay_name"):
        try:
            sp, name = load_screenplay_for_project(ts)
        except Exception as e:  # 404 abort も含めて defensive に拾う
            logger.warning("screenplay load failed for %s: %s", ts, e)

    return jsonify({
        "timestamp": ts,
        "screenplay_name": name,
        "screenplay": sp,
        "progress": progress,
        "current_stage": progress_store.current_stage(project_path),
        "analyze_job_id": meta.get("analyze_job_id"),
        "analyze_status": analyze_status_val,
    })
