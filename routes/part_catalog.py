"""``GET /api/parts/catalog`` の Blueprint。

Stage 1 UI で scene_parts / global_parts を編集する際に、利用可能な part の
カタログ (= id / description / params_schema / valid_contexts) を一括で返す。
SSOT は `config/part_registry/<category>.yaml` で、yaml load + cache は
`part_registry_loader` に集約 (= validator / clip_library / intent_resolver と
同じ cache を共有)。

Frontend (= ScriptEditPanel.tsx の新セクション) はこの endpoint を 1 回叩いて
全 categories を取得し、enum selector を構築する。

設計 doc: `docs/plannings/2026-05-10_compositional-architecture.md` §4
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify

import config
import part_registry_loader as _registry

logger = logging.getLogger(__name__)

part_catalog_bp = Blueprint("part_catalog", __name__)


# 「visual_intents 専用フィールド」は他カテゴリ entry に出力しない (= frontend で
# type 判別を間違わないため)。
_INTENT_ONLY_FIELDS = (
    "valid_start_emotions",
    "duration_buckets",
    "compatible_with",
    "motion_intensity_bucket",
)


def _normalize_entry(entry: dict[str, Any], category: str) -> dict[str, Any]:
    """yaml entry を frontend 向けに整形。

    - description は trim
    - params_schema は dict のまま (= frontend で type を見て input element を選ぶ)
    - valid_contexts は ["scene"] / ["global"] / ["scene", "global"] のいずれか
    - visual_intents 専用フィールドは category=visual_intents のときのみ出力
    """

    out: dict[str, Any] = {
        "id": entry.get("id"),
        "description": (entry.get("description") or "").strip(),
        "params_schema": entry.get("params_schema") or {},
        "valid_contexts": list(entry.get("valid_contexts") or []),
        "deprecated": bool(entry.get("deprecated", False)),
    }
    if category == "visual_intents":
        out["valid_start_emotions"] = list(
            entry.get("valid_start_emotions") or []
        )
        out["duration_buckets"] = list(entry.get("duration_buckets") or [])
        out["compatible_with"] = list(entry.get("compatible_with") or [])
        out["motion_intensity_bucket"] = entry.get("motion_intensity_bucket")
    return out


def _category_status(category: str) -> str:
    """yaml の存在 / parse 状況を 3 値で返す (= "ok" | "missing" | "parse_error")。

    SSOT loader の `load_registry` は parse error 時にも空 tuple を返してしまうため、
    deploy 事故 (= yaml 消失) と「カテゴリが空」を区別するためにここで file 直接
    確認する。
    """

    base = Path(getattr(config, "PART_REGISTRY_DIR", ""))
    yaml_path = base / f"{category}.yaml"
    if not yaml_path.exists():
        return "missing"
    try:
        import yaml  # type: ignore[import-not-found]

        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except ImportError:
        # pyyaml 不在は missing 同等扱い (= 全 category 同じ理由で空になる)
        return "missing"
    except (yaml.YAMLError, OSError) as e:
        logger.error("[part-catalog] %s.yaml parse failed: %s", category, e)
        return "parse_error"
    if not isinstance(data, dict):
        return "parse_error"
    return "ok"


def _load_category(category: str) -> dict[str, Any]:
    """1 category の yaml を読んで normalize した entries を返す。"""

    entries = [_normalize_entry(dict(e), category) for e in _registry.load_registry(category)]
    status = _category_status(category)
    return {
        "category": category,
        "entries": entries,
        "status": status,
        # 後方互換: 旧 frontend は found を見る
        "found": status == "ok",
    }


@part_catalog_bp.route("/api/parts/catalog", methods=["GET"])
def get_catalog():
    """全 part_registry yaml を JSON で返す。

    Response shape:
      {
        "categories": {
          "subtitle_styles": {
            "category": "subtitle_styles", "found": true, "status": "ok",
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
    for cat in _registry.KNOWN_CATEGORIES:
        out[cat] = _load_category(cat)
    return jsonify({"categories": out})
