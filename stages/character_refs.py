"""scene_gen.py から character ref 解決 helper を切り出した module。

将来 PR で _detect_storyboard_image / _generate_background_with_retry 等の
bg 関連 helper も本 module 群に集約する (= 計画書 §3.1.1-b 段階移行)。

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.1.1
"""

from __future__ import annotations

import logging
import os

import config

logger = logging.getLogger(__name__)


def resolve_character_refs(scene: dict) -> list[str]:
    """scene.identity.character_refs (SSOT) から参照画像を解決する。

    存在チェックを通って見つかった画像のみ返す。重複は除外。見つからない
    ref は warning ログを出して skip (= 不在自体は fail にしない)。
    """
    identity = scene.get("identity") or {}
    if "character_refs" in identity:
        names = list(identity.get("character_refs") or [])
    else:
        names = list(config.DEFAULT_CHARACTER_REFS)

    seen: set[str] = set()
    resolved: list[str] = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        ref_path = os.path.join(config.CHARACTERS_DIR, f"{name}.png")
        if os.path.exists(ref_path):
            resolved.append(ref_path)
        else:
            logger.warning("キャラクター参照画像が見つかりません: %s", ref_path)
    return resolved
