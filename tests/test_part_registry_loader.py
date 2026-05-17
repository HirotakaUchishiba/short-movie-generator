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
        assert loader.load_registry("visual_intents") == ()

    def test_parse_error_returns_empty(self, isolated_registry: Path) -> None:
        _write_yaml(
            isolated_registry / "visual_intents.yaml",
            "this is: not: yaml: parsable {{",
        )
        assert loader.load_registry("visual_intents") == ()

    def test_valid_yaml_returns_dict_tuple(
        self, isolated_registry: Path
    ) -> None:
        _write_yaml(
            isolated_registry / "visual_intents.yaml",
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
        result = loader.load_registry("visual_intents")
        assert len(result) == 2
        assert result[0]["id"] == "minimal"
        assert result[1]["id"] == "bold"

    def test_entries_without_id_are_skipped(
        self, isolated_registry: Path
    ) -> None:
        _write_yaml(
            isolated_registry / "visual_intents.yaml",
            """
parts:
  - id: minimal
  - description: id 欠落
  - id: 123  # 非 str
""",
        )
        result = loader.load_registry("visual_intents")
        assert len(result) == 1
        assert result[0]["id"] == "minimal"


class TestListIds:
    def test_returns_frozenset(self, isolated_registry: Path) -> None:
        _write_yaml(
            isolated_registry / "visual_intents.yaml",
            "parts:\n  - id: a\n  - id: b\n",
        )
        ids = loader.list_ids("visual_intents")
        assert isinstance(ids, frozenset)
        assert ids == frozenset({"a", "b"})

    def test_missing_returns_empty_frozenset(
        self, isolated_registry: Path
    ) -> None:
        assert loader.list_ids("visual_intents") == frozenset()


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
        assert loader.list_ids("visual_intents") == frozenset()
        # yaml を書き足す
        _write_yaml(
            isolated_registry / "visual_intents.yaml",
            "parts:\n  - id: minimal\n",
        )
        # cache が古い間は空
        assert loader.list_ids("visual_intents") == frozenset()
        # reset 後は反映される
        loader.reset_cache()
        assert loader.list_ids("visual_intents") == frozenset({"minimal"})


class TestConsumerSharedCache:
    """3 consumer (validator / clip_library / intent_resolver) が同じ SSOT cache
    を読むことを保証する (= reset_cache 1 回で全員同期)。
    """

    def test_validator_uses_loader_cache(
        self, isolated_registry: Path
    ) -> None:
        import screenplay_validator as sv

        # validator の reset は SSOT cache を消す (= 旧 _PART_REGISTRY_CACHE は廃止)
        _write_yaml(
            isolated_registry / "visual_intents.yaml",
            "parts:\n  - id: alpha\n",
        )
        sv.reset_part_registry_cache()
        assert loader.list_ids("visual_intents") == frozenset({"alpha"})

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
