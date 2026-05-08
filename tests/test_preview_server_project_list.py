"""GET /api/projects のテスト。

friendly title (= caption 1 行目) / hashtag / scene_count / has_bg_thumbnail を
返すことを確認する。
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


def _make_project(isolated_env, ts: str, screenplay: dict,
                   template_name: str = "test.json") -> str:
    import staged_pipeline
    ts_path = isolated_env["temp_dir"] / ts
    ts_path.mkdir(parents=True, exist_ok=True)
    staged_pipeline.run_script(screenplay, template_name, str(ts_path))
    return str(ts_path)


# ─── _split_caption / _project_display_title (pure helpers) ─────

def test_split_caption_extracts_title_and_hashtags():
    from preview_server import _split_caption
    cap = "未経験からITエンジニアに転職した1日のリアル\n在宅ワークで自由な働き方が叶った\n#IT転職 #未経験エンジニア"
    title, tags = _split_caption(cap)
    assert title == "未経験からITエンジニアに転職した1日のリアル"
    assert tags == "#IT転職 #未経験エンジニア"


def test_split_caption_handles_empty():
    from preview_server import _split_caption
    assert _split_caption("") == ("", "")
    assert _split_caption(None) == ("", "")


def test_split_caption_skips_blank_lines():
    from preview_server import _split_caption
    title, tags = _split_caption("\n\n本タイトル\n\n#tag1")
    assert title == "本タイトル"
    assert tags == "#tag1"


def test_split_caption_no_hashtags():
    from preview_server import _split_caption
    title, tags = _split_caption("シンプルなタイトルだけ")
    assert title == "シンプルなタイトルだけ"
    assert tags == ""


def test_display_title_prefers_caption():
    from preview_server import _project_display_title
    sp = {"caption": "本物のタイトル\n#tag"}
    assert _project_display_title(sp, "auto_abc.json") == "本物のタイトル"


def test_display_title_strips_json_extension():
    from preview_server import _project_display_title
    assert _project_display_title(None, "19_test.json") == "19_test"


def test_display_title_humanizes_auto_hash():
    from preview_server import _project_display_title
    name = "auto_72fb061ef4e3f8f0027475c7a5add1dec08619427fede4659e0f9337e1e9f361.json"
    title = _project_display_title(None, name)
    assert title.startswith("参考動画 ")
    assert "72fb061e" in title


def test_display_title_falls_back_when_all_missing():
    from preview_server import _project_display_title
    assert _project_display_title(None, None) == "(無題)"
    assert _project_display_title({"caption": ""}, None) == "(無題)"


# ─── GET /api/projects (integration) ────────────────────────────

_SP_WITH_CAPTION = {
    "caption": "未経験からITエンジニアに転職した1日のリアル\n在宅ワークで自由な働き方が叶った\n#IT転職 #未経験エンジニア",
    "scenes": [
        {"duration": 3.0, "lines": [{"text": "やばい", "start": 0, "end": 2}]},
        {"duration": 2.5, "lines": [{"text": "でもなんとかなる", "start": 0, "end": 2}]},
    ],
}


def test_projects_returns_friendly_title(client, isolated_env):
    _make_project(isolated_env, "20260507_120000", _SP_WITH_CAPTION)
    r = client.get("/api/projects")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["projects"]) == 1
    p = body["projects"][0]
    assert p["display_title"] == "未経験からITエンジニアに転職した1日のリアル"
    assert p["caption_hashtags"] == "#IT転職 #未経験エンジニア"
    assert p["scene_count"] == 2


def test_projects_has_bg_thumbnail_flag(client, isolated_env):
    ts_path = _make_project(isolated_env, "20260507_120100", _SP_WITH_CAPTION)
    r = client.get("/api/projects")
    p = r.get_json()["projects"][0]
    assert p["has_bg_thumbnail"] is False
    # bg_000.png を作って再取得
    with open(os.path.join(ts_path, "bg_000.png"), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
    r = client.get("/api/projects")
    p = r.get_json()["projects"][0]
    assert p["has_bg_thumbnail"] is True


def test_projects_falls_back_to_filename_when_caption_missing(client, isolated_env):
    """screenplay snapshot の caption が空 / 不正な場合、metadata の
    screenplay_name から friendly title を導出する (= validator はバイパス
    して metadata だけ存在する状態を再現する)。
    """
    ts = "20260507_120200"
    ts_path = isolated_env["temp_dir"] / ts
    ts_path.mkdir(parents=True, exist_ok=True)
    (ts_path / "metadata.json").write_text(
        json.dumps({
            "screenplay_name": "19_未経験からITエンジニアに転職した末路.json",
            "screenplay_template_name": "19_未経験からITエンジニアに転職した末路.json",
            "screenplay_path": "screenplay.json",
            "created_at": "2026-05-07T12:02:00",
        }),
        encoding="utf-8",
    )
    # snapshot は無し → load_project_screenplay が FileNotFoundError → caption 不在
    r = client.get("/api/projects")
    p = r.get_json()["projects"][0]
    assert p["display_title"] == "19_未経験からITエンジニアに転職した末路"


def test_projects_returns_multiple_sorted_by_ts_desc(client, isolated_env):
    _make_project(isolated_env, "20260507_120000", _SP_WITH_CAPTION)
    sp2 = dict(_SP_WITH_CAPTION)
    sp2["caption"] = "新しい方"
    _make_project(isolated_env, "20260507_130000", sp2)
    r = client.get("/api/projects")
    body = r.get_json()
    assert [p["timestamp"] for p in body["projects"]] == [
        "20260507_130000", "20260507_120000",
    ]
