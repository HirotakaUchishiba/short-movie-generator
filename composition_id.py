"""Phase X-1 / X-2a: scene の組み合わせ identity を計算する純粋関数。

`docs/plannings/2026-05-08_composition-cache-design.md` で定義された 3 層モデル
の Layer 2 (= Composition Identity) に対応。

- v1 (Phase X-1): (location_ref, sorted(character_refs)) から派生
- v2 (Phase X-2a): v1 + action_id を加味

scene の atomic 情報からどの version を選ぶかは ``resolve_version`` で決定する。
``action_id`` がある場合は v2、無ければ v1 を返す。両 version は同じ集合 (= 同じ
location + 同じ character_refs) でも異なる hash を出すので、cache key 衝突は起き
ない。

X-2a では bg_cache / kling_cache の meta にのみ書き込まれる。
``experiment_assignments`` テーブルへの v2 composition_id 連動は scene 粒度
bandit を回す X-3 で wire される予定 (= 現状は ``record_assignments`` の caller
が composition_id を渡していないので NULL で記録される)。cache key そのもの
には影響しない (= 既存の prompt SHA 完全一致は破壊しない)。
"""
from __future__ import annotations

import hashlib
import json

COMPOSITION_VERSION_V1 = "v1"
COMPOSITION_VERSION_V2 = "v2"


def resolve_version(*, action_id: str | None) -> str:
    """scene の atomic 情報から最新適用版数を決める。

    action_id が与えられていれば v2、無ければ v1 を返す。X-2b 以降で hook_id /
    arc_id を取り込む v3 が出てきたらここで判定する想定。
    """
    if action_id:
        return COMPOSITION_VERSION_V2
    return COMPOSITION_VERSION_V1


def compute_composition_id(
    *,
    location_ref: str | None,
    character_refs: list[str] | None,
    action_id: str | None = None,
    version: str = COMPOSITION_VERSION_V1,
) -> str:
    """scene の組み合わせ identity (= 16 桁 hex) を決定論的に派生する。

    引数:
        location_ref: scene.location_ref。None なら空文字列扱い。
        character_refs: scene.character_refs。None なら空リスト扱い。
            順序非依存に固定するため sorted で正規化する。
        action_id: scene.action_id (Phase X-2a 以降)。v2 のときのみ payload に
            含める。v1 では無視される (= 引数として渡しても結果は変わらない)。
        version: 計算式のバージョンタグ。"v1" / "v2" を受理。

    返り値:
        16 桁の hex 文字列 (= sha256 の最初の 16 文字)。
    """
    if version == COMPOSITION_VERSION_V1:
        payload = {
            "version": version,
            "location_ref": location_ref or "",
            "character_refs": sorted(character_refs or []),
        }
    elif version == COMPOSITION_VERSION_V2:
        payload = {
            "version": version,
            "location_ref": location_ref or "",
            "character_refs": sorted(character_refs or []),
            "action_id": action_id or "",
        }
    else:
        raise ValueError(f"unknown composition version: {version}")
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
