"""line patch API の単体テスト。

server-side merge により並行 patch が race しないことを検証。
"""
import json
import os
import threading

import pytest

import preview_server
import staged_pipeline


@pytest.fixture
def project(tmp_path, monkeypatch):
    """temp_dir + screenplay を用意した1プロジェクト。"""
    sp_dir = tmp_path / "screenplays"
    sp_dir.mkdir()
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    monkeypatch.setattr(preview_server.config, "SCREENPLAYS_DIR", str(sp_dir))
    monkeypatch.setattr(preview_server.config, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(preview_server, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(staged_pipeline.config, "SCREENPLAYS_DIR", str(sp_dir))

    name = "test_screenplay"
    sp = {
        "caption": "x",
        "scenes": [
            {
                "duration": 3,
                "background_prompt": "x",
                "lines": [
                    {"text": "line A", "start": 0, "silence_after_ms": 100},
                    {"text": "line B", "start": 1, "silence_after_ms": 200},
                    {"text": "line C", "start": 2},
                ],
            },
        ],
    }
    with open(sp_dir / f"{name}.json", "w") as f:
        json.dump(sp, f, ensure_ascii=False)

    ts = "20260426_120000"
    ts_dir = temp_dir / ts
    ts_dir.mkdir()
    with open(ts_dir / "metadata.json", "w") as f:
        json.dump({"screenplay_name": f"{name}.json"}, f)
    return {"ts": ts, "name": name, "sp_path": str(sp_dir / f"{name}.json")}


@pytest.fixture
def client():
    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


def test_patch_line_updates_single_field(client, project):
    r = client.patch(
        f"/api/projects/{project['ts']}/lines/0/0",
        json={"patch": {"silence_after_ms": 999}},
    )
    assert r.status_code == 200
    sp = json.load(open(project["sp_path"]))
    assert sp["scenes"][0]["lines"][0]["silence_after_ms"] == 999
    # 他 line に影響なし
    assert sp["scenes"][0]["lines"][1]["silence_after_ms"] == 200
    assert "silence_after_ms" not in sp["scenes"][0]["lines"][2]


def test_patch_line_null_deletes_field(client, project):
    r = client.patch(
        f"/api/projects/{project['ts']}/lines/0/0",
        json={"patch": {"silence_after_ms": None}},
    )
    assert r.status_code == 200
    sp = json.load(open(project["sp_path"]))
    assert "silence_after_ms" not in sp["scenes"][0]["lines"][0]
    # 他は無傷
    assert sp["scenes"][0]["lines"][1]["silence_after_ms"] == 200


def test_patch_line_rejects_unknown_field(client, project):
    r = client.patch(
        f"/api/projects/{project['ts']}/lines/0/0",
        json={"patch": {"evil_field": "danger"}},
    )
    assert r.status_code == 400
    assert "許可されていない" in r.get_json()["error"]


def test_patch_line_rejects_out_of_range(client, project):
    r = client.patch(
        f"/api/projects/{project['ts']}/lines/0/99",
        json={"patch": {"silence_after_ms": 100}},
    )
    assert r.status_code == 400


def test_patch_line_validation_failure_rolls_back(client, project):
    # 範囲外 (max=2000) → validator失敗 → save されない
    r = client.patch(
        f"/api/projects/{project['ts']}/lines/0/0",
        json={"patch": {"silence_after_ms": 99999}},
    )
    assert r.status_code == 400
    sp = json.load(open(project["sp_path"]))
    # 元の値 (100) のまま
    assert sp["scenes"][0]["lines"][0]["silence_after_ms"] == 100


def test_patch_line_concurrent_updates_preserve_each_other(client, project):
    """3 line を並行 patch しても全て保存される (server-side merge)。"""
    barrier = threading.Barrier(3)
    results = [None, None, None]

    def patch_line(idx, value):
        barrier.wait()
        r = client.patch(
            f"/api/projects/{project['ts']}/lines/0/{idx}",
            json={"patch": {"silence_after_ms": value}},
        )
        results[idx] = r.status_code

    threads = [
        threading.Thread(target=patch_line, args=(0, 1000)),
        threading.Thread(target=patch_line, args=(1, 1500)),
        threading.Thread(target=patch_line, args=(2, 500)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(s == 200 for s in results)
    sp = json.load(open(project["sp_path"]))
    assert sp["scenes"][0]["lines"][0]["silence_after_ms"] == 1000
    assert sp["scenes"][0]["lines"][1]["silence_after_ms"] == 1500
    assert sp["scenes"][0]["lines"][2]["silence_after_ms"] == 500


def test_tts_source_returns_joined_text_and_specs(client, project):
    r = client.get(f"/api/projects/{project['ts']}/tts-source")
    assert r.status_code == 200
    data = r.get_json()
    # line A + sep + line B + sep + line C
    assert data["text"] == "line A  line B  line C"
    assert data["char_count"] == len("line A  line B  line C")
    assert data["separator"] == "  "
    specs = data["line_specs"]
    assert len(specs) == 3
    # A: 0..6, B: 8..14, C: 16..22
    assert specs[0]["char_start"] == 0 and specs[0]["char_end"] == 6
    assert specs[1]["char_start"] == 8 and specs[1]["char_end"] == 14
    assert specs[2]["char_start"] == 16 and specs[2]["char_end"] == 22


def test_patch_scene_updates_emotion_cue_overrides(client, project):
    r = client.patch(
        f"/api/projects/{project['ts']}/scenes/0",
        json={"patch": {"emotion_cue_overrides": {"facial": "neutral"}}},
    )
    assert r.status_code == 200
    sp = json.load(open(project["sp_path"]))
    assert sp["scenes"][0]["emotion_cue_overrides"] == {"facial": "neutral"}


def test_patch_scene_rejects_invalid_preset_id(client, project):
    r = client.patch(
        f"/api/projects/{project['ts']}/scenes/0",
        json={"patch": {"emotion_cue_overrides": {"facial": "fake_preset"}}},
    )
    assert r.status_code == 400


def test_patch_scene_rejects_unknown_field(client, project):
    r = client.patch(
        f"/api/projects/{project['ts']}/scenes/0",
        json={"patch": {"evil_field": "x"}},
    )
    assert r.status_code == 400


def test_patch_scene_updates_tags(client, project):
    r = client.patch(
        f"/api/projects/{project['ts']}/scenes/0",
        json={"patch": {"tags": ["home_office", "morning"]}},
    )
    assert r.status_code == 200
    sp = json.load(open(project["sp_path"]))
    assert sp["scenes"][0]["tags"] == ["home_office", "morning"]


def test_patch_screenplay_meta_scoped_augmentations(client, project):
    r = client.patch(
        f"/api/projects/{project['ts']}/screenplay-meta",
        json={
            "patch": {
                "scoped_augmentations": [
                    {
                        "scope": {"tag": "home_office"},
                        "elements": ["standing_desk", "plants_background"],
                    },
                ],
            },
        },
    )
    assert r.status_code == 200
    sp = json.load(open(project["sp_path"]))
    assert len(sp["scoped_augmentations"]) == 1


def test_get_presets_returns_libraries(client, project):
    r = client.get("/api/presets")
    assert r.status_code == 200
    data = r.get_json()
    assert "libraries" in data
    assert "scene_tags" in data
    assert "facial" in data["libraries"]
    assert len(data["libraries"]["facial"]) > 10
