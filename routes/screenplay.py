"""routes/screenplay.py — screenplay snapshot 編集 endpoint。

preview_server.py から段階移行 (= 計画書 §3.1.2-a):

- PUT /api/projects/<ts>/screenplay        : 全 screenplay 上書き保存
- PATCH /api/projects/<ts>/lines/<s>/<l>   : line 単位 patch
- PATCH /api/projects/<ts>/screenplay-meta : screenplay-level meta patch

すべて screenplay_lock 経由で並行 patch を安全に処理する。snapshot は
abstract 形式のまま読み書きする (= live derivation を維持)。
"""

from __future__ import annotations

import logging
import os
from copy import deepcopy

from flask import Blueprint, jsonify, request

import progress_store
import staged_pipeline
from project_state import screenplay_lock
from routes._helpers import (
    api_error,
    classify_abstract_diff,
    is_analyze_pending,
    ts_path,
    validate_ts,
)

logger = logging.getLogger(__name__)

screenplay_bp = Blueprint("screenplay", __name__)


@screenplay_bp.route("/api/projects/<ts>/screenplay", methods=["PUT"])
def api_save_screenplay(ts):
    """全 screenplay を上書き保存し、変更内容に応じて Stage 2-6 承認を解除する。

    2026-05-17 schema 撤廃: line.speaker 変更も含む全 line/scene 編集は
    `classify_abstract_diff` で分類され、breaking (= TTS / 動画に影響) なら
    Stage 2 以降の承認が自動 reset される (= 古い voice の audio が次工程に
    流れるのを防ぐ。段階的ゲート方式 §15)。
    """
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return api_error(
            "SCREENPLAY_PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404,
        )
    data = request.get_json(force=True) or {}
    sp = data.get("screenplay")
    if not isinstance(sp, dict):
        return api_error(
            "SCREENPLAY_PAYLOAD_INVALID", "screenplayが必要です", 400,
        )
    try:
        from screenplay_validator import validate_screenplay

        errors = validate_screenplay(sp, strict=False)
        if errors:
            return jsonify(
                {"error_code": "SCREENPLAY_VALIDATION_FAILED",
                 "message": "validator失敗", "details": errors},
            ), 400
        with screenplay_lock(ts):
            try:
                old_sp = staged_pipeline.load_project_abstract(project_path)
            except FileNotFoundError:
                old_sp = {}
            # Stage 6 等は compose 済み screenplay を PUT してくる。snapshot は
            # abstract が SSOT なので、diff 判定・保存の前に abstract へ正規化する
            # (= 派生フィールド除去 + identity→root)。これをしないと compose 済み
            # vs abstract の差を breaking 誤判定し、全承認が飛ぶ + 背景未設定化する。
            sp = staged_pipeline._strip_composed_fields(sp)
            classification = classify_abstract_diff(old_sp, sp)
            if classification == "unchanged":
                return jsonify({"ok": True, "classification": "unchanged"})
            staged_pipeline.save_project_screenplay(project_path, sp)
            if classification == "breaking":
                progress_store.revoke_all_approvals(project_path)
            elif classification == "safe_only":
                progress_store.revoke_overlay_only(project_path)
    except Exception as e:
        return api_error("SCREENPLAY_SAVE_FAILED", str(e), 500)
    return jsonify({"ok": True, "classification": classification})


