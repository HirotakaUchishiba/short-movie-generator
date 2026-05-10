"""routes/* で共有する純関数ヘルパ。preview_server からも import される。

Blueprint 分割の途中段階で `preview_server._validate_ts` 等が複数 module から
参照されるのを避けるため、シグネチャ stable な util をここに集約する。
"""
from __future__ import annotations

import os
import re
from typing import Any

from flask import abort, jsonify

import config


def api_error(
    code: str, message: str, status: int, **extra: Any
) -> tuple[Any, int]:
    """error response の SSOT helper。

    `frontend/src/api.ts` の ApiError は `body.error_code` で分岐するため、
    backend は **必ず error_code field を含めて** 返す。`message` は人間可読の
    詳細、`extra` は count や missing_indices 等の構造化フィールド。

    使い方:
        return api_error("ANALYZE_INVALID_SHA256", "video_sha256 (64 hex) required", 400)
        return api_error("ANALYZE_VIDEO_REFERENCED", "still referenced", 409, count=3)

    code は SCREAMING_SNAKE_CASE の prefix (= ANALYZE_ / RENDER_PLAN_ / ...)
    で領域を区別する。
    """

    body: dict[str, Any] = {"error_code": code, "message": message}
    body.update(extra)
    return jsonify(body), status


_TS_PATTERN = re.compile(r"^[\w\-]+$")


def validate_ts(ts: str) -> str:
    """TS 文字列が ``^[\\w\\-]+$`` に従うか検証し、そのまま返す。NG なら 400。"""
    if not _TS_PATTERN.match(ts):
        abort(400, "不正なタイムスタンプ")
    return ts


def ts_path(ts: str, *, temp_dir: str | None = None) -> str:
    """``temp/<ts>`` の絶対パスを返す。``temp_dir`` を渡すとそれを優先。"""
    base = temp_dir if temp_dir is not None else config.TEMP_DIR
    return os.path.join(base, ts)


def safe_join(base: str, *parts: str) -> str:
    """ディレクトリトラバーサル防止。base 配下を超える結果は abort 400。"""
    p = os.path.realpath(os.path.join(base, *parts))
    if (
        not p.startswith(os.path.realpath(base) + os.sep)
        and p != os.path.realpath(base)
    ):
        abort(400, "不正なパス")
    return p


# ─── abstract diff classifier (= Phase D-G16) ──────────────────
#
# PUT /api/projects/<ts>/abstract で、変更内容によって approval revoke の粒度を
# 切り替えるための判定。CLAUDE.md「コストのかかる操作を安易に実行しない」原則。
#
#   unchanged  → 内容同じ。save スキップ可
#   safe_only  → Stage 6 (= overlay) にしか影響しない field のみ変更。
#                 Stage 2-5 (TTS / 音声 / 動画) の approval は維持してよい
#   breaking   → TTS / 音声 / 動画に影響する変更が含まれる。全 revoke が必要

# screenplay (root) で変更されても safe な key (= Stage 6 のみ影響)
_ROOT_SAFE_KEYS = frozenset({
    "scene_parts",            # 互換: scene 内に置くのが正だが root 直下も許容
    "global_parts",
    "subtitle_y_from_bottom",
})

# scene 内で変更されても safe な key
_SCENE_SAFE_KEYS = frozenset({
    "scene_parts",
    "_override_background_prompt",
    "_override_animation_prompt",
    "identity",
    "annotation",
})


def _diff_keys(old: dict, new: dict) -> set[str]:
    """dict 同士の浅い差分 key 集合 (= 値が違う or 片方にしかない key)。"""
    keys: set[str] = set()
    for k in set(old.keys()) | set(new.keys()):
        if old.get(k) != new.get(k):
            keys.add(k)
    return keys


def classify_abstract_diff(old: dict, new: dict) -> str:
    """abstract (= screenplay snapshot) の diff を分類する。

    返り値:
      - "unchanged" : 完全一致
      - "safe_only" : Stage 6 にしか影響しない field のみ変更 (= Stage 2-5 保持可)
      - "breaking"  : TTS / 音声 / 動画に影響する変更を含む (= 全 revoke 必要)

    判定原則: 安全側 (= breaking) に倒す。`safe_only` は変更 key 集合が
    既知の safe set に **完全に含まれる** ときだけ。少しでも未知 key が
    混じれば breaking。
    """
    if old == new:
        return "unchanged"

    # root レベルの diff key
    root_diff = _diff_keys(old, new)
    if not root_diff.issubset(_ROOT_SAFE_KEYS | {"scenes"}):
        return "breaking"

    # scenes が変わっていなければ root だけで判定終了
    if "scenes" not in root_diff:
        return "safe_only"

    # scenes 配列の長さ変化は構造変更 = breaking
    old_scenes = old.get("scenes") or []
    new_scenes = new.get("scenes") or []
    if len(old_scenes) != len(new_scenes):
        return "breaking"

    # 各 scene を浅く比較
    for old_s, new_s in zip(old_scenes, new_scenes):
        if not isinstance(old_s, dict) or not isinstance(new_s, dict):
            return "breaking"
        scene_diff = _diff_keys(old_s, new_s)
        if not scene_diff.issubset(_SCENE_SAFE_KEYS):
            return "breaking"

    return "safe_only"


def load_screenplay_for_project(
    ts: str, *, temp_dir: str | None = None,
) -> tuple[dict, str]:
    """temp_dir/<TS>/screenplay.json (= immutable snapshot) を読み込む。

    台本は project 作成時に temp/<TS>/screenplay.json にコピーされ、
    以後そのファイルだけが正となる。template (= screenplays/<name>.json)
    が外部で書き換わっても進行中 project には影響しない。

    Returns: (screenplay dict, original template name)
    """
    import staged_pipeline

    project_path = ts_path(ts, temp_dir=temp_dir)
    meta = staged_pipeline.read_metadata(project_path)
    if not meta:
        abort(404, "プロジェクトのmetadataがありません")
    name = meta.get("screenplay_template_name") or meta.get("screenplay_name")
    if not name:
        abort(404, "metadataにscreenplay_template_name/nameがありません")
    try:
        sp = staged_pipeline.load_project_screenplay(project_path)
    except FileNotFoundError:
        abort(404, "プロジェクトの screenplay.json snapshot が見つかりません")
    return sp, name
