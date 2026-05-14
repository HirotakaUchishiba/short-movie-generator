"""Stage 4 Kling cache 関連 API の単体テスト。

scan-cache / decisions / use-cache / queue-fresh / decisions/bulk /
generate-remaining / kling-cache entries / preview.mp4 / blacklist。
"""
import json
import time
from pathlib import Path

import pytest

import config
import kling_cache
import preview_server
import progress_store
import scene_gen
import staged_pipeline


@pytest.fixture
def project(tmp_path, monkeypatch):
    sp_dir = tmp_path / "screenplays"
    sp_dir.mkdir()
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    monkeypatch.setattr(preview_server.config, "SCREENPLAYS_DIR", str(sp_dir))
    monkeypatch.setattr(preview_server.config, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(preview_server, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(staged_pipeline.config, "SCREENPLAYS_DIR", str(sp_dir))

    # cache を test 用に隔離
    monkeypatch.setattr(
        config, "KLING_CACHE_DIR", str(tmp_path / "kling_cache"))
    monkeypatch.setattr(config, "KLING_CACHE_ENABLED", True)
    monkeypatch.setattr(config, "KLING_CACHE_AUTO_PRUNE", False)
    monkeypatch.setattr(config, "KLING_CACHE_REQUIRE_APPROVAL", False)
    monkeypatch.setattr(config, "KLING_CACHE_MISMATCH_THRESHOLD", 0.30)

    name = "test_kling_screenplay"
    sp = {
        "caption": "x",
        "scenes": [
            {
                "duration": 4.5,
                "background_prompt": "bg one",
                "animation_prompt": "subject A walks",
                "camera_distance": "medium-close",
                "location_ref": "home_office",
                "lines": [
                    {"text": "やった", "start": 0.0, "end": 1.0, "emotion": "喜び"},
                ],
            },
            {
                "duration": 4.0,
                "background_prompt": "bg two",
                "animation_prompt": "subject A sits",
                "camera_distance": "medium-close",
                "location_ref": "home_office",
                "lines": [
                    {"text": "ふぅ", "start": 0.0, "end": 1.0, "emotion": "中立"},
                ],
            },
        ],
    }
    with open(sp_dir / f"{name}.json", "w") as f:
        json.dump(sp, f, ensure_ascii=False)

    ts = "20260507_120000"
    ts_dir = temp_dir / ts
    ts_dir.mkdir()
    with open(ts_dir / "metadata.json", "w") as f:
        json.dump({
            "screenplay_name": f"{name}.json",
            "screenplay_template_name": f"{name}.json",
            "screenplay_path": "screenplay.json",
        }, f)
    with open(ts_dir / "screenplay.json", "w") as f:
        json.dump(sp, f, ensure_ascii=False)
    # bg を 2 枚作っておく (= scan が動く前提)
    (ts_dir / "bg_000.png").write_bytes(b"bg-content-A")
    (ts_dir / "bg_001.png").write_bytes(b"bg-content-B")
    return {"ts": ts, "name": name, "sp_path": str(ts_dir / "screenplay.json"),
            "ts_dir": str(ts_dir)}


@pytest.fixture
def client():
    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


@pytest.fixture
def stub_pipeline(monkeypatch):
    """trim / FAL を mock。"""
    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 5.0)

    def _fake_trim(src, dur, dst):
        Path(dst).write_bytes(Path(src).read_bytes())
    monkeypatch.setattr(scene_gen, "_trim_video", _fake_trim)

    fal_calls: list[dict] = []

    def _fake_generate_kling(bg_path, anim, duration, out, idx):
        Path(out).write_bytes(b"fresh-fal-bytes")
        fal_calls.append({"scene_idx": idx})
    monkeypatch.setattr(scene_gen, "_generate_kling", _fake_generate_kling)
    return fal_calls


# ─── scan-cache + decisions ─────────────────────────────


def test_scan_cache_initial(client, project, stub_pipeline):
    r = client.post(
        f"/api/projects/{project['ts']}/stages/kling/scan-cache")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    decisions = body["scene_decisions"]
    # 候補なしなので両シーンとも fresh で確定
    assert decisions["0"]["decision"] == "fresh"
    assert decisions["1"]["decision"] == "fresh"
    assert decisions["0"]["candidates"] == []


def test_decisions_get_returns_state(client, project, stub_pipeline):
    client.post(f"/api/projects/{project['ts']}/stages/kling/scan-cache")
    r = client.get(f"/api/projects/{project['ts']}/stages/kling/decisions")
    assert r.status_code == 200
    body = r.get_json()
    assert "scene_decisions" in body
    assert body["cache_scanned_at"]


def test_scan_finds_existing_cache_entry(client, project, stub_pipeline):
    """既存 cache に同 key の entry を仕込んでから scan → 候補が返る。"""
    # scene 0 用の cache key を計算 → store
    sp = staged_pipeline.load_project_screenplay(project["ts_dir"])
    inputs = scene_gen._scene_kling_inputs(
        0, sp["scenes"][0], sp, project["ts_dir"])
    src = Path(project["ts_dir"]) / "_seed.mp4"
    src.write_bytes(b"seeded-cache")
    kling_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_kling_cache_meta(sp["scenes"][0], inputs))

    r = client.post(
        f"/api/projects/{project['ts']}/stages/kling/scan-cache")
    body = r.get_json()
    assert body["scene_decisions"]["0"]["candidates"]
    assert body["scene_decisions"]["0"]["decision"] == "pending"
    # scene 1 は候補なし → fresh 確定
    assert body["scene_decisions"]["1"]["decision"] == "fresh"


