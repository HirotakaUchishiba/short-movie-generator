"""Phase 0: reject API + regenerate 暗黙アーカイブのテスト。

reject は記録のみ (= progress に副作用なし) の設計を契約として固定する。
regenerate_implicit は _archive_before_regen の単体テストでカバーする
(= /regen 経由のテストは実 stage runner を呼ぶので別レイヤ)。
"""
import json
import os

import pytest

import preview_server
import staged_pipeline


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()

    from qa import recorder as _recorder
    archive_root = tmp_path / "qa_failures"
    monkeypatch.setattr(
        _recorder, "qa_failures_root", lambda: str(archive_root),
    )
    return _db, str(archive_root)


@pytest.fixture
def project(tmp_path, monkeypatch, isolated_env):
    sp_dir = tmp_path / "screenplays"
    sp_dir.mkdir()
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    monkeypatch.setattr(preview_server.config, "SCREENPLAYS_DIR", str(sp_dir))
    monkeypatch.setattr(preview_server.config, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(preview_server, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(staged_pipeline.config, "SCREENPLAYS_DIR", str(sp_dir))

    name = "test_reject_screenplay"
    sp = {
        "caption": "x",
        "scenes": [
            {
                "duration": 5,
                "lines": [
                    {"text": "line A", "start": 0, "end": 1.0},
                    {"text": "line B", "start": 1, "end": 2.0},
                ],
            },
        ],
    }
    with open(sp_dir / f"{name}.json", "w") as f:
        json.dump(sp, f, ensure_ascii=False)

    ts = "20260507_180000"
    ts_dir = temp_dir / ts
    ts_dir.mkdir()
    with open(ts_dir / "metadata.json", "w") as f:
        json.dump({
            "screenplay_name": f"{name}.json",
            "screenplay_path": "screenplay.json",
        }, f)
    with open(ts_dir / "screenplay.json", "w") as f:
        json.dump(sp, f, ensure_ascii=False)
    return {"ts": ts, "name": name, "ts_dir": str(ts_dir)}


@pytest.fixture
def client():
    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


def _make_artifact(ts_dir: str, name: str) -> str:
    p = os.path.join(ts_dir, name)
    with open(p, "wb") as f:
        f.write(b"fake artifact bytes")
    return p


# ─── reject API ──────────────────────────────────────────


def test_reject_human_records_failure(client, project, isolated_env):
    db, archive_root = isolated_env
    art_path = _make_artifact(project["ts_dir"], "bg_0.png")

    r = client.post(
        f"/api/projects/{project['ts']}/reject",
        json={
            "stage": "bg",
            "scene_idx": 0,
            "tags": ["character_drift"],
            "note": "顔が崩れた",
        },
    )
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["ok"] is True
    assert body["failure_id"] > 0
    assert body["archive_dir"].startswith(archive_root)
    # artifact がコピーされている
    assert os.path.exists(os.path.join(body["archive_dir"], "bg_0.png"))
    # snapshot もコピーされる
    assert os.path.exists(os.path.join(body["archive_dir"], "screenplay.json"))

    rows = db.list_qa_failures(ts=project["ts"])
    assert len(rows) == 1
    assert rows[0]["source"] == "human_reject"
    assert rows[0]["tags"] == ["character_drift"]
    assert rows[0]["scene_idx"] == 0
    assert rows[0]["note"] == "顔が崩れた"


def test_reject_invalid_stage(client, project):
    r = client.post(
        f"/api/projects/{project['ts']}/reject",
        json={"stage": "invalid_stage", "tags": []},
    )
    assert r.status_code == 400


def test_reject_invalid_tag(client, project):
    r = client.post(
        f"/api/projects/{project['ts']}/reject",
        json={"stage": "bg", "tags": ["nonexistent_tag"]},
    )
    assert r.status_code == 400


def test_reject_invalid_scene_idx_type(client, project):
    r = client.post(
        f"/api/projects/{project['ts']}/reject",
        json={"stage": "bg", "tags": [], "scene_idx": "abc"},
    )
    assert r.status_code == 400


def test_reject_unknown_project(client):
    r = client.post(
        "/api/projects/99999999_999999/reject",
        json={"stage": "bg", "tags": []},
    )
    assert r.status_code == 404


def test_reject_does_not_affect_progress(client, project, isolated_env):
    """reject は progress (generated_at / approved_at) を触らない。"""
    import progress_store
    progress_store.mark_generated(project["ts_dir"], "bg")
    progress_store.mark_approved(project["ts_dir"], "bg")
    before_approved = progress_store.is_approved(project["ts_dir"], "bg")

    r = client.post(
        f"/api/projects/{project['ts']}/reject",
        json={"stage": "bg", "scene_idx": 0,
              "tags": ["character_drift"]},
    )
    assert r.status_code == 200

    after_approved = progress_store.is_approved(project["ts_dir"], "bg")
    assert before_approved == after_approved is True


def test_reject_works_without_artifact(client, project, isolated_env):
    """artifact が無いケース (= overlay 未生成段階の reject) でも記録は通る。"""
    db, _ = isolated_env
    r = client.post(
        f"/api/projects/{project['ts']}/reject",
        json={"stage": "overlay", "tags": ["subtitle_too_long"]},
    )
    assert r.status_code == 200
    rows = db.list_qa_failures(ts=project["ts"])
    assert len(rows) == 1
    assert rows[0]["artifact_path"] is None


def test_reject_invalid_note_type(client, project):
    """note は string 以外 (例: dict) を 400 で reject する。"""
    r = client.post(
        f"/api/projects/{project['ts']}/reject",
        json={"stage": "bg", "tags": [], "note": {"x": 1}},
    )
    assert r.status_code == 400


def test_reject_note_too_long(client, project):
    """note が _REJECT_NOTE_MAX_LENGTH (2000) を超えると 400。"""
    r = client.post(
        f"/api/projects/{project['ts']}/reject",
        json={"stage": "bg", "tags": [], "note": "あ" * 2001},
    )
    assert r.status_code == 400
    body = r.get_json()
    assert "2000" in body["error"]


def test_reject_note_at_limit_accepted(client, project):
    """ちょうど上限ぴったりの note は通る (= boundary の inclusivity)。"""
    r = client.post(
        f"/api/projects/{project['ts']}/reject",
        json={"stage": "bg", "tags": ["character_drift"],
              "note": "x" * 2000},
    )
    assert r.status_code == 200


# ─── /api/config/qa-tags (SSOT 配信) ──────────────────────────────────


def test_qa_tags_endpoint_returns_backend_ssot(client):
    """frontend がここから取得することで `qa/categories.py` を SSOT にできる。
    形式: tags=[{tag,label,axis}], axis_labels={axis: 表示名}。"""
    r = client.get("/api/config/qa-tags")
    assert r.status_code == 200
    body = r.get_json()
    assert "tags" in body and "axis_labels" in body
    # 既知タグが含まれている (= drift 検査の代わり)
    tags_set = {d["tag"] for d in body["tags"]}
    assert "character_drift" in tags_set
    assert "audio_silence" in tags_set
    assert "lipsync_mouth_off" in tags_set
    # 各タグが tag/label/axis を持つ
    for d in body["tags"]:
        assert set(d.keys()) >= {"tag", "label", "axis"}
        assert isinstance(d["label"], str) and d["label"]
    # axis_labels に 5 軸が揃っている
    assert {"visual", "audio", "lipsync", "subtitle", "story"} <= set(
        body["axis_labels"].keys(),
    )


# ─── _archive_before_regen ──────────────────────────────────────────


def test_archive_before_regen_records_when_artifact_exists(project, isolated_env):
    db, _ = isolated_env
    _make_artifact(project["ts_dir"], "kling_0.mp4")

    preview_server._archive_before_regen(
        project["ts"], "kling", scene_idx=0, line_idx=None,
    )
    rows = db.list_qa_failures(ts=project["ts"])
    assert len(rows) == 1
    assert rows[0]["source"] == "regenerate_implicit"
    assert rows[0]["stage"] == "kling"
    assert rows[0]["scene_idx"] == 0
    # tags は空のはず
    assert rows[0]["tags"] == []


def test_archive_before_regen_skips_when_no_artifact(project, isolated_env):
    """artifact が 1 つも存在しないなら何も記録しない (= 初回生成時)。"""
    db, _ = isolated_env
    preview_server._archive_before_regen(
        project["ts"], "kling", scene_idx=5, line_idx=None,
    )
    rows = db.list_qa_failures(ts=project["ts"])
    assert rows == []


# ─── _stage_artifact_paths の対称性 ──────────────────────────────────────────


def test_artifact_paths_tts_full_includes_full_and_per_line(project):
    """tts 全体 reject (scene_idx / line_idx 共に None) では tts_full.mp3 と
    全 per-line を archive 対象に含める (= 全 audio を残す)。"""
    _make_artifact(project["ts_dir"], "tts_full.mp3")
    _make_artifact(project["ts_dir"], "tts_0_0.mp3")
    _make_artifact(project["ts_dir"], "tts_0_1.mp3")
    paths = preview_server._stage_artifact_paths(
        project["ts_dir"], "tts", scene_idx=None, line_idx=None,
    )
    basenames = {os.path.basename(p) for p in paths}
    assert "tts_full.mp3" in basenames
    assert "tts_0_0.mp3" in basenames
    assert "tts_0_1.mp3" in basenames


def test_artifact_paths_tts_scene_only(project):
    """tts で scene_idx だけ指定すると、その scene の全 line を返す。"""
    _make_artifact(project["ts_dir"], "tts_2_0.mp3")
    _make_artifact(project["ts_dir"], "tts_2_1.mp3")
    _make_artifact(project["ts_dir"], "tts_3_0.mp3")  # 別 scene
    paths = preview_server._stage_artifact_paths(
        project["ts_dir"], "tts", scene_idx=2, line_idx=None,
    )
    basenames = {os.path.basename(p) for p in paths}
    assert basenames == {"tts_2_0.mp3", "tts_2_1.mp3"}


def test_artifact_paths_script_returns_empty(project):
    """script stage は snapshot 経由で別途コピーされるので artifact list は空。"""
    paths = preview_server._stage_artifact_paths(
        project["ts_dir"], "script", scene_idx=None, line_idx=None,
    )
    assert paths == []
