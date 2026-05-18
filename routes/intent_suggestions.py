"""``/api/intent-suggestions/*`` の Blueprint。

novel intent 候補 (= ``analyze`` pipeline 検出 + ``data/intent_suggestions.json``)
を UI から閲覧 / トリアージ / yaml snippet 取得するための API。

設計 doc: docs/plannings/2026-05-10_intent-suggestion-flow.md §3
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from flask import Blueprint, abort, jsonify, request

from analyze import suggestion_store
from analyze.suggestion_yaml import render_yaml_snippet
from routes._helpers import api_error

logger = logging.getLogger(__name__)

intent_suggestions_bp = Blueprint("intent_suggestions", __name__)


def _record_to_dict(rec: suggestion_store.IntentSuggestionRecord) -> dict[str, Any]:
    """``IntentSuggestionRecord`` を JSON-serializable dict に変換。"""

    d = asdict(rec)
    d["scene_indices"] = list(rec.scene_indices)
    return d


def _refresh_merged() -> int:
    """``visual_intents.yaml`` の現在 id 集合を読み、accepted entry のうち
    yaml に登場している proposed_id を merged に遅延更新する。

    yaml 取得失敗時 (= module 未解決 / yaml 構文エラー) は 0 件扱いで継続。
    """

    try:
        import part_registry_loader as _registry
        entries = _registry.load_registry("visual_intents")
    except (ImportError, OSError, ValueError) as e:
        logger.warning("[intent-suggestions] yaml lookup failed: %s", e)
        return 0
    yaml_ids = {
        str(entry.get("id"))
        for entry in entries
        if isinstance(entry, dict) and entry.get("id")
    }
    if not yaml_ids:
        return 0
    updated = suggestion_store.mark_merged_against_yaml(yaml_ids)
    if updated:
        logger.info(
            "[intent-suggestions] %d accepted entries promoted to merged",
            len(updated),
        )
    return len(updated)


@intent_suggestions_bp.route("/api/intent-suggestions", methods=["GET"])
def list_suggestions():
    """suggestion 一覧を返す (= UI のトリアージ画面用)。

    クエリ:
      - status: all / new / reviewing / accepted / dismissed / merged (default: all)

    Response:
      {
        "entries": [_record_to_dict(r), ...],
        "counts": {<status>: <count>}
      }
    """

    _refresh_merged()
    status_filter = request.args.get("status", "all")
    try:
        records = suggestion_store.list_by_status(status_filter)
    except ValueError as e:
        abort(400, str(e))
    counts = suggestion_store.counts_by_status()
    return jsonify(
        {
            "entries": [_record_to_dict(r) for r in records],
            "counts": counts,
        }
    )


@intent_suggestions_bp.route(
    "/api/intent-suggestions/<suggestion_id>/mark-reviewing",
    methods=["POST"],
)
def mark_reviewing(suggestion_id: str):
    """status を ``reviewing`` に遷移させる。"""

    try:
        rec = suggestion_store.update_status(suggestion_id, "reviewing")
    except KeyError:
        abort(404, f"suggestion not found: {suggestion_id}")
    except ValueError as e:
        return api_error(
            "INTENT_SUGGESTION_STATE_CONFLICT", str(e), 409,
            suggestion_id=suggestion_id,
        )
    return jsonify({"ok": True, "record": _record_to_dict(rec)})


@intent_suggestions_bp.route(
    "/api/intent-suggestions/<suggestion_id>/dismiss", methods=["POST"]
)
def dismiss(suggestion_id: str):
    """status を ``dismissed`` に遷移させる。

    Body: {"reason": str}  ← 必須、空文字 / None は 400 で reject
    """

    body = request.get_json(silent=True) or {}
    reason_raw = body.get("reason")
    if not isinstance(reason_raw, str) or not reason_raw.strip():
        abort(400, "reason is required (non-empty string)")
    try:
        rec = suggestion_store.update_status(
            suggestion_id, "dismissed", reason=reason_raw
        )
    except KeyError:
        abort(404, f"suggestion not found: {suggestion_id}")
    except ValueError as e:
        return api_error(
            "INTENT_SUGGESTION_STATE_CONFLICT", str(e), 409,
            suggestion_id=suggestion_id,
        )
    return jsonify({"ok": True, "record": _record_to_dict(rec)})


@intent_suggestions_bp.route(
    "/api/intent-suggestions/<suggestion_id>/accept", methods=["POST"]
)
def accept(suggestion_id: str):
    """status を ``accepted`` に遷移させ、yaml snippet を返す。

    Response:
      {"ok": True, "record": ..., "yaml_snippet": "<yaml string>"}

    snippet は visual_intents.yaml に貼り付ければそのまま valid な entry に
    なるが、TODO コメントが含まれており運用者が手で整える前提。
    """

    try:
        rec = suggestion_store.update_status(suggestion_id, "accepted")
    except KeyError:
        abort(404, f"suggestion not found: {suggestion_id}")
    except ValueError as e:
        return api_error(
            "INTENT_SUGGESTION_STATE_CONFLICT", str(e), 409,
            suggestion_id=suggestion_id,
        )
    snippet = render_yaml_snippet(rec)
    return jsonify(
        {"ok": True, "record": _record_to_dict(rec), "yaml_snippet": snippet}
    )


@intent_suggestions_bp.route(
    "/api/intent-suggestions/<suggestion_id>/yaml", methods=["GET"]
)
def get_yaml(suggestion_id: str):
    """1 entry の yaml snippet を text/yaml で返す (= 再取得用)。"""

    records = {r.id: r for r in suggestion_store.load()}
    rec = records.get(suggestion_id)
    if rec is None:
        abort(404, f"suggestion not found: {suggestion_id}")
    snippet = render_yaml_snippet(rec)
    return (snippet, 200, {"Content-Type": "text/yaml; charset=utf-8"})