# ─── use-cache ─────────────────────────────────────────


def test_use_cache_copies_and_records(client, project, stub_pipeline):
    sp = staged_pipeline.load_project_screenplay(project["ts_dir"])
    inputs = scene_gen._scene_kling_inputs(
        0, sp["scenes"][0], sp, project["ts_dir"])
    src = Path(project["ts_dir"]) / "_seed.mp4"
    src.write_bytes(b"cache-bytes")
    kling_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_kling_cache_meta(sp["scenes"][0], inputs))

    client.post(f"/api/projects/{project['ts']}/stages/kling/scan-cache")
    r = client.post(
        f"/api/projects/{project['ts']}/stages/kling/scenes/0/use-cache",
        json={"key": inputs["cache_key"]})
    assert r.status_code == 200, r.get_json()
    # raw mp4 + trim 出来ている
    assert Path(project["ts_dir"], "kling_000.mp4").exists()
    assert Path(project["ts_dir"], "scene_000.trim.mp4").exists()
    # decisions が cache に切替わった
    decisions = progress_store.get_kling_decisions(project["ts_dir"])
    assert decisions["scene_decisions"]["0"]["decision"] == "cache"
    assert decisions["scene_decisions"]["0"]["decided_key"] == inputs["cache_key"]


def test_use_cache_missing_key_returns_400(client, project, stub_pipeline):
    r = client.post(
        f"/api/projects/{project['ts']}/stages/kling/scenes/0/use-cache",
        json={})
    assert r.status_code == 400


def test_use_cache_unknown_key_returns_404(client, project, stub_pipeline):
    r = client.post(
        f"/api/projects/{project['ts']}/stages/kling/scenes/0/use-cache",
        json={"key": "0000000000000000"})
    assert r.status_code == 404


# ─── queue-fresh ───────────────────────────────────────


def test_queue_fresh_marks_scene_decision(client, project, stub_pipeline):
    client.post(f"/api/projects/{project['ts']}/stages/kling/scan-cache")
    r = client.post(
        f"/api/projects/{project['ts']}/stages/kling/scenes/0/queue-fresh")
    assert r.status_code == 200
    decisions = progress_store.get_kling_decisions(project["ts_dir"])
    assert decisions["scene_decisions"]["0"]["decision"] == "fresh"


# ─── decisions/bulk ───────────────────────────────────


def test_bulk_all_cache_adopts_candidates(client, project, stub_pipeline):
    sp = staged_pipeline.load_project_screenplay(project["ts_dir"])
    inputs = scene_gen._scene_kling_inputs(
        0, sp["scenes"][0], sp, project["ts_dir"])
    src = Path(project["ts_dir"]) / "_seed.mp4"
    src.write_bytes(b"bulk-cache")
    kling_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_kling_cache_meta(sp["scenes"][0], inputs))
    client.post(f"/api/projects/{project['ts']}/stages/kling/scan-cache")

    r = client.post(
        f"/api/projects/{project['ts']}/stages/kling/decisions/bulk",
        json={"action": "all-cache"})
    assert r.status_code == 200
    body = r.get_json()
    # scene 0 は cache、scene 1 は候補なしなので fresh queue
    assert body["scene_decisions"]["0"]["decision"] == "cache"
    assert body["scene_decisions"]["1"]["decision"] == "fresh"
    assert body["summary"]["adopted"] == 1
    # cache 採用済みの raw mp4 が出来ている
    assert Path(project["ts_dir"], "kling_000.mp4").read_bytes() == b"bulk-cache"


