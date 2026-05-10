"""``part_registry_loader.py`` の単体テスト + 4 consumer drift 監査。

設計 doc: docs/plannings/2026-05-10_compositional-architecture.md §4
"""

from __future__ import annotations

from pathlib import Path

import pytest

import part_registry_loader as loader


@pytest.fixture
def isolated_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """テストごとに分離した PART_REGISTRY_DIR を使う + cache を確実にクリア。"""

    monkeypatch.setattr("config.PART_REGISTRY_DIR", str(tmp_path))
    loader.reset_cache()
    yield tmp_path
    loader.reset_cache()


def _write_yaml(path: Path, payload: str) -> None:
    path.write_text(payload, encoding="utf-8")


class TestLoadRegistry:
    def test_missing_yaml_returns_empty(self, isolated_registry: Path) -> None:
        assert loader.load_registry("subtitle_styles") == ()

    def test_parse_error_returns_empty(self, isolated_registry: Path) -> None:
        _write_yaml(
            isolated_registry / "subtitle_styles.yaml",
            "this is: not: yaml: parsable {{",
        )
        assert loader.load_registry("subtitle_styles") == ()

    def test_valid_yaml_returns_dict_tuple(
        self, isolated_registry: Path
    ) -> None:
        _write_yaml(
            isolated_registry / "subtitle_styles.yaml",
            """
parts:
  - id: minimal
    description: シンプル字幕
    valid_contexts: [scene]
  - id: bold
    description: 太字
    valid_contexts: [scene]
""",
        )
        result = loader.load_registry("subtitle_styles")
        assert len(result) == 2
        assert result[0]["id"] == "minimal"
        assert result[1]["id"] == "bold"

    def test_entries_without_id_are_skipped(
        self, isolated_registry: Path
    ) -> None:
        _write_yaml(
            isolated_registry / "subtitle_styles.yaml",
            """
parts:
  - id: minimal
  - description: id 欠落
  - id: 123  # 非 str
""",
        )
        result = loader.load_registry("subtitle_styles")
        assert len(result) == 1
        assert result[0]["id"] == "minimal"


class TestListIds:
    def test_returns_frozenset(self, isolated_registry: Path) -> None:
        _write_yaml(
            isolated_registry / "subtitle_styles.yaml",
            "parts:\n  - id: a\n  - id: b\n",
        )
        ids = loader.list_ids("subtitle_styles")
        assert isinstance(ids, frozenset)
        assert ids == frozenset({"a", "b"})

    def test_missing_returns_empty_frozenset(
        self, isolated_registry: Path
    ) -> None:
        assert loader.list_ids("subtitle_styles") == frozenset()


class TestCompatibleWithMap:
    def test_visual_intents_compatible_with(
        self, isolated_registry: Path
    ) -> None:
        _write_yaml(
            isolated_registry / "visual_intents.yaml",
            """
parts:
  - id: talking_head_calm
    compatible_with: [reaction_surprise]
  - id: reaction_surprise
    compatible_with: [talking_head_calm, listening]
""",
        )
        m = loader.compatible_with_map("visual_intents")
        assert m["talking_head_calm"] == frozenset({"reaction_surprise"})
        assert m["reaction_surprise"] == frozenset(
            {"talking_head_calm", "listening"}
        )


class TestResetCache:
    def test_reset_invalidates_all_categories(
        self, isolated_registry: Path
    ) -> None:
        # 最初は空
        assert loader.list_ids("subtitle_styles") == frozenset()
        # yaml を書き足す
        _write_yaml(
            isolated_registry / "subtitle_styles.yaml",
            "parts:\n  - id: minimal\n",
        )
        # cache が古い間は空
        assert loader.list_ids("subtitle_styles") == frozenset()
        # reset 後は反映される
        loader.reset_cache()
        assert loader.list_ids("subtitle_styles") == frozenset({"minimal"})


class TestKnownCategoriesDriftGuard:
    """`KNOWN_CATEGORIES` SSOT が validator / part_catalog 双方の前提と
    一致することを保証する (= drift 検出)。
    """

    def test_validator_part_field_categories_subset(self) -> None:
        import screenplay_validator as sv

        all_consumer_categories: set[str] = set()
        all_consumer_categories.update(sv._SCENE_PART_FIELDS_SINGLE.values())
        all_consumer_categories.update(sv._SCENE_PART_FIELDS_ARRAY.values())
        all_consumer_categories.update(sv._GLOBAL_PART_FIELDS.values())
        # validator が参照する全カテゴリは KNOWN_CATEGORIES に含まれる必要がある
        # (= 逆は要らない: visual_intents は validator から直接参照されない)
        missing = all_consumer_categories - set(loader.KNOWN_CATEGORIES)
        assert missing == set(), f"validator が参照する未知カテゴリ: {missing}"

    def test_part_catalog_endpoint_uses_loader_known_categories(self) -> None:
        # part_catalog は loader.KNOWN_CATEGORIES を直接 import している
        # (= 二重定義無し)。import path だけ検証。
        from routes import part_catalog as pc

        assert pc._registry.KNOWN_CATEGORIES is loader.KNOWN_CATEGORIES


class TestConsumerSharedCache:
    """4 consumer (validator / clip_library / intent_resolver / part_catalog) が
    同じ SSOT cache を読むことを保証する (= reset_cache 1 回で全員同期)。
    """

    def test_validator_uses_loader_cache(
        self, isolated_registry: Path
    ) -> None:
        import screenplay_validator as sv

        # validator の reset は SSOT cache を消す (= 旧 _PART_REGISTRY_CACHE は廃止)
        _write_yaml(
            isolated_registry / "subtitle_styles.yaml",
            "parts:\n  - id: alpha\n",
        )
        sv.reset_part_registry_cache()
        assert sv._load_part_registry_ids("subtitle_styles") == frozenset(
            {"alpha"}
        )

    def test_clip_library_uses_loader_cache(
        self, isolated_registry: Path
    ) -> None:
        import clip_library as cl

        _write_yaml(
            isolated_registry / "visual_intents.yaml",
            """
parts:
  - id: a
    compatible_with: [b]
  - id: b
""",
        )
        cl.reset_intent_compat_cache()
        assert cl._intent_compatible("a", "b") is True
        assert cl._intent_compatible("b", "a") is True
        # compat に書かれていない pair は False
        assert cl._intent_compatible("a", "c") is False

    def test_intent_resolver_uses_loader_cache(
        self, isolated_registry: Path
    ) -> None:
        from analyze import intent_resolver as ir

        _write_yaml(
            isolated_registry / "visual_intents.yaml",
            """
parts:
  - id: ix
    description: テスト
    valid_start_emotions: [中立]
    duration_buckets: [5]
    motion_intensity_bucket: low
    compatible_with: []
  - id: dep
    deprecated: true
""",
        )
        loader.reset_cache()
        catalog = ir.load_intent_catalog()
        ids = {e.id for e in catalog}
        assert "ix" in ids
        # deprecated は filter される
        assert "dep" not in ids
