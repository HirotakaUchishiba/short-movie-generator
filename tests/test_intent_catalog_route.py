"""``GET /api/intent-catalog`` の統合テスト。

2026-05-17 Remotion / 演出パーツ撤去後、part_registry は visual_intents のみ。
endpoint も /api/parts/catalog (= 旧 multi-category) から
/api/intent-catalog (= 単一カテゴリ) に変更された。
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def client():
    import preview_server

    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


class TestIntentCatalogEndpoint:
    def test_returns_visual_intents_payload(self, client) -> None:
        resp = client.get("/api/intent-catalog")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["category"] == "visual_intents"
        assert data["status"] == "ok"
        assert data["found"] is True
        assert isinstance(data["entries"], list)
        assert len(data["entries"]) > 0

    def test_entry_shape(self, client) -> None:
        resp = client.get("/api/intent-catalog")
        data = resp.get_json()
        entry = data["entries"][0]
        for key in (
            "id",
            "description",
            "params_schema",
            "valid_contexts",
            "deprecated",
            "valid_start_emotions",
            "duration_buckets",
            "compatible_with",
            "motion_intensity_bucket",
        ):
            assert key in entry

    def test_missing_yaml_returns_found_false(
        self, client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import part_registry_loader

        monkeypatch.setattr("config.PART_REGISTRY_DIR", str(tmp_path))
        part_registry_loader.reset_cache()
        try:
            resp = client.get("/api/intent-catalog")
            data = resp.get_json()
            assert data["found"] is False
            assert data["status"] == "missing"
            assert data["entries"] == []
        finally:
            part_registry_loader.reset_cache()
