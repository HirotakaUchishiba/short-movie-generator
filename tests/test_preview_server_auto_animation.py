"""preview_server の auto-animation-prompt エンドポイント検証。"""

import json
from unittest.mock import MagicMock

import pytest

import auto_animation_prompt as aap
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

    name = "auto_test_screenplay"
    sp = {
        "caption": "test",
        "scenes": [
            {
                "duration": 5,
                "background_prompt": "デスク",
                "lines": [
                    {"text": "やったー", "start": 0, "emotion": "喜び",
                     "delivery": "弾むような声"},
                ],
            },
            {
                "duration": 4,
                "background_prompt": "他のシーン",
                "lines": [
                    {"text": "うーん", "start": 0, "emotion": "困惑"},
                ],
            },
        ],
    }
    with open(sp_dir / f"{name}.json", "w") as f:
        json.dump(sp, f, ensure_ascii=False)

    ts = "20260429_100000"
    ts_dir = temp_dir / ts
    ts_dir.mkdir()
    with open(ts_dir / "metadata.json", "w") as f:
        json.dump({"screenplay_name": f"{name}.json"}, f)
    return {"ts": ts, "name": name, "sp_path": str(sp_dir / f"{name}.json"),
            "ts_dir": str(ts_dir)}


@pytest.fixture
def client():
    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


def test_get_returns_null_when_no_cache(client, project) -> None:
    r = client.get(f"/api/projects/{project['ts']}/scenes/0/auto-animation-prompt")
    assert r.status_code == 200
    body = r.get_json()
    assert body["auto"] is None
    assert body["cached"] is False
    assert body["manual"] is None


def test_post_regenerate_calls_llm(client, project, monkeypatch) -> None:
    fake_generate = MagicMock(return_value={
        "composed": "AUTO_OUTPUT",
        "structured": {
            "subject": "Young woman",
            "action_sequence": "leans forward",
            "camera": "subtle zoom",
            "mood": "relief",
        },
        "input_hash": "hash1",
    })
    monkeypatch.setattr(aap, "generate", fake_generate)

    r = client.post(
        f"/api/projects/{project['ts']}/scenes/0/auto-animation-prompt",
        json={"action": "regenerate"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["auto"] == "AUTO_OUTPUT"
    assert body["structured"]["subject"] == "Young woman"
    fake_generate.assert_called_once()
    args, kwargs = fake_generate.call_args
    assert kwargs.get("force") is True


def test_post_adopt_writes_back_to_screenplay(
    client, project, monkeypatch,
) -> None:
    """adopt でキャッシュ済み prompt が screenplay の animation_prompt に書き戻される。"""
    monkeypatch.setattr(aap, "get_cached", lambda *a, **kw: {
        "composed": "ADOPTED_PROMPT",
        "structured": {
            "subject": "S", "action_sequence": "A",
            "camera": "C", "mood": "M",
        },
        "input_hash": "h",
    })

    r = client.post(
        f"/api/projects/{project['ts']}/scenes/0/auto-animation-prompt",
        json={"action": "adopt"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["adopted"] is True
    assert body["manual"] == "ADOPTED_PROMPT"

    # disk 上の screenplay にも反映されている
    with open(project["sp_path"]) as f:
        disk = json.load(f)
    assert disk["scenes"][0]["animation_prompt"] == "ADOPTED_PROMPT"
    # 他シーンは変わらない
    assert "animation_prompt" not in disk["scenes"][1] \
        or disk["scenes"][1].get("animation_prompt") != "ADOPTED_PROMPT"


def test_post_adopt_without_cache_returns_400(
    client, project, monkeypatch,
) -> None:
    monkeypatch.setattr(aap, "get_cached", lambda *a, **kw: None)
    r = client.post(
        f"/api/projects/{project['ts']}/scenes/0/auto-animation-prompt",
        json={"action": "adopt"},
    )
    assert r.status_code == 400
    assert "採用できる" in r.get_json()["error"]


def test_post_unknown_action_returns_400(client, project) -> None:
    r = client.post(
        f"/api/projects/{project['ts']}/scenes/0/auto-animation-prompt",
        json={"action": "frobnicate"},
    )
    assert r.status_code == 400


def test_get_after_regenerate_returns_cached(
    client, project, monkeypatch,
) -> None:
    """regenerate 後の GET は cached=True で同じ内容を返す。"""
    monkeypatch.setattr(aap, "generate", lambda *a, **kw: {
        "composed": "CACHED",
        "structured": {"subject": "x", "action_sequence": "y",
                        "camera": "z", "mood": "w"},
        "input_hash": "h",
    })
    monkeypatch.setattr(aap, "get_cached", lambda *a, **kw: {
        "composed": "CACHED",
        "structured": {"subject": "x", "action_sequence": "y",
                        "camera": "z", "mood": "w"},
        "input_hash": "h",
    })

    client.post(
        f"/api/projects/{project['ts']}/scenes/0/auto-animation-prompt",
        json={"action": "regenerate"},
    )
    r = client.get(f"/api/projects/{project['ts']}/scenes/0/auto-animation-prompt")
    body = r.get_json()
    assert body["cached"] is True
    assert body["auto"] == "CACHED"


def test_out_of_range_scene_idx_returns_400(client, project) -> None:
    r = client.get(f"/api/projects/{project['ts']}/scenes/99/auto-animation-prompt")
    assert r.status_code == 400


def test_post_regenerate_handles_llm_error(client, project, monkeypatch) -> None:
    def boom(*a, **kw):
        raise RuntimeError("LLM dead")
    monkeypatch.setattr(aap, "generate", boom)

    r = client.post(
        f"/api/projects/{project['ts']}/scenes/0/auto-animation-prompt",
        json={"action": "regenerate"},
    )
    assert r.status_code == 500
    assert "LLM dead" in r.get_json()["error"]
