"""効果音 (SE) ライブラリ (Stage se 用)。bgm_library と同型。

`data/se_catalog.json` から SE 一覧を読み、id → `assets/se/<file>` を解決する。
category (sting / transition / reaction / emphasis) でフィルタもできる
(= se_planner が emotion/intent → category → 具体 SE を選ぶのに使う)。実音源は
商用利用可のものを運用者が `assets/se/` に配置する。詳細は
docs/plannings/2026-05-27_se-overlay-stage.md。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass

import config

logger = logging.getLogger(__name__)


@dataclass
class SeTrack:
    id: str
    title: str
    file: str
    category: str
    license: str
    source: str


def load_catalog() -> list[SeTrack]:
    """catalog json を読む。不在 / 壊れは空 list (graceful)。"""
    path = config.SE_CATALOG_PATH
    if not os.path.exists(path):
        logger.info("[se] catalog not found: %s", path)
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[se] catalog read error: %s", e)
        return []
    out: list[SeTrack] = []
    for e in data if isinstance(data, list) else []:
        if isinstance(e, dict) and isinstance(e.get("id"), str):
            out.append(SeTrack(
                id=e["id"],
                title=e.get("title") or e["id"],
                file=e.get("file") or "",
                category=e.get("category") or "",
                license=e.get("license") or "unknown",
                source=e.get("source") or "",
            ))
    return out


def _probe_duration(path: str) -> float:
    """ffprobe で音源長 (秒) を返す。失敗時 0.0。"""
    import json as _json
    import subprocess
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", path],
            capture_output=True, text=True, timeout=10)
        return round(float(_json.loads(r.stdout)["format"]["duration"]), 3)
    except (subprocess.SubprocessError, ValueError, KeyError, OSError):
        return 0.0


def list_se() -> list[dict]:
    """UI 用に catalog を dict list で返す (実ファイルが存在するもの + duration_sec)。"""
    out = []
    for t in load_catalog():
        p = os.path.join(config.SE_DIR, t.file) if t.file else ""
        if p and os.path.exists(p):
            d = asdict(t)
            d["duration_sec"] = _probe_duration(p)
            out.append(d)
    return out


def resolve_se_path(se_id: str | None) -> str | None:
    """se_id → `assets/se/<file>` 絶対パス。未定義 / file 欠落 / 不在は None。"""
    if not se_id:
        return None
    for t in load_catalog():
        if t.id == se_id:
            if not t.file:
                return None
            p = os.path.join(config.SE_DIR, t.file)
            return p if os.path.exists(p) else None
    logger.warning("[se] unknown se_id: %s", se_id)
    return None


def se_by_category(category: str) -> list[SeTrack]:
    """指定 category の SE で実ファイルが存在するもの (= se_planner の選択候補)。"""
    out = []
    for t in load_catalog():
        if t.category == category and t.file:
            p = os.path.join(config.SE_DIR, t.file)
            if os.path.exists(p):
                out.append(t)
    return out
