"""BGM ライブラリ (Stage bgm 用)。

`data/bgm_catalog.json` から BGM 一覧を読み、id → `assets/bgm/<file>` のパスを
解決する。実音源は **商用利用可** のもの (Pixabay / Uppbeat / YouTube Audio
Library 等) を運用者が `assets/bgm/` に配置し catalog に登録する。Phase 2 で
生成 AI (fal.ai) 取得を追加する想定。詳細は
docs/plannings/2026-05-27_bgm-overlay-stage.md。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass

import config

logger = logging.getLogger(__name__)

NONE_ID = "none"


@dataclass
class BgmTrack:
    id: str
    title: str
    file: str
    mood: str
    duration_sec: float | None
    license: str
    source: str


def load_catalog() -> list[BgmTrack]:
    """catalog json を読む。不在 / 壊れ / pyyaml 不要 (json) → 空 list (graceful)。"""
    path = config.BGM_CATALOG_PATH
    if not os.path.exists(path):
        logger.info("[bgm] catalog not found: %s", path)
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[bgm] catalog read error: %s", e)
        return []
    out: list[BgmTrack] = []
    for e in data if isinstance(data, list) else []:
        if isinstance(e, dict) and isinstance(e.get("id"), str):
            out.append(BgmTrack(
                id=e["id"],
                title=e.get("title") or e["id"],
                file=e.get("file") or "",
                mood=e.get("mood") or "",
                duration_sec=e.get("duration_sec"),
                license=e.get("license") or "unknown",
                source=e.get("source") or "",
            ))
    return out


def list_bgm() -> list[dict]:
    """UI 用に catalog を dict list で返す (実ファイルが存在するものだけ)。"""
    out = []
    for t in load_catalog():
        p = os.path.join(config.BGM_DIR, t.file) if t.file else ""
        if p and os.path.exists(p):
            out.append(asdict(t))
    return out


def resolve_bgm_path(bgm_id: str | None) -> str | None:
    """bgm_id → `assets/bgm/<file>` 絶対パス。

    none / 空 / 未定義 / file 欠落 / 実ファイル不在 はすべて None (= BGM なし扱い)。
    """
    if not bgm_id or bgm_id == NONE_ID:
        return None
    for t in load_catalog():
        if t.id == bgm_id:
            if not t.file:
                return None
            p = os.path.join(config.BGM_DIR, t.file)
            return p if os.path.exists(p) else None
    logger.warning("[bgm] unknown bgm_id: %s", bgm_id)
    return None
