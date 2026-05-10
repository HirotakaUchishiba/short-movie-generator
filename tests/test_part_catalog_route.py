"""``GET /api/parts/catalog`` の統合テスト。

設計 doc: docs/plannings/2026-05-10_compositional-architecture.md §4
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def client():
    import preview_server

    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


class TestCatalogEndpoint:
    def test_returns_categories_dict(self, client) -> None:
        resp = client.get("/api/parts/catalog")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "categories" in data
        # 既知 categories が全部入っている
        for cat in (
            "subtitle_styles",
            "stickers",
            "filter_presets",
            "camera_moves",
            "lower_thirds",
            "title_cards",
            "transitions",
            "frame_layouts",
            "visual_intents",
        ):
            assert cat in data["categories"]

    def test_subtitle_styles_has_minimal(self, client) -> None:
        resp = client.get("/api/parts/catalog")
        data = resp.get_json()
        sub_cat = data["categories"]["subtitle_styles"]
        assert sub_cat["found"] is True
        ids = {e["id"] for e in sub_cat["entries"]}
        assert "minimal" in ids
        assert "fade_in" in ids
        assert "karaoke_bold" in ids

    def test_entry_shape(self, client) -> None:
        resp = client.get("/api/parts/catalog")
        data = resp.get_json()
        entry = data["categories"]["subtitle_styles"]["entries"][0]
        # 必須キーが揃っている
        for key in (
            "id",
            "description",
            "params_schema",
            "valid_contexts",
            "deprecated",
        ):
            assert key in entry

    def test_visual_intents_has_extra_fields(self, client) -> None:
        """visual_intents 専用フィールド (= valid_start_emotions / compatible_with /
        duration_buckets / motion_intensity_bucket) が出ている。"""

        resp = client.get("/api/parts/catalog")
        data = resp.get_json()
        vi_entries = data["categories"]["visual_intents"]["entries"]
        assert len(vi_entries) > 0
        e = vi_entries[0]
        assert "valid_start_emotions" in e
        assert "duration_buckets" in e
        assert "compatible_with" in e
        assert "motion_intensity_bucket" in e

    def test_missing_category_returns_found_false(
        self, client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 一時的に PART_REGISTRY_DIR を空ディレクトリに切替え + SSOT cache を
        # reset すると found:false / status:missing になる
        import part_registry_loader

        monkeypatch.setattr("config.PART_REGISTRY_DIR", str(tmp_path))
        part_registry_loader.reset_cache()
        try:
            resp = client.get("/api/parts/catalog")
            data = resp.get_json()
            for cat_name, cat_data in data["categories"].items():
                assert cat_data["found"] is False
                assert cat_data["status"] == "missing"
                assert cat_data["entries"] == []
        finally:
            part_registry_loader.reset_cache()
