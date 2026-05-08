"""Phase X-1: scene の組み合わせ identity を計算する純粋関数。

`docs/plannings/2026-05-08_composition-cache-design.md` で定義された 3 層モデル
の Layer 2 (= Composition Identity) に対応。X-1 段階の v1 は scene が現状持って
いる atomic 情報 (= location_ref + character_refs) のみから派生する。X-2 で
``actions/`` / ``hooks/`` / ``arcs/`` SSOT が導入されたら v2 を追加し、両者を
``composition_version`` で区別して並走させる前提。

X-1 では bg_cache / kling_cache の meta と experiment_assignments テーブルに
書き込まれるが、cache key そのものには影響しない (= 既存の prompt SHA 完全一致
は破壊しない)。
"""
from __future__ import annotations

import hashlib
import json

COMPOSITION_VERSION_V1 = "v1"


def compute_composition_id(
    *,
    location_ref: str | None,
    character_refs: list[str] | None,
    version: str = COMPOSITION_VERSION_V1,
) -> str:
    """scene の組み合わせ identity (= 16 桁 hex) を決定論的に派生する。

    引数:
        location_ref: scene.location_ref。None なら空文字列扱い。
        character_refs: scene.character_refs。None なら空リスト扱い。
            順序非依存に固定するため sorted で正規化する。
        version: 計算式のバージョンタグ。X-1 では "v1" のみ受理。

    返り値:
        16 桁の hex 文字列 (= sha256 の最初の 16 文字)。
    """
    if version != COMPOSITION_VERSION_V1:
        raise ValueError(f"unknown composition version: {version}")
    payload = {
        "version": version,
        "location_ref": location_ref or "",
        "character_refs": sorted(character_refs or []),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
