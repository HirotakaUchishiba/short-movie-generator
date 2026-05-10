"""``/api/intent-suggestions/*`` の統合テスト。

設計 doc: docs/plannings/2026-05-10_intent-suggestion-flow.md §3
"""

from __future__ import annotations

import pytest

from analyze import suggestion_store
from analyze.suggestion_store import (
    IntentSuggestionRecord,
    compute_id,
    save,
)


@pytest.fixture
def client(monkeypatch):
    """preview_server の test client。conftest._isolate_intent_suggestions が
    INTENT_SUGGESTIONS_PATH を tmp_path に向けているので副作用が発生しない。
    """

    import preview_server

    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


def _make_record(
    proposed_id: str = "frantic_typing",
    description: str = "subject types furiously",
    status: str = "new",
    dismissed_reason: str | None = None,
) -> IntentSuggestionRecord:
    sid = compute_id(proposed_id, description)
    return IntentSuggestionRecord(
        id=sid,
        proposed_id=proposed_id,
        description=description,
        rationale="rationale for " + proposed_id,
        scene_indices=(3, 7),
        source_screenplay="screenplays/auto_x.json",
        source_analyze_job_id="job-x",
        status=status,  # type: ignore[arg-type]
        dismissed_reason=dismissed_reason,
        occurrences=1,
        created_at="2026-05-10T00:00:00Z",
        updated_at="2026-05-10T00:00:00Z",
    )


# ───────────── GET /api/intent-suggestions ─────────────


