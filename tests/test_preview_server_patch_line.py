"""line / scene patch API の単体テスト。

snapshot は abstract 形式のまま読み書きされる (= live derivation)。
allowlist は abstract schema に揃う。並行 patch は per-ts lock で直列化。
"""
import json
import threading

import pytest

import preview_server
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

    name = "test_screenplay"
    # snapshot は abstract 形式 (= 派生フィールド無し) で保持される
    sp = {
        "caption": "x",
        "scenes": [
            {
                "duration": 5,
                "location_ref": "home_office",
                "lines": [
                    {"text": "line A", "start": 0, "end": 1.0, "emotion": "中立"},
                    {"text": "line B", "start": 1, "end": 2.0},
                    {"text": "line C", "start": 2, "end": 3.0},
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
        json.dump({
            "screenplay_name": f"{name}.json",
            "screenplay_path": "screenplay.json",
        }, f)
    with open(ts_dir / "screenplay.json", "w") as f:
        json.dump(sp, f, ensure_ascii=False)
    return {"ts": ts, "name": name, "sp_path": str(ts_dir / "screenplay.json")}


@pytest.fixture
def client():
    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


# ─── line patch ──────────────────────────────────────────


def test_patch_line_updates_emotion(client, project):
    r = client.patch(
        f"/api/projects/{project['ts']}/lines/0/0",
        json={"patch": {"emotion": "焦り"}},
    )
    assert r.status_code == 200, r.get_json()
    sp = json.load(open(project["sp_path"]))
    assert sp["scenes"][0]["lines"][0]["emotion"] == "焦り"
    # 他 line に影響なし
    assert "emotion" not in sp["scenes"][0]["lines"][1]
    assert "emotion" not in sp["scenes"][0]["lines"][2]


def test_patch_line_null_deletes_field(client, project):
    # まず emotion を設定 → null で消す
    client.patch(
        f"/api/projects/{project['ts']}/lines/0/0",
        json={"patch": {"emotion": "驚き"}},
    )
    r = client.patch(
        f"/api/projects/{project['ts']}/lines/0/0",
        json={"patch": {"emotion": None}},
    )
    assert r.status_code == 200
    sp = json.load(open(project["sp_path"]))
    assert "emotion" not in sp["scenes"][0]["lines"][0]


def test_patch_line_rejects_start_end(client, project):
    """start/end は TTS が SSOT — 手動 patch は 400 で reject。"""
    for field in ("start", "end"):
        r = client.patch(
            f"/api/projects/{project['ts']}/lines/0/1",
            json={"patch": {field: 0.5}},
        )
        assert r.status_code == 400, f"{field} の patch が通った"
        assert "許可されていない" in r.get_json()["error"]
    # 元の値は不変
    sp = json.load(open(project["sp_path"]))
    assert sp["scenes"][0]["lines"][1]["start"] == 1
    assert sp["scenes"][0]["lines"][1]["end"] == 2.0


def test_patch_line_updates_subtitles(client, project):
    r = client.patch(
        f"/api/projects/{project['ts']}/lines/0/0",
        json={"patch": {"subtitles": [
            {"text": "やばい"},
            {"text": "セーフ"},
        ]}},
    )
    assert r.status_code == 200, r.get_json()
    sp = json.load(open(project["sp_path"]))
    assert len(sp["scenes"][0]["lines"][0]["subtitles"]) == 2


def test_patch_line_updates_hidden(client, project):
    r = client.patch(
        f"/api/projects/{project['ts']}/lines/0/0",
        json={"patch": {"hidden": True}},
    )
    assert r.status_code == 200
    sp = json.load(open(project["sp_path"]))
    assert sp["scenes"][0]["lines"][0]["hidden"] is True


def test_patch_line_updates_acoustic(client, project):
    r = client.patch(
        f"/api/projects/{project['ts']}/lines/0/0",
        json={"patch": {"acoustic": {
            "pitch_trend": "rising",
            "rms_peak": 0.5,
            "wpm": 320,
        }}},
    )
    assert r.status_code == 200, r.get_json()
    sp = json.load(open(project["sp_path"]))
    assert sp["scenes"][0]["lines"][0]["acoustic"]["pitch_trend"] == "rising"


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
        json={"patch": {"emotion": "驚き"}},
    )
    assert r.status_code == 400


def test_patch_line_validation_failure_rolls_back(client, project):
    """schema 違反 (= subtitles の text 空) で validator が reject、save されない。"""
    r = client.patch(
        f"/api/projects/{project['ts']}/lines/0/0",
        json={"patch": {"subtitles": [{"text": ""}]}},
    )
    assert r.status_code == 400
    sp = json.load(open(project["sp_path"]))
    # 元の line には subtitles が入らないまま
    assert "subtitles" not in sp["scenes"][0]["lines"][0]


def test_patch_line_concurrent_updates_preserve_each_other(client, project):
    """3 line を並行 patch しても全て保存される (per-ts lock + server-side merge)。"""
    barrier = threading.Barrier(3)
    results = [None, None, None]

    def patch_line(idx, value):
        barrier.wait()
        r = client.patch(
            f"/api/projects/{project['ts']}/lines/0/{idx}",
            json={"patch": {"emotion": value}},
        )
        results[idx] = r.status_code

    threads = [
        threading.Thread(target=patch_line, args=(0, "驚き")),
        threading.Thread(target=patch_line, args=(1, "焦り")),
        threading.Thread(target=patch_line, args=(2, "満足")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(s == 200 for s in results)
    sp = json.load(open(project["sp_path"]))
    assert sp["scenes"][0]["lines"][0]["emotion"] == "驚き"
    assert sp["scenes"][0]["lines"][1]["emotion"] == "焦り"
    assert sp["scenes"][0]["lines"][2]["emotion"] == "満足"


def test_patch_line_does_not_bake_derived_fields(client, project):
    """live derivation: snapshot に派生フィールドは焼かれない。

    背景プロンプト・animation_prompt・character_refs などは compose が読み出し
    時に毎回再生成するので、snapshot 上には登場してはいけない。
    """
    r = client.patch(
        f"/api/projects/{project['ts']}/lines/0/0",
        json={"patch": {"emotion": "驚き"}},
    )
    assert r.status_code == 200
    sp = json.load(open(project["sp_path"]))
    scene = sp["scenes"][0]
    for derived in (
        "background_prompt", "animation_prompt", "character_refs",
        "characters", "lipsync",
    ):
        assert derived not in scene, f"派生 '{derived}' が snapshot に焼かれた"


# ─── screenplay-meta patch ─────────────────────────────


def test_patch_screenplay_meta_subtitle_y_from_bottom(client, project):
    r = client.patch(
        f"/api/projects/{project['ts']}/screenplay-meta",
        json={"patch": {"subtitle_y_from_bottom": 200}},
    )
    assert r.status_code == 200, r.get_json()
    sp = json.load(open(project["sp_path"]))
    assert sp["subtitle_y_from_bottom"] == 200


def test_patch_screenplay_meta_rejects_scoped_augmentations(client, project):
    """scoped_augmentations は廃止済み — patch_screenplay_meta allowlist 外。"""
    r = client.patch(
        f"/api/projects/{project['ts']}/screenplay-meta",
        json={"patch": {"scoped_augmentations": []}},
    )
    assert r.status_code == 400


# ─── 横断的サニティチェック ─────────────────────────


def test_get_presets_returns_libraries(client, project):
    r = client.get("/api/presets")
    assert r.status_code == 200
    data = r.get_json()
    assert "libraries" in data
    assert "facial" in data["libraries"]


def test_tts_source_returns_joined_text_and_specs(client, project):
    r = client.get(f"/api/projects/{project['ts']}/tts-source")
    assert r.status_code == 200
    data = r.get_json()
    assert data["text"] == "line A  line B  line C"
    assert data["char_count"] == len("line A  line B  line C")
    assert data["separator"] == "  "
    specs = data["line_specs"]
    assert len(specs) == 3
    assert specs[0]["char_start"] == 0 and specs[0]["char_end"] == 6
    assert specs[1]["char_start"] == 8 and specs[1]["char_end"] == 14
    assert specs[2]["char_start"] == 16 and specs[2]["char_end"] == 22
