"""``GET /api/intent-catalog`` の Blueprint。

clip_library hard match key (= scene.annotation.visual_intent_id) の
カタログを Stage 1 / IntentCatalog ページに返す。SSOT は
`config/part_registry/visual_intents.yaml`、yaml load + cache は
`part_registry_loader` に集約 (= validator / clip_library /
intent_resolver と同じ cache を共有)。

2026-05-17 の Remotion / 演出パーツ撤去で他カテゴリの part_registry が
すべて消えたため、本 endpoint も visual_intents 単独を返す形に縮小した。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify

import config
import part_registry_loader as _registry

logger = logging.getLogger(__name__)

intent_catalog_bp = Blueprint("intent_catalog", __name__)

_CATEGORY = "visual_intents"


def _normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """yaml entry を frontend 向けに整形。"""

    return {
        "id": entry.get("id"),
        "description": (entry.get("description") or "").strip(),
        "params_schema": entry.get("params_schema") or {},
        "valid_contexts": list(entry.get("valid_contexts") or []),
        "deprecated": bool(entry.get("deprecated", False)),
        "valid_start_emotions": list(entry.get("valid_start_emotions") or []),
        "duration_buckets": list(entry.get("duration_buckets") or []),
        "compatible_with": list(entry.get("compatible_with") or []),
        "motion_intensity_bucket": entry.get("motion_intensity_bucket"),
    }


def _yaml_status() -> str:
    """yaml の存在 / parse 状況を 3 値で返す (= "ok" | "missing" | "parse_error")。

    SSOT loader の `load_registry` は parse error 時にも空 tuple を返してしまうため、
    deploy 事故 (= yaml 消失) と「entries が空」を区別するためにここで file 直接
    確認する。
    """

    base = Path(getattr(config, "PART_REGISTRY_DIR", ""))
    yaml_path = base / f"{_CATEGORY}.yaml"
    if not yaml_path.exists():
        return "missing"
    try:
        import yaml  # type: ignore[import-not-found]

        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except ImportError:
        # pyyaml 不在は missing 同等扱い
        return "missing"
    except (yaml.YAMLError, OSError) as e:
        logger.error("[intent-catalog] %s.yaml parse failed: %s", _CATEGORY, e)
        return "parse_error"
    if not isinstance(data, dict):
        return "parse_error"
    return "ok"


@intent_catalog_bp.route("/api/intent-catalog", methods=["GET"])
def get_catalog():
    """visual_intents yaml を JSON で返す。

    Response shape:
      {
        "category": "visual_intents",
        "status": "ok" | "missing" | "parse_error",
        "found": bool,
        "entries": [
          {"id": "talking_head_calm", "description": "...",
           "valid_start_emotions": [...], "duration_buckets": [...],
           "compatible_with": [...], "motion_intensity_bucket": "...",
           "params_schema": {...}, "valid_contexts": [...],
           "deprecated": false},
          ...
        ]
      }
    """

    entries = [_normalize_entry(dict(e)) for e in _registry.load_registry(_CATEGORY)]
    status = _yaml_status()
    return jsonify({
        "category": _CATEGORY,
        "status": status,
        "found": status == "ok",
        "entries": entries,
    })
