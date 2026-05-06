"""Stage 3 BG cache 関連 API の単体テスト。

scan-cache / decisions / use-cache / queue-fresh / decisions/bulk /
generate-remaining / bg-cache entries / preview.png / blacklist。
kling 側 (test_preview_server_kling_cache.py) と対称。
"""
import json
import time
from pathlib import Path

import pytest

import bg_cache
import config
import preview_server
import progress_store
import scene_gen
import staged_pipeline


@pytest.fixture
def isolated_assets(tmp_path, monkeypatch):
    chars = tmp_path / "characters"
    locs = tmp_path / "locations"
    chars.mkdir()
    locs.mkdir()
    from analyze import character_meta as cmeta_mod
    from analyze import location as loc_mod
    monkeypatch.setattr(cmeta_mod, "CHARACTERS_DIR", chars)
    monkeypatch.setattr(loc_mod, "LOCATIONS_DIR", locs)
    base = chars / "f1"
    base.mkdir()
    (base / "office.png").write_bytes(b"img-f1-office")
    cmeta_mod.save_character_meta(cmeta_mod.CharacterMeta(id="f1"))
    loc_mod.save_location(loc_mod.Location(
        id="home_office", decor="scandi", camera_distance="medium-close",
    ))
    loc_mod.save_location(loc_mod.Location(
        id="cafe_barista", decor="cafe-vintage", camera_distance="medium",
    ))
    return {"chars": chars, "locs": locs}


@pytest.fixture
def project(tmp_path, monkeypatch, isolated_assets):
    sp_dir = tmp_path / "screenplays"
    sp_dir.mkdir()
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    monkeypatch.setattr(preview_server.config, "SCREENPLAYS_DIR", str(sp_dir))
    monkeypatch.setattr(preview_server.config, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(preview_server, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(staged_pipeline.config, "SCREENPLAYS_DIR", str(sp_dir))

    monkeypatch.setattr(
        config, "BG_CACHE_DIR", str(tmp_path / "bg_cache"))
    monkeypatch.setattr(config, "BG_CACHE_ENABLED", True)
    monkeypatch.setattr(config, "BG_CACHE_REQUIRE_APPROVAL", False)

    name = "test_bg_screenplay"
    sp = {
        "caption": "x",
        "scenes": [
            {
                "duration": 4.5,
                "background_prompt": "subject A in office, scene zero",
                "animation_prompt": "subject A walks",
                "character_refs": ["f1__office"],
                "characters": [{"name": "f1__office"}],
                "camera_distance": "medium-close",
                "location_ref": "home_office",
                "lines": [{"text": "やった", "start": 0.0, "end": 1.0}],
            },
            {
                "duration": 4.0,
                "background_prompt": "subject A in cafe, scene one",
                "animation_prompt": "subject A sits",
                "character_refs": ["f1__office"],
                "characters": [{"name": "f1__office"}],
                "camera_distance": "medium",
                "location_ref": "cafe_barista",
                "lines": [{"text": "ふぅ", "start": 0.0, "end": 1.0}],
            },
        ],
    }
    with open(sp_dir / f"{name}.json", "w") as f:
        json.dump(sp, f, ensure_ascii=False)

    ts = "20260507_140000"
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
    return {"ts": ts, "name": name, "sp_path": str(ts_dir / "screenplay.json"),
            "ts_dir": str(ts_dir)}


@pytest.fixture
def client():
    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


@pytest.fixture
def stub_imagen(monkeypatch):
    """Imagen 実呼び出しを mock。"""
    calls: list[dict] = []
    def _fake_generate_image(prompt, path, reference_images=None):
        Path(path).write_bytes(b"fresh-png")
        calls.append({"path": path})
    import imagen_client
    monkeypatch.setattr(imagen_client, "generate_image", _fake_generate_image)
    monkeypatch.setattr(scene_gen, "_detect_storyboard_image", lambda p: False)
    return calls


# ─── scan-cache + decisions ─────────────────────


def test_scan_cache_initial(client, project, stub_imagen):
    r = client.post(
        f"/api/projects/{project['ts']}/stages/bg/scan-cache")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    decisions = body["scene_decisions"]
    # 初回 = 候補なし → fresh 確定
    assert decisions["0"]["decision"] == "fresh"
    assert decisions["1"]["decision"] == "fresh"


def test_decisions_get_returns_state(client, project, stub_imagen):
    client.post(f"/api/projects/{project['ts']}/stages/bg/scan-cache")
    r = client.get(f"/api/projects/{project['ts']}/stages/bg/decisions")
    assert r.status_code == 200
    body = r.get_json()
    assert "scene_decisions" in body
    assert body["cache_scanned_at"]


def test_scan_finds_existing_cache_entry(client, project, stub_imagen):
    sp = staged_pipeline.load_project_screenplay(project["ts_dir"])
    inputs = scene_gen._scene_bg_inputs(
        0, sp["scenes"][0], sp, project["ts_dir"])
    src = Path(project["ts_dir"]) / "_seed.png"
    src.write_bytes(b"seeded-bg")
    bg_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_bg_cache_meta(sp["scenes"][0], 0, inputs))

    r = client.post(
        f"/api/projects/{project['ts']}/stages/bg/scan-cache")
    body = r.get_json()
    assert body["scene_decisions"]["0"]["candidates"]
    assert body["scene_decisions"]["0"]["decision"] == "pending"
    # scene 1 は別 prompt (= 別 key) なので候補なし
    assert body["scene_decisions"]["1"]["decision"] == "fresh"


# ─── use-cache ──────────────────────────────────


def test_use_cache_copies_and_records(client, project, stub_imagen):
    sp = staged_pipeline.load_project_screenplay(project["ts_dir"])
    inputs = scene_gen._scene_bg_inputs(
        0, sp["scenes"][0], sp, project["ts_dir"])
    src = Path(project["ts_dir"]) / "_seed.png"
    src.write_bytes(b"cached-bg")
    bg_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_bg_cache_meta(sp["scenes"][0], 0, inputs))

    client.post(f"/api/projects/{project['ts']}/stages/bg/scan-cache")
    r = client.post(
        f"/api/projects/{project['ts']}/stages/bg/scenes/0/use-cache",
        json={"key": inputs["cache_key"]})
    assert r.status_code == 200, r.get_json()
    # bg PNG が出来ている
    bg_path = Path(project["ts_dir"], "bg_000.png")
    assert bg_path.exists()
    assert bg_path.read_bytes() == b"cached-bg"
    decisions = progress_store.get_decisions(project["ts_dir"], "bg")
    assert decisions["scene_decisions"]["0"]["decision"] == "cache"
    assert decisions["scene_decisions"]["0"]["decided_key"] == inputs["cache_key"]


