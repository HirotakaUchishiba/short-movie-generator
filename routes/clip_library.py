"""``/api/clips/*`` の Blueprint。

clip_library (= Phase 1) の entry を UI から閲覧 / 承認 / blacklist 化する
ための API。Stage 3/4 の hit バッジ表示と IntentCatalog 画面の両方が
本 endpoint を利用する。

設計 doc: docs/plannings/2026-05-10_compositional-architecture.md §3
"""
from __future__ import annotations

import json
import logging
from typing import Any

from flask import Blueprint, abort, jsonify, request

import clip_library
import config

logger = logging.getLogger(__name__)

clip_library_bp = Blueprint("clip_library", __name__)


def _entry_to_dict(entry: clip_library.ClipEntry) -> dict[str, Any]:
    """`ClipEntry` を JSON-serializable な dict に変換 (= UI 表示用)。"""

    return {
        "id": entry.id,
        "identity": entry.identity.to_dict(),
        "annotation": entry.annotation.to_dict(),
        "provenance": entry.provenance.to_dict(),
        "lifecycle": entry.lifecycle.to_dict(),
    }


@clip_library_bp.route("/api/clips", methods=["GET"])
def list_clips():
    """全 entry を一覧する (= active / pending_review / blacklisted 含む)。

    Response:
      {
        "enabled": <bool, CLIP_LIBRARY_ENABLED>,
        "entries": [_entry_to_dict(e), ...]
      }

    クエリパラメータ:
      - status: "active" / "pending_review" / "blacklisted" / "all" (default "all")
    """

    status_filter = request.args.get("status", "all")
    out: list[dict[str, Any]] = []
    for entry in clip_library.iter_all_entries():
        if status_filter != "all" and entry.lifecycle.status != status_filter:
            continue
        out.append(_entry_to_dict(entry))
    return jsonify({
        "enabled": bool(getattr(config, "CLIP_LIBRARY_ENABLED", False)),
        "entries": out,
    })


@clip_library_bp.route("/api/clips/<entry_id>", methods=["GET"])
def get_clip(entry_id: str):
    """1 entry の詳細を返す。"""

    entry = clip_library.load_entry(entry_id)
    if entry is None:
        abort(404, f"clip entry not found: {entry_id}")
    return jsonify({"entry": _entry_to_dict(entry)})


@clip_library_bp.route("/api/clips/<entry_id>/approve", methods=["POST"])
def approve_clip(entry_id: str):
    """`pending_review` を `active` に昇格させる。"""

    if not clip_library.approve_entry(entry_id):
        abort(404, f"clip entry not found: {entry_id}")
    entry = clip_library.load_entry(entry_id)
    return jsonify({"ok": True, "entry": _entry_to_dict(entry) if entry else None})


@clip_library_bp.route("/api/clips/<entry_id>/blacklist", methods=["POST"])
def blacklist_clip(entry_id: str):
    """entry を blacklist 化 (= 以後 lookup で除外)。

    Body: {"reason": str}
    """

    body = request.get_json(silent=True) or {}
    reason = str(body.get("reason") or "(no reason given)")
    if not clip_library.blacklist_entry(entry_id, reason):
        abort(404, f"clip entry not found: {entry_id}")
    entry = clip_library.load_entry(entry_id)
    return jsonify({"ok": True, "entry": _entry_to_dict(entry) if entry else None})


@clip_library_bp.route(
    "/api/projects/<ts>/clip-library-status", methods=["GET"]
)
def project_clip_status(ts: str):
    """指定 project (= TS) の screenplay snapshot を読んで、
    各 scene が clip_library hit しているか判定する。

    Response:
      {
        "enabled": <bool>,
        "scenes": [
          {"scene_idx": 0, "has_identity": true, "satisfied": true,
           "entry_id": "01H8..."},
          {"scene_idx": 1, "has_identity": false, "satisfied": false},
          ...
        ]
      }

    判定:
      - has_identity: scene が identity 情報 (= character_refs / location_ref /
        start_emotion) を持っているか
      - satisfied: identity scene について、現在 lookup_clip_pool が hit するか
        (= 実 hit を行うとファイルコピーが副作用で発生するので、ここでは
        「pool が空でないか」 + 「1 件以上 active entry があるか」だけを判定)
      - entry_id: hit する場合の最有力 entry (= top-1)
    """

    from routes._helpers import load_screenplay_for_project, validate_ts

    validate_ts(ts)
    # PR #157 (Phase A) で compose_screenplay() が identity / annotation /
    # scene_parts を pass-through するようになったため、snapshot 直読み
    # workaround を撤去し、他の route と同じ load_screenplay_for_project
    # (= compose 経由) に統一する。
    #
    # 副次効果: snapshot に identity が手書きで書かれていない場合でも、
    # compose の `_derive_identity()` が featured_characters + location_ref +
    # lines[0].emotion + camera_distance から identity を派生するので、Stage 1
    # UI で abstract を編集した直後でも clip_library hit 候補を判定できる。
    sp, _name = load_screenplay_for_project(ts)
    enabled = bool(getattr(config, "CLIP_LIBRARY_ENABLED", False))

    out: list[dict[str, Any]] = []
    for s_idx, scene in enumerate(sp.get("scenes") or []):
        has_id = clip_library.scene_has_identity(scene)
        record: dict[str, Any] = {
            "scene_idx": s_idx,
            "has_identity": has_id,
            "satisfied": False,
        }
        if has_id:
            try:
                pool = clip_library.lookup_clip_pool(scene)
                if pool:
                    # variant 選択は決定論なので、UI には top-1 を表示。ts は
                    # validate_ts 後そのまま (basename は不要、関数は ts 全体で seed)
                    entry = clip_library.select_variant(pool, ts, s_idx)
                    record["satisfied"] = True
                    record["entry_id"] = entry.id
                    record["pool_size"] = len(pool)
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
                # silent failure を避けるため具体型を列挙。bare Exception では
                # ImportError 等の bug を mask してしまう。
                logger.warning(
                    "[clip-status] scene %d lookup 失敗: %s", s_idx, e,
                )
        out.append(record)
    return jsonify({"enabled": enabled, "scenes": out})
