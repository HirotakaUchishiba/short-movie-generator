"""``GET /api/parts/catalog`` の Blueprint。

Stage 1 UI で scene_parts / global_parts を編集する際に、利用可能な part の
カタログ (= id / description / params_schema / valid_contexts) を一括で返す。
SSOT は `config/part_registry/<category>.yaml`。

Frontend (= ScriptEditPanel.tsx の新セクション) はこの endpoint を 1 回叩いて
全 categories を取得し、enum selector を構築する。

設計 doc: `docs/plannings/2026-05-10_compositional-architecture.md` §4
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify

import config

logger = logging.getLogger(__name__)

part_catalog_bp = Blueprint("part_catalog", __name__)


# scene_parts / global_parts のどちらに置くべきかを示すヒント。
# valid_contexts (= yaml の `valid_contexts` フィールド) と一致させる。
_KNOWN_CATEGORIES: tuple[str, ...] = (
    "subtitle_styles",
    "stickers",
    "filter_presets",
    "camera_moves",
    "lower_thirds",
    "title_cards",
    "transitions",
    "frame_layouts",
    "visual_intents",
)


def _load_yaml(yaml_path: Path) -> dict[str, Any] | None:
    if not yaml_path.exists():
        return None
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("[part-catalog] pyyaml not installed")
        return None
    try:
        return yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as e:
        logger.warning("[part-catalog] %s parse error: %s", yaml_path, e)
        return None


def _normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """yaml entry を frontend 向けに整形。

    - description は trim
    - params_schema は dict のまま (= frontend で type を見て input element を選ぶ)
    - valid_contexts は ["scene"] / ["global"] / ["scene", "global"] のいずれか
    """

    return {
        "id": entry.get("id"),
        "description": (entry.get("description") or "").strip(),
        "params_schema": entry.get("params_schema") or {},
        "valid_contexts": list(entry.get("valid_contexts") or []),
        "deprecated": bool(entry.get("deprecated", False)),
        # visual_intents 専用フィールド (= 他カテゴリでは undefined)
        "valid_start_emotions": list(
            entry.get("valid_start_emotions") or []
        ),
        "duration_buckets": list(entry.get("duration_buckets") or []),
        "compatible_with": list(entry.get("compatible_with") or []),
        "motion_intensity_bucket": entry.get("motion_intensity_bucket"),
    }


def _load_category(category: str) -> dict[str, Any]:
    """1 category の yaml を読んで normalize した entries を返す。"""

    base = Path(getattr(config, "PART_REGISTRY_DIR", ""))
    yaml_path = base / f"{category}.yaml"
    data = _load_yaml(yaml_path)
    if data is None:
        return {"category": category, "entries": [], "found": False}
    entries = [
        _normalize_entry(e)
        for e in (data.get("parts") or [])
        if isinstance(e, dict) and isinstance(e.get("id"), str)
    ]
    return {
        "category": category,
        "version": data.get("version"),
        "entries": entries,
        "found": True,
    }


@part_catalog_bp.route("/api/parts/catalog", methods=["GET"])
def get_catalog():
    """全 part_registry yaml を JSON で返す。

    Response shape:
      {
        "categories": {
          "subtitle_styles": {
            "category": "subtitle_styles", "version": 1, "found": true,
            "entries": [
              {"id": "minimal", "description": "...",
               "params_schema": {...}, "valid_contexts": ["scene"],
               "deprecated": false, ...},
              ...
            ]
          },
          ...
        }
      }
    """

    out: dict[str, dict[str, Any]] = {}
    for cat in _KNOWN_CATEGORIES:
        out[cat] = _load_category(cat)
    return jsonify({"categories": out})