@screenplay_bp.route(
    "/api/projects/<ts>/lines/<int:scene_idx>/<int:line_idx>",
    methods=["PATCH"],
)
def api_patch_line(ts, scene_idx, line_idx):
    """abstract snapshot の line に部分 patch を適用する。

    snapshot は abstract 形式のまま読み書きする (= live derivation を維持)。
    派生フィールド (voice_overrides の base 値・background_prompt 等) は
    Stage 2 以降が compose を介して読むので、ここでは触らない。
    """
    validate_ts(ts)
    data = request.get_json(force=True) or {}
    patch = data.get("patch")
    if not isinstance(patch, dict):
        return api_error(
            "SCREENPLAY_PATCH_INVALID", "patch (object) が必要です", 400,
        )
    # abstract line schema に揃えた allowlist。start/end は **TTS が SSOT** で
    # ユーザー編集対象外 (analyze の Whisper 値 → Stage 2 で実音声長に上書き)
    # なので除外する。subtitles/hidden は字幕分割・抑止フラグとして残す。
    # voice_overrides は line 個別 override が compose で base に上書き優先される
    allowed = {
        "text", "tts_text", "emotion",
        "emotion_intensity", "delivery", "audio_tags", "speaker",
        "pronunciation_hints", "acoustic",
        "subtitles", "hidden",
    }
    unknown = set(patch.keys()) - allowed
    if unknown:
        return api_error(
            "SCREENPLAY_PATCH_UNKNOWN_FIELDS",
            f"許可されていないフィールド: {sorted(unknown)}", 400,
        )

    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return api_error(
            "SCREENPLAY_PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404,
        )
    try:
        from screenplay_validator import validate_abstract

        with screenplay_lock(ts):
            sp = staged_pipeline.load_project_abstract(project_path)
            scenes = sp.get("scenes") or []
            if scene_idx >= len(scenes):
                return api_error(
                    "SCREENPLAY_PATCH_SCENE_OUT_OF_RANGE",
                    f"scene_idx範囲外: {scene_idx}", 400,
                )
            lines = scenes[scene_idx].get("lines") or []
            if line_idx >= len(lines):
                return api_error(
                    "SCREENPLAY_PATCH_LINE_OUT_OF_RANGE",
                    f"line_idx範囲外: {line_idx}", 400,
                )
            old_sp = deepcopy(sp)
            line = lines[line_idx]
            for k, v in patch.items():
                if v is None:
                    line.pop(k, None)
                else:
                    line[k] = v
            errors = validate_abstract(sp, strict=False)
            if errors:
                return jsonify(
                    {"error_code": "SCREENPLAY_VALIDATION_FAILED",
                     "message": "validator失敗", "details": errors},
                ), 400
            classification = classify_abstract_diff(old_sp, sp)
            if classification == "unchanged":
                return jsonify({"ok": True, "classification": "unchanged"})
            staged_pipeline.save_project_screenplay(project_path, sp)
            # line.speaker / text / emotion 等の patch は breaking 扱いになり、
            # Stage 2 以降の承認が自動 reset される (= 古い voice / 動画 / 字幕
            # が次工程に流れるのを防ぐ。2026-05-17 schema 撤廃)
            if classification == "breaking":
                progress_store.revoke_all_approvals(project_path)
            elif classification == "safe_only":
                progress_store.revoke_overlay_only(project_path)
    except Exception as e:
        return api_error("SCREENPLAY_PATCH_FAILED", str(e), 500)
    return jsonify({"ok": True, "classification": classification})


@screenplay_bp.route(
    "/api/projects/<ts>/screenplay-meta", methods=["PATCH"],
)
def api_patch_screenplay_meta(ts):
    """screenplay-level meta (= subtitle_y_from_bottom 等) の部分 patch。"""
    validate_ts(ts)
    data = request.get_json(force=True) or {}
    patch = data.get("patch")
    if not isinstance(patch, dict):
        return api_error(
            "SCREENPLAY_META_PATCH_INVALID", "patch (object) が必要です", 400,
        )
    allowed = {"subtitle_y_from_bottom"}
    unknown = set(patch.keys()) - allowed
    if unknown:
        return api_error(
            "SCREENPLAY_META_UNKNOWN_FIELDS",
            f"許可されていないフィールド: {sorted(unknown)}", 400,
        )

    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return api_error(
            "SCREENPLAY_PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404,
        )
    try:
        from screenplay_validator import validate_abstract

        with screenplay_lock(ts):
            sp = staged_pipeline.load_project_abstract(project_path)
            for k, v in patch.items():
                if v is None:
                    sp.pop(k, None)
                else:
                    sp[k] = v
            errors = validate_abstract(sp, strict=False)
            if errors:
                return jsonify(
                    {"error_code": "SCREENPLAY_VALIDATION_FAILED",
                     "message": "validator失敗", "details": errors},
                ), 400
            staged_pipeline.save_project_screenplay(project_path, sp)
    except Exception as e:
        return api_error("SCREENPLAY_META_PATCH_FAILED", str(e), 500)
    return jsonify({"ok": True})


@screenplay_bp.route("/api/projects/<ts>/abstract", methods=["GET"])
def api_get_project_abstract(ts):
    """project の現在 snapshot を生のまま返す (= 抽象台本、UI 編集対象)。

    completeness の判定は frontend が abstract から live 計算するので、
    diagnostics はレスポンスに含めない (``analyze.compose.diagnose_abstract``
    は関数として残しているため、CLI / 別ツールから引き続き利用可能)。
    """
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return api_error(
            "ANALYZE_PROJECT_NOT_FOUND",
            "プロジェクトが存在しません",
            404,
        )
    if is_analyze_pending(ts):
        return api_error(
            "ANALYZE_STAGE_NOT_READY",
            "Stage 0 (analyze) が完了するまで abstract を読めません",
            403,
        )
    try:
        sp = staged_pipeline.load_project_abstract(project_path)
    except FileNotFoundError:
        return api_error(
            "ANALYZE_SNAPSHOT_NOT_FOUND",
            "screenplay snapshot not found",
            404,
        )
    return jsonify({
        "screenplay_path": staged_pipeline.project_screenplay_path(project_path),
        "abstract": sp,
    })


