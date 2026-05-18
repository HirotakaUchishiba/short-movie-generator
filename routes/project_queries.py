"""project 単位の read-only query endpoint Blueprint。

preview_server.py から段階移行 (= §3.1.2)。以下 4 endpoint をまとめる:

- GET /api/projects/<ts>/tts-source
- GET /api/projects/<ts>/scenes/<int>/composed-prompts
- GET /api/projects/<ts>/progress
- GET /api/projects/<ts>/scenes/<int>/bg-cache-info

どれも書き込みを伴わない (= screenplay_lock 不要)。compose 派生や cache
判定結果を UI 透明性のために返す。
"""
from __future__ import annotations

import json
import logging
import os

from flask import Blueprint, jsonify

import progress_store
import scene_gen
import staged_pipeline

from routes._helpers import (
    api_error,
    load_screenplay_for_project,
    ts_path,
    validate_ts,
)

logger = logging.getLogger(__name__)

project_queries_bp = Blueprint("project_queries", __name__)


# ElevenLabs に実際に送信される原文を返す。
# scene_gen._build_screenplay_text を呼んで line を separator で連結した結果と、
# 各 line の char range (char_start, char_end) を返す。UI 透明性のため。
@project_queries_bp.route("/api/projects/<ts>/tts-source", methods=["GET"])
def api_tts_source(ts):
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
    sp, _ = load_screenplay_for_project(ts)
    full_text, line_specs = scene_gen._build_screenplay_text(sp)
    return jsonify({
        "text": full_text,
        "char_count": len(full_text),
        "separator": scene_gen.SCREENPLAY_TEXT_SEPARATOR,
        "line_specs": line_specs,
    })


# scene 単位の合成済みプロンプト (BG/Kling 用) を返す。
# scene_gen._build_background_prompt / _get_animation_prompt の出力をそのまま返す。
@project_queries_bp.route(
    "/api/projects/<ts>/scenes/<int:scene_idx>/composed-prompts",
    methods=["GET"])
def api_composed_prompts(ts, scene_idx):
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
    sp, _ = load_screenplay_for_project(ts)
    scenes = sp.get("scenes") or []
    if scene_idx >= len(scenes):
        return api_error(
            "SCENE_INDEX_OUT_OF_RANGE",
            f"scene_idx範囲外: {scene_idx}", 400,
            scene_idx=scene_idx, scene_count=len(scenes),
        )
    scene = scenes[scene_idx]
    bg_prompt = scene_gen._build_background_prompt(
        scene, sp, ts_path=project_path, s_idx=scene_idx)
    anim_prompt = scene_gen._get_animation_prompt(
        scene, ts_path=project_path, s_idx=scene_idx)
    return jsonify({
        "scene_idx": scene_idx,
        "background_prompt": bg_prompt,
        "animation_prompt": anim_prompt,
    })


@project_queries_bp.route("/api/projects/<ts>/progress", methods=["GET"])
def api_project_progress(ts):
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
    return jsonify({
        "progress": progress_store.load(project_path),
        "current_stage": progress_store.current_stage(project_path),
    })


# bg_cache 情報取得: 該当 scene の合成入力からキャッシュキーを派生し、
# キャッシュに同 key の画像が存在するかを返す (= UI のバッジ表示用)。
@project_queries_bp.route(
    "/api/projects/<ts>/scenes/<int:scene_idx>/bg-cache-info",
    methods=["GET"])
def api_bg_cache_info(ts, scene_idx):
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return api_error("PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404)
    try:
        sp = staged_pipeline.load_project_screenplay(project_path)
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
