"""GET/PUT /api/projects/<ts>/abstract のテスト。

project 内 immutable snapshot (= temp/<TS>/screenplay.json) を読み書きする。
template (= screenplays/<name>.json) は触らない。
"""
import json
import os

import pytest


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    sp_dir = tmp_path / "screenplays"
    sp_dir.mkdir(parents=True)
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True)
    import config as _cfg
    import staged_pipeline
    monkeypatch.setattr(_cfg, "SCREENPLAYS_DIR", str(sp_dir))
    monkeypatch.setattr(_cfg, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(staged_pipeline.config, "SCREENPLAYS_DIR", str(sp_dir))
    return {"tmp_path": tmp_path, "sp_dir": sp_dir, "temp_dir": temp_dir}


@pytest.fixture
def client(isolated_env, monkeypatch):
    import preview_server
    monkeypatch.setattr(preview_server, "TEMP_DIR", str(isolated_env["temp_dir"]))
    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


_PROJECT_SP = {
    "caption": "test caption",
    "scenes": [
        {
            "duration": 4.0,
            "background_prompt": "bg placeholder",
            "animation_prompt": "anim placeholder",
            "lines": [
                {"text": "やばい", "start": 0, "end": 2,
                 "emotion": "焦り", "delivery": "早口"},
            ],
        },
    ],
}


def _make_project(isolated_env, ts: str = "20260429_120000",
                   screenplay: dict | None = None) -> tuple[str, str]:
    """run_script を直接叩いて project snapshot を作成する。"""
    import staged_pipeline
    sp = screenplay or _PROJECT_SP
    ts_path = isolated_env["temp_dir"] / ts
    ts_path.mkdir(parents=True, exist_ok=True)
    staged_pipeline.run_script(sp, "abstract_test_template", str(ts_path))
    return ts, str(ts_path)


# ─── GET ─────────────────────────────────────────────────────

def test_get_abstract_returns_snapshot(client, isolated_env):
    ts, ts_path = _make_project(isolated_env)
    r = client.get(f"/api/projects/{ts}/abstract")
    assert r.status_code == 200
    body = r.get_json()
    assert body["screenplay_path"].endswith("screenplay.json")
    assert body["abstract"]["caption"] == "test caption"
    assert len(body["abstract"]["scenes"]) == 1


def test_get_abstract_404_for_unknown_project(client):
    r = client.get("/api/projects/29991231_000000/abstract")
    assert r.status_code == 404


def test_get_abstract_400_for_invalid_ts(client):
    r = client.get("/api/projects/bad ts/abstract")
    assert r.status_code in (400, 404)


def test_get_abstract_404_when_snapshot_missing(client, isolated_env):
    """metadata はあるが screenplay.json snapshot が無い → 404。"""
    ts = "20260429_125555"
    ts_path = isolated_env["temp_dir"] / ts
    ts_path.mkdir(parents=True)
    (ts_path / "metadata.json").write_text(
        json.dumps({"screenplay_name": "x", "screenplay_path": "screenplay.json"}),
        encoding="utf-8",
    )
    r = client.get(f"/api/projects/{ts}/abstract")
    assert r.status_code == 404


# ─── PUT ─────────────────────────────────────────────────────

def test_put_abstract_writes_to_snapshot_only(client, isolated_env):
    """PUT は project snapshot だけを上書き、template は不変。"""
    ts, ts_path = _make_project(isolated_env)

    template_path = isolated_env["sp_dir"] / "abstract_test_template.json"
    template_path.write_text(json.dumps(_PROJECT_SP, ensure_ascii=False))
    template_before = template_path.read_text()

    new_abstract = {
        "caption": "edited caption",
        "scenes": [
            {
                "duration": 5.0,
                "lines": [
                    {"text": "編集後", "start": 0, "end": 2,
                     "emotion": "中立"},
                ],
            },
        ],
    }
    r = client.put(
        f"/api/projects/{ts}/abstract",
        json={"abstract": new_abstract},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["scenes"] == 1
    snap_path = ts_path + "/screenplay.json"
    assert body["screenplay_path"] == snap_path
    with open(snap_path) as f:
        saved = json.load(f)
    assert saved["caption"] == "edited caption"
    # template は不変
    assert template_path.read_text() == template_before


def test_put_abstract_400_when_body_missing(client, isolated_env):
    ts, _ = _make_project(isolated_env)
    r = client.put(f"/api/projects/{ts}/abstract", json={})
    assert r.status_code == 400


def test_put_abstract_400_when_scenes_empty(client, isolated_env):
    ts, _ = _make_project(isolated_env)
    r = client.put(
        f"/api/projects/{ts}/abstract",
        json={"abstract": {"caption": "x", "scenes": []}},
    )
    assert r.status_code == 400


def test_put_abstract_404_for_unknown_project(client):
    r = client.put(
        "/api/projects/29991231_000000/abstract",
        json={"abstract": {"caption": "x", "scenes": [
            {"duration": 3, "lines": []},
        ]}},
    )
    assert r.status_code == 404


def test_put_abstract_then_get_returns_same(client, isolated_env):
    ts, _ = _make_project(isolated_env)
    new_abstract = {
        "caption": "後から書いた",
        "scenes": [
            {"duration": 3.0, "lines": [
                {"text": "x", "start": 0, "end": 1, "emotion": "中立"},
            ]},
        ],
    }
    client.put(f"/api/projects/{ts}/abstract", json={"abstract": new_abstract})
    r = client.get(f"/api/projects/{ts}/abstract")
    assert r.status_code == 200
    assert r.get_json()["abstract"]["caption"] == "後から書いた"


# ─── PUT abstract validate ─────────────────────────────────


def test_put_abstract_rejects_invalid_schema(client, isolated_env):
    """不正な schema (= ASCII カンマ入りテキスト) は 400 で reject される。"""
    ts, _ = _make_project(isolated_env)
    bad_abstract = {
        "caption": "x",
        "scenes": [
            {"duration": 3, "lines": [
                {"text": "やばい,セーフ", "start": 0, "end": 1},
            ]},
        ],
    }
    r = client.put(f"/api/projects/{ts}/abstract", json={"abstract": bad_abstract})
    assert r.status_code == 400
    body = r.get_json()
    assert "errors" in body
    assert any("text" in e or "pattern" in e for e in body["errors"])


def test_put_abstract_accepts_abstract_form_without_background_prompt(client, isolated_env):
    """abstract 形式 (= background_prompt 無し) は通る (= require_composed=False)。"""
    ts, _ = _make_project(isolated_env)
    abs_form = {
        "caption": "x",
        "featured_characters": ["f1"],
        "speaker_to_ref": {"speaker_1": "f1"},
        "scenes": [
            {
                "duration": 3,
                "location_ref": "home_office",
                "character_selection": ["f1"],
                "animation_style": "subtle",
                "lines": [
                    {"text": "やばい", "start": 0, "end": 1,
                     "speaker": "speaker_1"},
                ],
            },
        ],
    }
    r = client.put(f"/api/projects/{ts}/abstract", json={"abstract": abs_form})
    assert r.status_code == 200, r.get_json()


# ─── GET abstract response shape ───────────────────────────


def test_get_abstract_does_not_include_diagnostics(client, isolated_env):
    """GET レスポンスは abstract のみ (diagnostics は frontend で live 計算)。"""
    ts, _ = _make_project(isolated_env)
    r = client.get(f"/api/projects/{ts}/abstract")
    assert r.status_code == 200
    body = r.get_json()
    assert "abstract" in body
    assert "screenplay_path" in body
    # diagnostics はサーバ応答に含めない (= frontend が abstract から再計算)
    assert "diagnostics" not in body