@screenplay_bp.route("/api/projects/<ts>/abstract", methods=["PUT"])
def api_put_project_abstract(ts):
    """project snapshot (= 抽象台本) を上書き保存し、変更内容に応じて承認を解除する。

    snapshot は抽象台本のまま保存される。Stage 2 以降が読むときに compose を
    都度走らせて派生フィールドを生成する
    (= ``staged_pipeline.load_project_screenplay``)。

    Phase D-G16: 変更を ``classify_abstract_diff`` で分類し:
      - unchanged → save スキップ、approval も触らず 200 を返す
      - safe_only (= subtitle_y_from_bottom 等 overlay にしか影響しない field)
                 → Stage 6 (overlay) 承認だけ revoke、Stage 2-5 は維持
      - breaking → 従来通り全 revoke
    CLAUDE.md「コストのかかる操作を安易に実行しない」原則に従い、再 TTS / 再
    動画生成を不要な場面で促さない。
    """
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return api_error(
            "ANALYZE_PROJECT_NOT_FOUND",
            "プロジェクトが存在しません",
            404,
        )
    if is_analyze_pending(ts):
        return api_error(
            "ANALYZE_STAGE_NOT_READY",
            "Stage 0 (analyze) が完了するまで abstract を更新できません",
            403,
        )
    data = request.get_json(force=True) or {}
    abstract = data.get("abstract")
    if not isinstance(abstract, dict):
        return api_error(
            "ANALYZE_ABSTRACT_REQUIRED",
            "abstract (object) is required",
            400,
        )
    scenes = abstract.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return api_error(
            "ANALYZE_ABSTRACT_SCENES_EMPTY",
            "abstract.scenes must be non-empty array",
            400,
        )
    from screenplay_validator import (
        normalize_abstract_annotations,
        validate_abstract,
    )
    normalize_abstract_annotations(abstract)
    errors = validate_abstract(abstract, strict=False)
    if errors:
        return api_error(
            "ANALYZE_ABSTRACT_VALIDATION_FAILED",
            "abstract のスキーマ検証に失敗しました",
            400,
            errors=errors,
        )
    try:
        old_abstract = staged_pipeline.load_project_abstract(project_path)
    except FileNotFoundError:
        old_abstract = {}
    classification = classify_abstract_diff(old_abstract, abstract)
    revoked_approvals = False
    with screenplay_lock(ts):
        if classification == "unchanged":
            pass
        else:
            staged_pipeline.save_project_screenplay(project_path, abstract)
            if classification == "breaking":
                progress_store.revoke_all_approvals(project_path)
                revoked_approvals = True
            elif classification == "safe_only":
                progress_store.revoke_overlay_only(project_path)
                revoked_approvals = True
    return jsonify({
        "screenplay_path": staged_pipeline.project_screenplay_path(project_path),
        "scenes": len(scenes),
        "revoked_approvals": revoked_approvals,
        "classification": classification,
    })


@screenplay_bp.route("/api/projects/<ts>/scene-boundaries", methods=["POST"])
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
    validate_ts(ts)
    project_path = ts_path(ts)
    if not os.path.isdir(project_path):
        return api_error(
            "PROJECT_NOT_FOUND", "プロジェクトが存在しません", 404,
        )
    data = request.get_json(force=True) or {}
    raw = data.get("line_boundaries")
    if not isinstance(raw, list) or not all(isinstance(x, int) for x in raw):
        return api_error(
            "SCENE_BOUNDARIES_INVALID",
            "line_boundaries は int の list である必要があります", 400,
        )
    try:
        with screenplay_lock(ts):
            result = staged_pipeline.apply_scene_boundaries(project_path, raw)
    except FileNotFoundError as e:
        return api_error("SCENE_BOUNDARIES_NOT_FOUND", str(e), 404)
    except ValueError as e:
        return api_error("SCENE_BOUNDARIES_INVALID", str(e), 400)
    except Exception as e:
        logger.exception("apply_scene_boundaries failed")
        return api_error("SCENE_BOUNDARIES_FAILED", str(e), 500)
    return jsonify({
        "ok": True,
        "scenes": result["scenes"],
        "lines": result["lines"],
        "subtitles_reset_lines": result.get("subtitles_reset_lines", 0),
    })
