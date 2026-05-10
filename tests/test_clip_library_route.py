"""``/api/clips/*`` の統合テスト。

設計 doc: docs/plannings/2026-05-10_compositional-architecture.md §3
"""

from __future__ import annotations

from pathlib import Path

import pytest

import clip_library


@pytest.fixture
def isolated_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "clips"
    root.mkdir()
    monkeypatch.setattr("config.CLIP_LIBRARY_DIR", str(root))
    monkeypatch.setattr("config.CLIP_LIBRARY_ENABLED", True)
    monkeypatch.setattr("config.CLIP_POOL_AUTO_APPROVE", True)
    return root


@pytest.fixture
def client(isolated_root):
    import preview_server

    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


def _make_entry() -> clip_library.ClipEntry:
    return clip_library.register_clip_entry(
        identity=clip_library.ClipIdentity(
            ("f1__office",), "home_office", "中立"
        ),
        annotation=clip_library.ClipAnnotation(
            visual_intent_id="talking_head_calm"
        ),
        provenance=clip_library.ClipProvenance(),
        bg_src=None,
        kling_src=None,
        auto_approve=True,
    )


class TestListClips:
    def test_empty_returns_no_entries(self, client) -> None:
        resp = client.get("/api/clips")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "entries" in data
        assert data["entries"] == []
        assert data["enabled"] is True

    def test_returns_registered_entries(self, client) -> None:
        e = _make_entry()
        resp = client.get("/api/clips")
        data = resp.get_json()
        assert len(data["entries"]) == 1
        assert data["entries"][0]["id"] == e.id
        assert data["entries"][0]["lifecycle"]["status"] == "active"

    def test_status_filter(self, client) -> None:
        # active を 1 つ、pending を 1 つ register
        a = _make_entry()
        p = clip_library.register_clip_entry(
            identity=clip_library.ClipIdentity(
                ("m1",), "park", "中立"
            ),
            annotation=clip_library.ClipAnnotation(),
            provenance=clip_library.ClipProvenance(),
            bg_src=None,
            kling_src=None,
            auto_approve=False,
        )

        active_resp = client.get("/api/clips?status=active")
        active_ids = {e["id"] for e in active_resp.get_json()["entries"]}
        assert a.id in active_ids
        assert p.id not in active_ids

        pending_resp = client.get("/api/clips?status=pending_review")
        pending_ids = {e["id"] for e in pending_resp.get_json()["entries"]}
        assert p.id in pending_ids
        assert a.id not in pending_ids


class TestEntryOps:
    def test_get_existing_entry(self, client) -> None:
        e = _make_entry()
        resp = client.get(f"/api/clips/{e.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["entry"]["id"] == e.id

    def test_get_unknown_entry_returns_404(self, client) -> None:
        resp = client.get("/api/clips/nonexistent_id")
        assert resp.status_code == 404

    def test_approve_promotes_pending(self, client) -> None:
        p = clip_library.register_clip_entry(
            identity=clip_library.ClipIdentity(("m1",), "park", "中立"),
            annotation=clip_library.ClipAnnotation(),
            provenance=clip_library.ClipProvenance(),
            bg_src=None,
            kling_src=None,
            auto_approve=False,
        )
        resp = client.post(f"/api/clips/{p.id}/approve")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["entry"]["lifecycle"]["status"] == "active"

    def test_blacklist_marks_as_blacklisted(self, client) -> None:
        e = _make_entry()
        resp = client.post(
            f"/api/clips/{e.id}/blacklist",
            json={"reason": "見た目が崩れている"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["entry"]["lifecycle"]["status"] == "blacklisted"
        assert data["entry"]["lifecycle"]["blacklist_reason"] == "見た目が崩れている"


class TestProjectClipStatus:
    """指定 project の各 scene が clip_library hit するかを判定する endpoint。"""

    def _setup_project(
        self, tmp_path: Path, scenes: list[dict],
        monkeypatch: pytest.MonkeyPatch,
    ) -> str:
        """temp/<TS>/screenplay.json + metadata.json を直接書く。

        PR #157 (Phase A) で routes の clip-library-status が compose 経由
        (= load_screenplay_for_project) に統一されたため、abstract に
        featured_characters / speaker_to_ref が無いと character_refs が
        compose で空配列に上書きされる (= scene_has_identity が False になる)。

        テスト fixture では各 scene の `character_refs` を抽出して
        `featured_characters` に展開し、compose の `_resolve_scene_characters`
        の fallback (= 全 available_ids) 経路で character_refs が再現される
        ようにする。これで「テストの意図 (= scene が identity を持っている)」と
        compose 派生結果が整合する。
        """

        import json

        sp_dir = tmp_path / "screenplays"
        sp_dir.mkdir(parents=True)
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir(parents=True)
        monkeypatch.setattr("config.SCREENPLAYS_DIR", str(sp_dir))
        monkeypatch.setattr("config.TEMP_DIR", str(temp_dir))

        # 各 scene の character_refs を集約して featured_characters に展開
        # (= compose の _resolve_scene_characters fallback で character_refs を
        # 再現させる)。speaker_to_ref は test 範囲外なので空。
        all_chars: list[str] = []
        seen: set[str] = set()
        for s in scenes:
            for c in s.get("character_refs") or []:
                if c not in seen:
                    seen.add(c)
                    all_chars.append(c)

        ts = "20260510_120000"
        ts_path = temp_dir / ts
        ts_path.mkdir()
        screenplay: dict = {"caption": "x", "scenes": scenes}
        if all_chars:
            screenplay["featured_characters"] = all_chars
        (ts_path / "screenplay.json").write_text(
            json.dumps(screenplay, ensure_ascii=False),
            encoding="utf-8",
        )
        (ts_path / "metadata.json").write_text(
            json.dumps(
                {"screenplay_template_name": "test.json", "screenplay_sha": "x"},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return ts

    def test_scene_with_no_identity_reports_false(
        self, isolated_root: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, client,
    ) -> None:
        ts = self._setup_project(
            tmp_path,
            [
                {
                    "duration": 2.0,
                    "background_prompt": "x",
                    "lines": [
                        {"text": "a", "start": 0, "end": 1, "emotion": "中立"}
                    ],
                }
            ],
            monkeypatch,
        )
        resp = client.get(f"/api/projects/{ts}/clip-library-status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["enabled"] is True
        assert len(data["scenes"]) == 1
        assert data["scenes"][0]["has_identity"] is False
        assert data["scenes"][0]["satisfied"] is False

    def test_scene_with_identity_reports_satisfied_when_pool_hits(
        self, isolated_root: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, client,
    ) -> None:
        # library に entry を入れておく
        e = _make_entry()
        ts = self._setup_project(
            tmp_path,
            [
                {
                    "duration": 2.0,
                    "background_prompt": "x",
                    "character_refs": ["f1__office"],
                    "location_ref": "home_office",
                    "start_emotion": "中立",
                    "lines": [
                        {"text": "a", "start": 0, "end": 1, "emotion": "中立"}
                    ],
                }
            ],
            monkeypatch,
        )
        resp = client.get(f"/api/projects/{ts}/clip-library-status")
        data = resp.get_json()
        scene_status = data["scenes"][0]
        assert scene_status["has_identity"] is True
        assert scene_status["satisfied"] is True
        assert scene_status["entry_id"] == e.id
        assert scene_status["pool_size"] == 1
