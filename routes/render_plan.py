"""``GET /api/projects/<TS>/render-plan`` の Blueprint。

Phase 3-A: Composition Engine (Remotion) のフロント `<Player>` が読む render_plan
JSON を返す。``compositor_remotion.build_render_plan`` を呼ぶだけの薄いラッパで、
backend SSOT (= タイミング解決ロジック) はそのまま温存する。

詳細: docs/plannings/2026-05-10_compositional-architecture.md §3-5

Phase 3-B 以降で frontend の StageOverlay.tsx がこの endpoint を SWR で fetch して
``<Player component={ScreenplayBase} inputProps={{plan}}>`` に渡す。

scene_video_path は **frontend Vite dev server (= 5173) の origin に対する http URL**
として返す (= `/asset/<TS>/scene_<S>.mp4` 経由で preview_server が配信)。これにより
`<OffthreadVideo>` / `<Video>` 双方から `staticFile` 不要で再生できる。
"""
from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify, request

from routes._helpers import (
    load_screenplay_for_project,
    ts_path,
    validate_ts,
)

logger = logging.getLogger(__name__)

render_plan_bp = Blueprint("render_plan", __name__)


# 409 response の error_code (= frontend が string match ではなく code で
# 分岐するための SSOT)。新しい理由を追加したらここに定数を増やす。
ERR_SCENES_EMPTY = "scenes_empty"
ERR_SCENE_VIDEOS_NOT_READY = "scene_videos_not_ready"


def _scene_video_paths(ts: str, scene_count: int) -> tuple[list[str], list[int]]:
    """temp/<TS>/scene_<S>.mp4 を走査し、存在パスと欠落 index を返す。

    Stage 5 (= 音声+リップシンク合成) 完了前は scene_<S>.mp4 が無いため、
    409 を返す責務は呼び出し側 endpoint に委ねる。欠落 index を返すことで
    「Stage 5 部分失敗」 (= 一部 scene だけ合成済) と「Stage 5 未着手」を
    UI で区別できる。
    """

    base = ts_path(ts)
    paths: list[str] = []
    missing: list[int] = []
    for i in range(scene_count):
        candidate = os.path.join(base, f"scene_{i:03d}.mp4")
        if os.path.exists(candidate):
            paths.append(candidate)
        else:
            missing.append(i)
    return paths, missing


def _asset_url_for_scene_video(ts: str, scene_idx: int, abs_path: str) -> str:
    """preview_server の /asset 経由 URL を組み立てる。

    abs_path のファイル名 (= scene_<S>.mp4) を `/asset/<TS>/<basename>` で配信する。
    Vite dev server から見ると preview_server の origin (= 127.0.0.1:5555) を指す
    cross-origin だが、CORS は preview_server 側で許可済み。
    """

    basename = os.path.basename(abs_path)
    server_origin = request.host_url.rstrip("/")
    return f"{server_origin}/asset/{ts}/{basename}"


@render_plan_bp.route("/api/projects/<ts>/render-plan", methods=["GET"])
def get_render_plan(ts: str):
    """`compositor_remotion.build_render_plan` の結果を JSON で返す。

    Stage 5 が完了していない (= scene_<S>.mp4 がまだ無い) 場合は 409 で「まだ
    プレビュー不可」を返す。
    """

    validate_ts(ts)
    screenplay, _ = load_screenplay_for_project(ts)

    scenes = screenplay.get("scenes") or []
    if not scenes:
        return (
            jsonify(
                {
                    "error_code": ERR_SCENES_EMPTY,
                    "message": "scenes が空",
                }
            ),
            409,
        )

    scene_paths, missing = _scene_video_paths(ts, len(scenes))
    if missing:
        return (
            jsonify(
                {
                    "error_code": ERR_SCENE_VIDEOS_NOT_READY,
                    "message": (
                        "scene_<S>.mp4 が見つかりません。Stage 5 (scene 合成) "
                        "完了後にプレビュー可能です"
                    ),
                    "missing_scene_indices": missing,
                }
            ),
            409,
        )

    # build_render_plan は scene_video_path を受け取った scene_paths のまま詰める。
    # フロント `<Player>` で再生するには http URL が必要なので、後段で書き換える。
    from compositor_remotion import build_render_plan

    plan = build_render_plan(screenplay, scene_paths, public_relpath=None)

    # scene_video_path を /asset/<TS>/... の http URL に置換 (= フロント Player 用)。
    # `compose_video_remotion` (= サーバ render) では symlink + staticFile で
    # 別経路を使うため、本書き換えは preview にのみ作用する。
    for s_idx, scene in enumerate(plan["scenes"]):
        scene["scene_video_path"] = _asset_url_for_scene_video(
            ts, s_idx, scene_paths[s_idx]
        )

    return jsonify({"plan": plan})
