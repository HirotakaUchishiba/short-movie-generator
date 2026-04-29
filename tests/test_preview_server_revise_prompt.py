"""preview_server の revise-prompt エンドポイント検証。"""

import json
from unittest.mock import MagicMock

import pytest

import preview_server
import prompt_revise
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

    name = "revise_test_screenplay"
    sp = {
        "caption": "test",
        "scenes": [
            {
                "duration": 5,
                "background_prompt": "デスクに向かう女性 cinematic lighting",
                "animation_prompt": "young woman leans forward, subtle zoom",
                "lines": [
                    {"text": "やったー", "start": 0, "emotion": "喜び",
                     "delivery": "弾むような声"},
                ],
            },
            {
                "duration": 4,
                "background_prompt": "他のシーン",
                "animation_prompt": "another scene motion",
                "lines": [
                    {"text": "うーん", "start": 0, "emotion": "困惑"},
                ],
            },
        ],
    }
    with open(sp_dir / f"{name}.json", "w") as f:
        json.dump(sp, f, ensure_ascii=False)

    ts = "20260429_110000"
    ts_dir = temp_dir / ts
    ts_dir.mkdir()
    with open(ts_dir / "metadata.json", "w") as f:
        json.dump({"screenplay_name": f"{name}.json"}, f)
    drafts_path = sp_dir / "drafts" / f"{name}.json"
    return {"ts": ts, "name": name, "sp_path": str(sp_dir / f"{name}.json"),
            "drafts_path": str(drafts_path), "ts_dir": str(ts_dir)}


@pytest.fixture
def client():
    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


def test_preview_returns_revised_text(client, project, monkeypatch) -> None:
    fake_revise = MagicMock(return_value={
        "revised": "デスクに向かう女性 wide shot, cinematic lighting",
        "model": "claude-sonnet-4-6",
        "field": "background_prompt",
    })
    monkeypatch.setattr(prompt_revise, "revise", fake_revise)

    r = client.post(
        f"/api/projects/{project['ts']}/scenes/0/revise-prompt",
        json={
            "action": "preview",
            "field": "background_prompt",
            "instruction_ja": "カメラを引いて wide shot に",
        },
    )
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["field"] == "background_prompt"
    assert "wide shot" in body["revised"]
    assert body["previous"]
    fake_revise.assert_called_once()
    _, kwargs = fake_revise.call_args
    assert kwargs["field"] == "background_prompt"
    assert kwargs["instruction_ja"] == "カメラを引いて wide shot に"


def test_preview_animation_field(client, project, monkeypatch) -> None:
    fake_revise = MagicMock(return_value={
        "revised": "young woman exhales and smiles, subtle zoom-in",
        "model": "claude-sonnet-4-6",
        "field": "animation_prompt",
    })
    monkeypatch.setattr(prompt_revise, "revise", fake_revise)

    r = client.post(
        f"/api/projects/{project['ts']}/scenes/0/revise-prompt",
        json={
            "action": "preview",
            "field": "animation_prompt",
            "instruction_ja": "笑顔に変えて",
        },
    )
    assert r.status_code == 200
    body = r.get_json()
    assert "exhales" in body["revised"]
    assert body["field"] == "animation_prompt"


def test_apply_writes_to_screenplay(client, project) -> None:
    revised_text = "young woman gasps, leans back, subtle zoom-out"
    r = client.post(
        f"/api/projects/{project['ts']}/scenes/0/revise-prompt",
        json={
            "action": "apply",
            "field": "animation_prompt",
            "instruction_ja": "驚きの動きに変えて",
            "revised": revised_text,
        },
    )
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["applied"] is True

    # save_screenplay は drafts/ に書き出す
    with open(project["drafts_path"]) as f:
        disk = json.load(f)
    assert disk["scenes"][0]["animation_prompt"] == revised_text
    # 他シーン未変更
    assert disk["scenes"][1]["animation_prompt"] == "another scene motion"
    # canonical は触っていない
    with open(project["sp_path"]) as f:
        canonical = json.load(f)
    assert canonical["scenes"][0]["animation_prompt"] == "young woman leans forward, subtle zoom"


def test_apply_writes_background_prompt(client, project) -> None:
    revised_text = "デスクに向かう女性 wide shot ultra-detailed"
    r = client.post(
        f"/api/projects/{project['ts']}/scenes/0/revise-prompt",
        json={
            "action": "apply",
            "field": "background_prompt",
            "instruction_ja": "wide shot に",
            "revised": revised_text,
        },
    )
    assert r.status_code == 200
    with open(project["drafts_path"]) as f:
        disk = json.load(f)
    assert disk["scenes"][0]["background_prompt"] == revised_text