def test_bulk_all_fresh_clears_files(client, project, stub_pipeline):
    # 既に kling_000.mp4 が存在する状態を作る
    Path(project["ts_dir"], "kling_000.mp4").write_bytes(b"old")
    client.post(f"/api/projects/{project['ts']}/stages/kling/scan-cache")
    r = client.post(
        f"/api/projects/{project['ts']}/stages/kling/decisions/bulk",
        json={"action": "all-fresh"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["scene_decisions"]["0"]["decision"] == "fresh"
    assert body["scene_decisions"]["1"]["decision"] == "fresh"
    # 既存 mp4 はクリアされた
    assert not Path(project["ts_dir"], "kling_000.mp4").exists()


def test_bulk_invalid_action_400(client, project, stub_pipeline):
    r = client.post(
        f"/api/projects/{project['ts']}/stages/kling/decisions/bulk",
        json={"action": "weird"})
    assert r.status_code == 400


# ─── generate-remaining ────────────────────────────────


def test_generate_remaining_blocks_when_pending(
        client, project, stub_pipeline):
    sp = staged_pipeline.load_project_screenplay(project["ts_dir"])
    inputs = scene_gen._scene_kling_inputs(
        0, sp["scenes"][0], sp, project["ts_dir"])
    src = Path(project["ts_dir"]) / "_seed.mp4"
    src.write_bytes(b"x")
    kling_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_kling_cache_meta(sp["scenes"][0], inputs))
    # scan の結果、scene 0 は pending、scene 1 は fresh 確定
    client.post(f"/api/projects/{project['ts']}/stages/kling/scan-cache")
    r = client.post(
        f"/api/projects/{project['ts']}/stages/kling/generate-remaining")
    assert r.status_code == 400
    body = r.get_json()
    assert "pending_scenes" in body
    assert body["pending_scenes"] == [0]


def test_generate_remaining_runs_only_fresh(client, project, stub_pipeline):
    # 全シーンを fresh に
    client.post(f"/api/projects/{project['ts']}/stages/kling/scan-cache")
    client.post(
        f"/api/projects/{project['ts']}/stages/kling/decisions/bulk",
        json={"action": "all-fresh"})
    r = client.post(
        f"/api/projects/{project['ts']}/stages/kling/generate-remaining")
    assert r.status_code == 200
    body = r.get_json()
    assert body["fresh_scenes"] == [0, 1]
    # job の完了を待つ (= バックグラウンド実行)
    job_id = body["job_id"]
    for _ in range(50):
        j = client.get(f"/api/jobs/{job_id}").get_json()
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "completed", j
    # FAL が 2 回呼ばれた
    assert len(stub_pipeline) == 2
    # progress が generated 状態
    assert progress_store.is_generated(project["ts_dir"], "kling")


# ─── kling-cache entries / blacklist / preview ──


def test_cache_entries_and_blacklist(client, project, stub_pipeline):
    src = Path(project["ts_dir"]) / "_seed.mp4"
    src.write_bytes(b"abc")
    sp = staged_pipeline.load_project_screenplay(project["ts_dir"])
    inputs = scene_gen._scene_kling_inputs(
        0, sp["scenes"][0], sp, project["ts_dir"])
    kling_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_kling_cache_meta(sp["scenes"][0], inputs))

    r = client.get("/api/kling-cache/entries")
    assert r.status_code == 200
    entries = r.get_json()["entries"]
    assert any(e["key"] == inputs["cache_key"] for e in entries)

    r = client.post(
        f"/api/kling-cache/{inputs['cache_key']}/blacklist",
        json={"reason": "宇宙が崩壊"})
    assert r.status_code == 200
    meta = kling_cache.load_meta(inputs["cache_key"])
    assert meta["quality"]["blacklisted"] is True
    assert meta["quality"]["blacklist_reason"] == "宇宙が崩壊"


def test_cache_preview_serves_mp4(client, project, stub_pipeline):
    src = Path(project["ts_dir"]) / "_seed.mp4"
    src.write_bytes(b"video-bytes")
    sp = staged_pipeline.load_project_screenplay(project["ts_dir"])
    inputs = scene_gen._scene_kling_inputs(
        0, sp["scenes"][0], sp, project["ts_dir"])
    kling_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_kling_cache_meta(sp["scenes"][0], inputs))

    r = client.get(f"/api/kling-cache/{inputs['cache_key']}/preview.mp4")
    assert r.status_code == 200
    assert r.data == b"video-bytes"


def test_cache_preview_invalid_key_400(client):
    r = client.get("/api/kling-cache/notavalidhash/preview.mp4")
    assert r.status_code == 400


def test_cache_blacklist_invalid_key_400(client):
    r = client.post(
        "/api/kling-cache/notavalidhash/blacklist", json={"reason": "x"})
    assert r.status_code == 400


def test_cache_delete_removes_entry(client, project, stub_pipeline):
    src = Path(project["ts_dir"]) / "_seed.mp4"
    src.write_bytes(b"delete-me")
    sp = staged_pipeline.load_project_screenplay(project["ts_dir"])
    inputs = scene_gen._scene_kling_inputs(
        0, sp["scenes"][0], sp, project["ts_dir"])
    kling_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_kling_cache_meta(sp["scenes"][0], inputs))

    r = client.delete(f"/api/kling-cache/{inputs['cache_key']}")
    assert r.status_code == 200
    assert kling_cache.lookup(inputs["cache_key"]) is None


def test_cache_delete_returns_404_when_entry_missing(client, project,
                                                     stub_pipeline):
    """有効な hash16 形式 + cache に存在しない key は 404 を返す
    (= `_stage_cache_delete` の `if not is_deleted` 経路への regression test)。"""
    # 有効形式 (16 hex chars) だが store されていない key
    nonexistent = "0" * 16
    assert kling_cache.lookup(nonexistent) is None
    r = client.delete(f"/api/kling-cache/{nonexistent}")
    assert r.status_code == 404
    body = r.get_json()
    assert "not found" in (body.get("error") or "").lower()
