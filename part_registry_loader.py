"""``config/part_registry/<category>.yaml`` の単一ロード経路 (= SSOT cache)。

screenplay_validator / clip_library / analyze.intent_resolver / routes.intent_catalog
の 4 consumer が同じ yaml を独立に load + 独立に cache していた。Cache invalidation
が散る + 各々で例外型の絞り方が違う、という drift 元になっていたため、ここに
集約する。

現状の唯一の category は ``visual_intents`` (= clip_library の hard match key)。
2026-05-17 の Remotion / 演出パーツ撤去 (= ``2026-05-17_drop-remotion-and-parts.md``)
で他カテゴリ (subtitle_styles / stickers / ...) は全削除済み。loader API は
generic な形を残しているが、実用上は ``"visual_intents"`` のみが渡される。

利用側は `load_registry(category)` / `list_ids(category)` / `compatible_with_map()`
を呼び、test では `reset_cache()` 1 行で 4 consumer すべてが同期的に再読込される。
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def _yaml_path(category: str) -> Path:
    return Path(getattr(config, "PART_REGISTRY_DIR", "")) / f"{category}.yaml"


@functools.lru_cache(maxsize=None)
def load_registry(category: str) -> tuple[dict, ...]:
    """指定 category の yaml の `parts` 配列を **dict の tuple** で返す。

    yaml が無い / pyyaml 未導入 / parse 失敗 の場合は空 tuple。
    consumer 側は「空 tuple = 該当 category 不在」とみなして fallback する。

    返り値が tuple なのは lru_cache に hashable な値を入れる必要があるため。
    consumer 側で list() に変換しても良い (= shallow なので副作用はない)。
    """

    path = _yaml_path(category)
    if not path.exists():
        logger.info("[part-registry] %s.yaml not found at %s", category, path)
        return ()
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "[part-registry] pyyaml not installed — %s skipped", category
        )
        return ()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as e:
        logger.warning("[part-registry] %s.yaml parse error: %s", category, e)
        return ()

    out: list[dict] = []
    for entry in (data or {}).get("parts") or []:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            out.append(entry)
    return tuple(out)


def list_ids(category: str) -> frozenset[str]:
    """category の有効 id 集合 (= validator の整合チェック用)。"""

    return frozenset(e["id"] for e in load_registry(category))


def compatible_with_map(category: str = "visual_intents") -> dict[str, frozenset[str]]:
    """category の各 entry の `compatible_with` を id → frozenset で返す。

    visual_intents 以外のカテゴリには `compatible_with` フィールドが無いため
    通常空 dict (= 各 entry の get で空集合) になる。clip_library の variant
    互換判定 + intent_resolver の suggestion 整合チェックで共有する。
    """

    out: dict[str, frozenset[str]] = {}
    for e in load_registry(category):
        compat = e.get("compatible_with") or []
        if isinstance(compat, list):
            out[e["id"]] = frozenset(c for c in compat if isinstance(c, str))
    return out


def reset_cache() -> None:
    """テスト用: 全 consumer を強制再ロードする (= monkeypatch 後の同期点)。

    `monkeypatch.setattr("config.PART_REGISTRY_DIR", new_dir)` の後にこれを
    呼べば、validator / clip_library / intent_catalog / intent_resolver すべてが
    新ディレクトリを読みに行く。
    """

    load_registry.cache_clear()