def test_apply_without_revised_returns_400(client, project) -> None:
    r = client.post(
        f"/api/projects/{project['ts']}/scenes/0/revise-prompt",
        json={
            "action": "apply",
            "field": "background_prompt",
            "instruction_ja": "変えて",
        },
    )
    assert r.status_code == 400
    assert "revised" in r.get_json()["error"]


def test_unknown_field_returns_400(client, project) -> None:
    r = client.post(
        f"/api/projects/{project['ts']}/scenes/0/revise-prompt",
        json={
            "action": "preview",
            "field": "weird_prompt",
            "instruction_ja": "変えて",
        },
    )
    assert r.status_code == 400


def test_empty_instruction_returns_400(client, project) -> None:
    r = client.post(
        f"/api/projects/{project['ts']}/scenes/0/revise-prompt",
        json={
            "action": "preview",
            "field": "background_prompt",
            "instruction_ja": "   ",
        },
    )
    assert r.status_code == 400


def test_unknown_action_returns_400(client, project) -> None:
    r = client.post(
        f"/api/projects/{project['ts']}/scenes/0/revise-prompt",
        json={
            "action": "frobnicate",
            "field": "background_prompt",
            "instruction_ja": "変えて",
        },
    )
    assert r.status_code == 400


def test_out_of_range_scene_idx_returns_400(client, project) -> None:
    r = client.post(
        f"/api/projects/{project['ts']}/scenes/99/revise-prompt",
        json={
            "action": "preview",
            "field": "background_prompt",
            "instruction_ja": "変えて",
        },
    )
    assert r.status_code == 400


def test_preview_propagates_validation_error(client, project, monkeypatch) -> None:
    """LLM が UI 語を返してきたら 400 (ValueError) を返す。"""
    def boom(*a, **kw):
        raise ValueError("UI 誘発語を検出: ['chat bubble']")
    monkeypatch.setattr(prompt_revise, "revise", boom)

    r = client.post(
        f"/api/projects/{project['ts']}/scenes/0/revise-prompt",
        json={
            "action": "preview",
            "field": "animation_prompt",
            "instruction_ja": "変えて",
        },
    )
    assert r.status_code == 400
    assert "UI 誘発語" in r.get_json()["error"]


def test_preview_handles_runtime_error_500(client, project, monkeypatch) -> None:
    def boom(*a, **kw):
        raise RuntimeError("ANTHROPIC_API_KEY 未設定")
    monkeypatch.setattr(prompt_revise, "revise", boom)

    r = client.post(
        f"/api/projects/{project['ts']}/scenes/0/revise-prompt",
        json={
            "action": "preview",
            "field": "background_prompt",
            "instruction_ja": "変えて",
        },
    )
    assert r.status_code == 400
    assert "ANTHROPIC_API_KEY" in r.get_json()["error"]


def test_preview_uses_composed_prompt_as_baseline(client, project, monkeypatch) -> None:
    """preview の "previous" は scene_gen の合成済みプロンプトに基づく。
    手書き background_prompt が直接使われるか、emotion等を反映した合成版が
    使われるかは scene_gen 側の責務。ここでは scene_gen を呼ぶこと自体を確認。"""
    captured = {}
    fake_build_bg = MagicMock(side_effect=lambda scene, sp, **kw: "COMPOSED_BG")
    fake_get_anim = MagicMock(side_effect=lambda scene, **kw: "COMPOSED_ANIM")
    monkeypatch.setattr(scene_gen, "_build_background_prompt", fake_build_bg)
    monkeypatch.setattr(scene_gen, "_get_animation_prompt", fake_get_anim)

    def fake_revise(*a, **kw):
        captured.update(kw)
        return {
            "revised": "REVISED",
            "model": "claude-sonnet-4-6",
            "field": kw["field"],
        }
    monkeypatch.setattr(prompt_revise, "revise", fake_revise)

    r = client.post(
        f"/api/projects/{project['ts']}/scenes/0/revise-prompt",
        json={
            "action": "preview",
            "field": "background_prompt",
            "instruction_ja": "変えて",
        },
    )
    assert r.status_code == 200
    assert captured["current_prompt"] == "COMPOSED_BG"
    fake_build_bg.assert_called_once()

    r2 = client.post(
        f"/api/projects/{project['ts']}/scenes/0/revise-prompt",
        json={
            "action": "preview",
            "field": "animation_prompt",
            "instruction_ja": "変えて",
        },
    )
    assert r2.status_code == 200
    assert captured["current_prompt"] == "COMPOSED_ANIM"
    fake_get_anim.assert_called_once()
