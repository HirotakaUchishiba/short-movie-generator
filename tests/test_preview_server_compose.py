"""POST /api/screenplay/analyze/<job>/compose の API テスト。"""
import json

import pytest


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    from analyze import style as _style
    monkeypatch.setattr(_style, "STYLES_DIR", tmp_path / "styles")
    return {"styles_dir": tmp_path / "styles"}


@pytest.fixture
def client(isolated_env):
    import preview_server
    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


def _make_style(client) -> str:
    payload = {
        "name": "test_style",
        "characters": [
            {"name": "主人公", "role": "narrator", "ref": "female_engineer",
             "voice_overrides": {"voice_id": "v1"}},
        ],
        "wardrobe_continuity": {"office": "グレーニット"},
        "default_wardrobe": "office",
        "location_continuity": {
            "home_office": {
                "decor": "ミニマル", "lighting": "自然光",
                "color_palette": "白", "props": "MacBook",
                "camera_distance": "medium",
            },
        },
        "default_location": "home_office",
        "default_tags": ["home_office"],
    }
    r = client.post("/api/styles", json=payload)
    assert r.status_code == 201
    return "test_style"


def _make_job_with_abstract(tmp_path, video_sha="x" * 64) -> str:
    """抽象台本を screenplay_path に書いた completed ジョブを作る。"""
    from analyze import job as analyze_job
    abstract_path = tmp_path / "abstract.json"
    abstract = {
        "caption": "test",
        "scenes": [
            {
                "duration": 4.0,
                "lines": [
                    {"text": "やばい", "start": 0, "end": 2,
                     "emotion": "焦り", "delivery": "早口"},
                ],
            },
        ],
    }
    with open(abstract_path, "w", encoding="utf-8") as f:
        json.dump(abstract, f, ensure_ascii=False)
    j = analyze_job.create_job(video_sha, {})
    analyze_job.transition_status(
        j.id, "completed", screenplay_path=str(abstract_path),
    )
    return j.id


def test_compose_succeeds_and_overwrites(client, tmp_path):
    style_name = _make_style(client)
    job_id = _make_job_with_abstract(tmp_path)
    r = client.post(
        f"/api/screenplay/analyze/{job_id}/compose",
        json={"style_name": style_name},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["style_name"] == style_name
    assert body["scenes"] == 1

    # 上書き後のファイルが完全 screenplay になっている
    with open(body["screenplay_path"], encoding="utf-8") as f:
        sp = json.load(f)
    scene = sp["scenes"][0]
    assert "background_prompt" in scene
    assert "animation_prompt" in scene
    assert scene["wardrobe"]["identifier"] == "office"
    assert scene["location_ref"] == "home_office"
    assert scene["lipsync"] is True
    # voice_overrides が line に注入される
    assert sp["scenes"][0]["lines"][0]["voice_overrides"]["voice_id"] == "v1"


def test_compose_with_scene_overrides(client, tmp_path):
    style_name = _make_style(client)
    job_id = _make_job_with_abstract(tmp_path)
    # 別 wardrobe を style に追加
    client.put(f"/api/styles/{style_name}", json={
        "name": style_name,
        "characters": [
            {"name": "主人公", "role": "narrator", "ref": "female_engineer"},
        ],
        "wardrobe_continuity": {"office": "グレー", "weekend": "パーカー"},
        "default_wardrobe": "office",
        "location_continuity": {
            "home_office": {
                "decor": "x", "lighting": "x", "color_palette": "x",
                "props": "x", "camera_distance": "medium",
            },
        },
        "default_location": "home_office",
        "default_tags": ["home_office"],
    })
    r = client.post(
        f"/api/screenplay/analyze/{job_id}/compose",
        json={"style_name": style_name,
              "scene_overrides": {"0": {"wardrobe": "weekend"}}},
    )
    assert r.status_code == 200
    with open(r.get_json()["screenplay_path"], encoding="utf-8") as f:
        sp = json.load(f)
    assert sp["scenes"][0]["wardrobe"]["identifier"] == "weekend"


def test_compose_404_for_unknown_job(client):
    _make_style(client)
    r = client.post("/api/screenplay/analyze/analyze_nope/compose",
                    json={"style_name": "test_style"})
    assert r.status_code == 404


def test_compose_400_for_invalid_job_id(client):
    r = client.post("/api/screenplay/analyze/bad-id/compose",
                    json={"style_name": "x"})
    assert r.status_code == 400


def test_compose_404_for_unknown_style(client, tmp_path):
    job_id = _make_job_with_abstract(tmp_path)
    r = client.post(f"/api/screenplay/analyze/{job_id}/compose",
                    json={"style_name": "no_such_style"})
    assert r.status_code == 404


def test_compose_400_when_style_name_missing(client, tmp_path):
    job_id = _make_job_with_abstract(tmp_path)
    r = client.post(f"/api/screenplay/analyze/{job_id}/compose", json={})
    assert r.status_code == 400


def test_compose_400_when_screenplay_file_missing(client, tmp_path):
    """ジョブはあるが screenplay_path のファイルが存在しない → 400。"""
    from analyze import job as analyze_job
    _make_style(client)
    j = analyze_job.create_job("x" * 64, {})
    analyze_job.transition_status(
        j.id, "completed", screenplay_path="/nonexistent/path.json",
    )
    r = client.post(f"/api/screenplay/analyze/{j.id}/compose",
                    json={"style_name": "test_style"})
    assert r.status_code == 400
