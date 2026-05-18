"""routes/* で共有する純関数ヘルパ。

api_error / validate_ts / ts_path / safe_join / load_screenplay_for_project /
is_analyze_pending / ffprobe_duration / save_reference_video /
classify_abstract_diff を 17 個の Blueprint module から共有する。
preview_server.py 内に残る test 互換 shim (_ts_path / _spawn_job /
_ffprobe_duration) もここを経由する。
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


# TS 文字列の format check に使う共有 regex。
# - validate_ts() = HTTP request handler 内で abort(400) する経路
# - is_valid_ts() = bulk endpoint 等で raise せず bool で判定する経路
# 両者の regex を同一に保つため、必ずこの定数を経由する (= ad-hoc な
# re.compile を新規追加しない)。
_TS_PATTERN = re.compile(r"^[\w\-]+$")


def is_valid_ts(ts: str) -> bool:
    """TS 文字列が ``^[\\w\\-]+$`` に従うか bool で返す (= abort しない)。

    bulk-delete のように複数 ts を 1 リクエストで処理し、不正 ts を個別の
    failed エントリとして収集する経路で使う。
    """
    return isinstance(ts, str) and bool(_TS_PATTERN.match(ts))


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
    "subtitle_y_from_bottom",
})

# scene 内で変更されても safe な key
_SCENE_SAFE_KEYS = frozenset({
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


def is_analyze_pending(ts: str, *, temp_dir: str | None = None) -> bool:
    """analyze 経路 project が Stage 0 (analyze) を未完了かどうか。

    True を返す条件 (= 全て満たす):
      - `analyze_job_id` が metadata にある (= analyze 経路で作られた project)
      - `screenplay_name` が metadata に無い (= snapshot がまだコピーされていない)
      - `analyze_status` が "running" / "pending" / "failed" / None のいずれか
        (= "completed" 以外。failed は retry endpoint 経路で別途扱う)

    legacy template 経路 (= screenplay_name あり) は常に False。analyze_job_id
    が無い project (= 壊れた / 古い project) も False (= 個別 endpoint の
    load_screenplay_for_project で 404 を返させる)。

    Stage 1+ stage runner / abstract endpoint で 403 ANALYZE_STAGE_NOT_READY
    を返す前のチェックに使う。
    """
    import progress_store
    import staged_pipeline
    project_path = ts_path(ts, temp_dir=temp_dir)
    meta = staged_pipeline.read_metadata(project_path) or {}
    if meta.get("screenplay_name"):
        return False
    if not meta.get("analyze_job_id"):
        return False
    status = progress_store.analyze_status(project_path)
    return status != "completed"


def ffprobe_duration(path: str) -> float:
    """ffprobe で動画の duration を秒で返す。失敗時 0.0。

    旧 preview_server._ffprobe_duration を移管 (= POST /api/reference_videos と
    新 POST /api/projects/from-reference-video が共通利用)。
    """
    import json
    import subprocess
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", path],
            capture_output=True, text=True,
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def save_reference_video(file_storage) -> dict:
    """multipart reference video を dedup + sha256 ベースで保存し、metadata を返す。

    POST /api/reference_videos と POST /api/projects/from-reference-video の
    共通経路。dedup hit なら touch_reference_video まで内部で完結、新規なら
    ffprobe_duration で計測して upsert_reference_video まで行う。

    Returns: dict = {
        sha256, size_bytes, duration_sec, original_name, deduplicated: bool
    }
    Raises:
        ValueError: 拡張子が ALLOWED_VIDEO_EXTS に無い (= caller は 400 で reject)
    """
    import os
    import uuid

    from analyze import job as analyze_job
    from analyze.cache import file_sha256

    name = file_storage.filename or "video"
    ext = os.path.splitext(name)[1].lower()
    if ext not in analyze_job.ALLOWED_VIDEO_EXTS:
        raise ValueError(
            f"unsupported extension: {ext}; "
            f"allowed: {list(analyze_job.ALLOWED_VIDEO_EXTS)}",
        )

    ref_dir = analyze_job.reference_videos_dir()
    tmp = ref_dir / f".tmp_{uuid.uuid4().hex}{ext}"
    try:
        file_storage.save(str(tmp))
        sha = file_sha256(str(tmp))
        size = os.path.getsize(tmp)
        original = os.path.basename(name)

        existing = analyze_job.get_reference_video(sha)
        if existing:
            tmp.unlink(missing_ok=True)
            analyze_job.touch_reference_video(sha)
            return {
                "sha256": sha,
                "size_bytes": existing["size_bytes"],
                "duration_sec": existing["duration_sec"],
                "original_name": existing["original_name"],
                "deduplicated": True,
            }

        final_path = ref_dir / f"{sha}{ext}"
        tmp.replace(final_path)
        duration = ffprobe_duration(str(final_path))
        analyze_job.upsert_reference_video(
            sha, original_name=original,
            size_bytes=size, duration_sec=duration,
        )
        return {
            "sha256": sha,
            "size_bytes": size,
            "duration_sec": duration,
            "original_name": original,
            "deduplicated": False,
        }
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