class TestListSuggestions:
    def test_empty_inbox_returns_empty(self, client) -> None:
        resp = client.get("/api/intent-suggestions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["entries"] == []
        # counts は全 status 0
        assert data["counts"]["new"] == 0
        assert data["counts"]["merged"] == 0

    def test_returns_records_and_counts(self, client) -> None:
        save(
            [
                _make_record("a", "d1", status="new"),
                _make_record("b", "d2", status="new"),
                _make_record("c", "d3", status="reviewing"),
            ]
        )
        resp = client.get("/api/intent-suggestions")
        data = resp.get_json()
        assert len(data["entries"]) == 3
        assert data["counts"]["new"] == 2
        assert data["counts"]["reviewing"] == 1

    def test_status_filter(self, client) -> None:
        save(
            [
                _make_record("a", "d1", status="new"),
                _make_record("b", "d2", status="dismissed",
                              dismissed_reason="x"),
            ]
        )
        resp = client.get("/api/intent-suggestions?status=new")
        data = resp.get_json()
        assert len(data["entries"]) == 1
        assert data["entries"][0]["proposed_id"] == "a"

    def test_invalid_status_filter_returns_400(self, client) -> None:
        resp = client.get("/api/intent-suggestions?status=garbage")
        assert resp.status_code == 400


# ───────────── POST mark-reviewing / dismiss / accept ─────────────


class TestMarkReviewing:
    def test_new_to_reviewing(self, client) -> None:
        save([_make_record(status="new")])
        sid = compute_id("frantic_typing", "subject types furiously")
        resp = client.post(
            f"/api/intent-suggestions/{sid}/mark-reviewing"
        )
        assert resp.status_code == 200
        assert resp.get_json()["record"]["status"] == "reviewing"

    def test_invalid_transition_returns_409(self, client) -> None:
        save([_make_record(status="dismissed", dismissed_reason="x")])
        sid = compute_id("frantic_typing", "subject types furiously")
        resp = client.post(
            f"/api/intent-suggestions/{sid}/mark-reviewing"
        )
        assert resp.status_code == 409

    def test_missing_id_returns_404(self, client) -> None:
        resp = client.post(
            "/api/intent-suggestions/nonexistent/mark-reviewing"
        )
        assert resp.status_code == 404


class TestDismiss:
    def test_with_reason_succeeds(self, client) -> None:
        save([_make_record(status="new")])
        sid = compute_id("frantic_typing", "subject types furiously")
        resp = client.post(
            f"/api/intent-suggestions/{sid}/dismiss",
            json={"reason": "too niche"},
        )
        assert resp.status_code == 200
        rec = resp.get_json()["record"]
        assert rec["status"] == "dismissed"
        assert rec["dismissed_reason"] == "too niche"

    def test_empty_reason_returns_400(self, client) -> None:
        save([_make_record(status="new")])
        sid = compute_id("frantic_typing", "subject types furiously")
        resp = client.post(
            f"/api/intent-suggestions/{sid}/dismiss",
            json={"reason": ""},
        )
        assert resp.status_code == 400

    def test_missing_reason_returns_400(self, client) -> None:
        save([_make_record(status="new")])
        sid = compute_id("frantic_typing", "subject types furiously")
        resp = client.post(
            f"/api/intent-suggestions/{sid}/dismiss",
            json={},
        )
        assert resp.status_code == 400


class TestAccept:
    def test_returns_yaml_snippet(self, client) -> None:
        save([_make_record(status="new")])
        sid = compute_id("frantic_typing", "subject types furiously")
        resp = client.post(f"/api/intent-suggestions/{sid}/accept")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["record"]["status"] == "accepted"
        assert "id: frantic_typing" in data["yaml_snippet"]
        assert "TODO" in data["yaml_snippet"]

    def test_invalid_transition_dismissed_to_accepted(self, client) -> None:
        save([_make_record(status="dismissed", dismissed_reason="x")])
        sid = compute_id("frantic_typing", "subject types furiously")
        resp = client.post(f"/api/intent-suggestions/{sid}/accept")
        assert resp.status_code == 409

    def test_missing_id_returns_404(self, client) -> None:
        resp = client.post("/api/intent-suggestions/nope/accept")
        assert resp.status_code == 404


class TestGetYaml:
    def test_returns_yaml_for_existing(self, client) -> None:
        save([_make_record(status="accepted")])
        sid = compute_id("frantic_typing", "subject types furiously")
        resp = client.get(f"/api/intent-suggestions/{sid}/yaml")
        assert resp.status_code == 200
        assert "text/yaml" in resp.headers.get("Content-Type", "")
        body = resp.get_data(as_text=True)
        assert "id: frantic_typing" in body

    def test_missing_id_returns_404(self, client) -> None:
        resp = client.get("/api/intent-suggestions/nope/yaml")
        assert resp.status_code == 404


# ───────────── merged 自動検出 ─────────────


class TestMergedAutoDetection:
    def test_accepted_becomes_merged_when_yaml_has_id(
        self, client, monkeypatch
    ) -> None:
        save([_make_record(proposed_id="talking_head_calm",
                           description="d",
                           status="accepted")])
        # talking_head_calm は既存 visual_intents.yaml にあるので、GET 一覧で
        # accepted → merged に遅延更新されるはず
        resp = client.get("/api/intent-suggestions")
        data = resp.get_json()
        statuses = {e["proposed_id"]: e["status"] for e in data["entries"]}
        assert statuses["talking_head_calm"] == "merged"

    def test_unknown_id_stays_accepted(self, client) -> None:
        save([_make_record(proposed_id="not_in_yaml_at_all",
                           description="d",
                           status="accepted")])
        resp = client.get("/api/intent-suggestions")
        data = resp.get_json()
        statuses = {e["proposed_id"]: e["status"] for e in data["entries"]}
        assert statuses["not_in_yaml_at_all"] == "accepted"

    def test_yaml_lookup_failure_does_not_crash(
        self, client, monkeypatch
    ) -> None:
        # part_registry_loader を import 失敗させる ImportError 経路
        from routes import intent_suggestions as iroute

        def _broken(*args, **kwargs):
            raise OSError("boom")

        monkeypatch.setattr(
            "part_registry_loader.load_registry", _broken
        )
        save([_make_record(status="accepted")])
        resp = client.get("/api/intent-suggestions")
        # yaml 取得失敗でも 200 で entry を返す (= merged 化はスキップ)
        assert resp.status_code == 200
        # _refresh_merged が 0 を返すこと自体は副次的検証
        assert iroute._refresh_merged() == 0
