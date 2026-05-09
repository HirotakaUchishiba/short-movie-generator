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
import progress_store
import staged_pipeline

from routes._helpers import (
    load_screenplay_for_project,
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


@projects_bp.route("/api/projects/<ts>", methods=["GET"])
def api_project_detail(ts):
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return jsonify({"error": "プロジェクトが存在しません"}), 404
    sp, name = load_screenplay_for_project(ts)
    progress = progress_store.load(project_path)
    meta = staged_pipeline.read_metadata(project_path) or {}
    return jsonify({
        "timestamp": ts,
        "screenplay_name": name,
        "screenplay": sp,
        "progress": progress,
        "current_stage": progress_store.current_stage(project_path),
        "analyze_job_id": meta.get("analyze_job_id"),
    })