def test_use_cache_missing_key_400(client, project, stub_imagen):
    r = client.post(
        f"/api/projects/{project['ts']}/stages/bg/scenes/0/use-cache",
        json={})
    assert r.status_code == 400


def test_use_cache_unknown_key_404(client, project, stub_imagen):
    r = client.post(
        f"/api/projects/{project['ts']}/stages/bg/scenes/0/use-cache",
        json={"key": "0000000000000000"})
    assert r.status_code == 404


# ─── queue-fresh ────────────────────────────────


def test_queue_fresh_marks_decision(client, project, stub_imagen):
    client.post(f"/api/projects/{project['ts']}/stages/bg/scan-cache")
    r = client.post(
        f"/api/projects/{project['ts']}/stages/bg/scenes/0/queue-fresh")
    assert r.status_code == 200
    decisions = progress_store.get_decisions(project["ts_dir"], "bg")
    assert decisions["scene_decisions"]["0"]["decision"] == "fresh"


# ─── decisions/bulk ────────────────────────────


def test_bulk_all_cache_adopts(client, project, stub_imagen):
    sp = staged_pipeline.load_project_screenplay(project["ts_dir"])
    inputs = scene_gen._scene_bg_inputs(
        0, sp["scenes"][0], sp, project["ts_dir"])
    src = Path(project["ts_dir"]) / "_seed.png"
    src.write_bytes(b"bulk-bg")
    bg_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_bg_cache_meta(sp["scenes"][0], 0, inputs))
    client.post(f"/api/projects/{project['ts']}/stages/bg/scan-cache")

    r = client.post(
        f"/api/projects/{project['ts']}/stages/bg/decisions/bulk",
        json={"action": "all-cache"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["scene_decisions"]["0"]["decision"] == "cache"
    assert body["scene_decisions"]["1"]["decision"] == "fresh"
    assert body["summary"]["adopted"] == 1
    assert Path(project["ts_dir"], "bg_000.png").read_bytes() == b"bulk-bg"


def test_bulk_all_fresh_clears_files(client, project, stub_imagen):
    Path(project["ts_dir"], "bg_000.png").write_bytes(b"old")
    client.post(f"/api/projects/{project['ts']}/stages/bg/scan-cache")
    r = client.post(
        f"/api/projects/{project['ts']}/stages/bg/decisions/bulk",
        json={"action": "all-fresh"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["scene_decisions"]["0"]["decision"] == "fresh"
    assert body["scene_decisions"]["1"]["decision"] == "fresh"
    assert not Path(project["ts_dir"], "bg_000.png").exists()


def test_bulk_invalid_action_400(client, project, stub_imagen):
    r = client.post(
        f"/api/projects/{project['ts']}/stages/bg/decisions/bulk",
        json={"action": "weird"})
    assert r.status_code == 400


# ─── generate-remaining ────────────────────────


def test_generate_remaining_blocks_when_pending(
        client, project, stub_imagen):
    sp = staged_pipeline.load_project_screenplay(project["ts_dir"])
    inputs = scene_gen._scene_bg_inputs(
        0, sp["scenes"][0], sp, project["ts_dir"])
    src = Path(project["ts_dir"]) / "_seed.png"
    src.write_bytes(b"x")
    bg_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_bg_cache_meta(sp["scenes"][0], 0, inputs))
    client.post(f"/api/projects/{project['ts']}/stages/bg/scan-cache")
    r = client.post(
        f"/api/projects/{project['ts']}/stages/bg/generate-remaining")
    assert r.status_code == 400
    body = r.get_json()
    assert body["pending_scenes"] == [0]


def test_generate_remaining_runs_only_fresh(client, project, stub_imagen):
    client.post(f"/api/projects/{project['ts']}/stages/bg/scan-cache")
    client.post(
        f"/api/projects/{project['ts']}/stages/bg/decisions/bulk",
        json={"action": "all-fresh"})
    r = client.post(
        f"/api/projects/{project['ts']}/stages/bg/generate-remaining")
    assert r.status_code == 200
    body = r.get_json()
    assert body["fresh_scenes"] == [0, 1]
    job_id = body["job_id"]
    for _ in range(50):
        j = client.get(f"/api/jobs/{job_id}").get_json()
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "completed", j
    assert len(stub_imagen) == 2
    assert progress_store.is_generated(project["ts_dir"], "bg")


# ─── bg-cache entries / blacklist / preview / delete ──


def test_cache_entries_and_blacklist(client, project, stub_imagen):
    src = Path(project["ts_dir"]) / "_seed.png"
    src.write_bytes(b"abc")
    sp = staged_pipeline.load_project_screenplay(project["ts_dir"])
    inputs = scene_gen._scene_bg_inputs(
        0, sp["scenes"][0], sp, project["ts_dir"])
    bg_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_bg_cache_meta(sp["scenes"][0], 0, inputs))

    r = client.get("/api/bg-cache/entries")
    assert r.status_code == 200
    entries = r.get_json()["entries"]
    assert any(e["key"] == inputs["cache_key"] for e in entries)

    r = client.post(
        f"/api/bg-cache/{inputs['cache_key']}/blacklist",
        json={"reason": "コマ割り混入"})
    assert r.status_code == 200
    meta = bg_cache.load_meta(inputs["cache_key"])
    assert meta["quality"]["blacklisted"] is True
    assert meta["quality"]["blacklist_reason"] == "コマ割り混入"


def test_cache_preview_serves_png(client, project, stub_imagen):
    src = Path(project["ts_dir"]) / "_seed.png"
    src.write_bytes(b"image-bytes")
    sp = staged_pipeline.load_project_screenplay(project["ts_dir"])
    inputs = scene_gen._scene_bg_inputs(
        0, sp["scenes"][0], sp, project["ts_dir"])
    bg_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_bg_cache_meta(sp["scenes"][0], 0, inputs))

    r = client.get(f"/api/bg-cache/{inputs['cache_key']}/preview.png")
    assert r.status_code == 200
    assert r.data == b"image-bytes"


def test_cache_preview_invalid_key_400(client):
    r = client.get("/api/bg-cache/notavalidhash/preview.png")
    assert r.status_code == 400


def test_cache_delete_removes_entry(client, project, stub_imagen):
    src = Path(project["ts_dir"]) / "_seed.png"
    src.write_bytes(b"delete-me")
    sp = staged_pipeline.load_project_screenplay(project["ts_dir"])
    inputs = scene_gen._scene_bg_inputs(
        0, sp["scenes"][0], sp, project["ts_dir"])
    bg_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_bg_cache_meta(sp["scenes"][0], 0, inputs))

    r = client.delete(f"/api/bg-cache/{inputs['cache_key']}")
    assert r.status_code == 200
    assert bg_cache.lookup(inputs["cache_key"]) is None
