import json
import os
from unittest.mock import MagicMock

import pytest

import progress_store
import staged_pipeline


@pytest.fixture
def fake_screenplays_dir(tmp_path, monkeypatch) -> str:
    d = tmp_path / "screenplays"
    d.mkdir()
    monkeypatch.setattr(staged_pipeline.config, "SCREENPLAYS_DIR", str(d))
    return str(d)


def _write_sp(dir_path: str, name: str, sp: dict) -> str:
    p = os.path.join(dir_path, name)
    with open(p, "w") as f:
        json.dump(sp, f, ensure_ascii=False)
    return p


def _minimal_sp() -> dict:
    return {
        "caption": "x #y",
        "scenes": [
            {"duration": 3.0, "background_prompt": "bg",
             "animation_prompt": "motion",
             "lines": [{"text": "やばい", "start": 0.0, "end": 1.0}]},
        ],
    }


# ─── テンプレ (screenplays/ 直下) のロード ───────────────────

def test_load_template_finds_with_or_without_extension(
    fake_screenplays_dir,
) -> None:
    _write_sp(fake_screenplays_dir, "demo.json", _minimal_sp())
    sp = staged_pipeline.load_template("demo")
    assert sp["caption"]
    sp = staged_pipeline.load_template("demo.json")
    assert sp["caption"]


def test_load_template_does_not_look_into_drafts(
    fake_screenplays_dir,
) -> None:
    """drafts/canonical 二層モデルは廃止。drafts/ サブディレクトリは無視される。"""
    drafts_dir = os.path.join(fake_screenplays_dir, "drafts")
    os.makedirs(drafts_dir)
    _write_sp(drafts_dir, "demo.json", {"caption": "from drafts (legacy)",
                                          "scenes": []})
    with pytest.raises(FileNotFoundError):
        staged_pipeline.load_template("demo")


def test_load_template_screenplays_root_only(fake_screenplays_dir) -> None:
    canonical = _minimal_sp()
    canonical["caption"] = "from root"
    _write_sp(fake_screenplays_dir, "demo.json", canonical)
    # drafts/ にファイルがあっても無視
    drafts_dir = os.path.join(fake_screenplays_dir, "drafts")
    os.makedirs(drafts_dir)
    _write_sp(drafts_dir, "demo.json", {"caption": "ignored", "scenes": []})

    assert staged_pipeline.load_template("demo")["caption"] == "from root"


# ─── project snapshot (temp/<TS>/screenplay.json) ────────────

def test_run_script_writes_snapshot_and_metadata(
    fake_screenplays_dir, tmp_path,
) -> None:
    _write_sp(fake_screenplays_dir, "demo.json", _minimal_sp())
    sp = staged_pipeline.load_template("demo")
    ts_path = str(tmp_path / "ts1")
    os.makedirs(ts_path)
    staged_pipeline.run_script(sp, "demo", ts_path)

    assert progress_store.is_generated(ts_path, "script")
    snap = staged_pipeline.project_screenplay_path(ts_path)
    assert os.path.exists(snap)
    # snapshot は与えた sp と一致
    assert staged_pipeline.load_project_screenplay(ts_path)["caption"] == sp["caption"]
    # metadata は新フォーマット
    meta = staged_pipeline.read_metadata(ts_path)
    assert meta["screenplay_path"] == "screenplay.json"
    assert meta["screenplay_template_name"] == "demo"
    assert meta["screenplay_sha256"]


def test_save_project_screenplay_updates_metadata_sha(
    fake_screenplays_dir, tmp_path,
) -> None:
    _write_sp(fake_screenplays_dir, "demo.json", _minimal_sp())
    sp = staged_pipeline.load_template("demo")
    ts_path = str(tmp_path / "ts1b")
    os.makedirs(ts_path)
    staged_pipeline.run_script(sp, "demo", ts_path)
    sha_before = staged_pipeline.read_metadata(ts_path)["screenplay_sha256"]

    sp["caption"] = "edited via UI"
    staged_pipeline.save_project_screenplay(ts_path, sp)
    sha_after = staged_pipeline.read_metadata(ts_path)["screenplay_sha256"]
    assert sha_after != sha_before
    assert (
        staged_pipeline.load_project_screenplay(ts_path)["caption"]
        == "edited via UI"
    )


def test_project_snapshot_isolated_from_template_changes(
    fake_screenplays_dir, tmp_path,
) -> None:
    """template が外部で書き換わっても、project snapshot は不変であること。
    これが drafts/canonical 撤廃の核心ガード。
    """
    template_path = _write_sp(fake_screenplays_dir, "demo.json", _minimal_sp())
    sp = staged_pipeline.load_template("demo")
    ts_path = str(tmp_path / "tsiso")
    os.makedirs(ts_path)
    staged_pipeline.run_script(sp, "demo", ts_path)

    # template を別 scene 数で上書き
    new_template = _minimal_sp()
    new_template["scenes"].append({
        "duration": 3.0, "background_prompt": "bg2",
        "animation_prompt": "motion2",
        "lines": [{"text": "新規", "start": 0.0, "end": 1.0}],
    })
    with open(template_path, "w") as f:
        json.dump(new_template, f, ensure_ascii=False)

    # project snapshot は書き換わっていない
    snap = staged_pipeline.load_project_screenplay(ts_path)
    assert len(snap["scenes"]) == 1


# ─── stage runners ────────────────────────────────────────────

def test_run_tts_blocks_when_script_unapproved(
    fake_screenplays_dir, tmp_path,
) -> None:
    _write_sp(fake_screenplays_dir, "demo.json", _minimal_sp())
    sp = staged_pipeline.load_template("demo")
    ts_path = str(tmp_path / "ts2")
    os.makedirs(ts_path)
    staged_pipeline.run_script(sp, "demo", ts_path)
    with pytest.raises(RuntimeError, match="未承認"):
        staged_pipeline.run_tts(sp, ts_path)


def test_run_next_stage_advances_step_by_step(
    fake_screenplays_dir, tmp_path, monkeypatch,
) -> None:
    _write_sp(fake_screenplays_dir, "demo.json", _minimal_sp())
    sp = staged_pipeline.load_template("demo")
    ts_path = str(tmp_path / "ts3")
    os.makedirs(ts_path)

    # 重い処理 (TTS / kling / scene) を mock でスキップ
    monkeypatch.setattr(
        staged_pipeline.scene_gen, "generate_backgrounds",
        lambda screenplay, td: {f"bg_{i:03d}": "" for i in range(len(screenplay["scenes"]))},
    )
    monkeypatch.setattr(
        staged_pipeline.scene_gen, "generate_kling_for_screenplay",
        lambda screenplay, td, **_kw: None,
    )
    monkeypatch.setattr(
        staged_pipeline.scene_gen, "assemble_scene_videos",
        lambda screenplay, td: [],
    )
    executed = staged_pipeline.run_next_stage(sp, "demo", ts_path)
    assert executed == "script"
    assert progress_store.next_stage(ts_path) is None  # 未承認でブロック

    progress_store.mark_approved(ts_path, "script")
    executed = staged_pipeline.run_next_stage(sp, "demo", ts_path)
    assert executed == "tts"


def test_regen_increments_count(fake_screenplays_dir, tmp_path, monkeypatch) -> None:
    _write_sp(fake_screenplays_dir, "demo.json", _minimal_sp())
    sp = staged_pipeline.load_template("demo")
    ts_path = str(tmp_path / "ts4")
    os.makedirs(ts_path)
    progress_store.mark_generated(ts_path, "tts")

    monkeypatch.setattr(staged_pipeline.scene_gen, "regen_tts_line", MagicMock())
    staged_pipeline.regen("tts", sp, ts_path, scene_idx=0, line_idx=0)
    p = progress_store.load(ts_path)
    assert p["stages"]["tts"]["regen_count"] == 1
    assert not progress_store.is_approved(ts_path, "tts")
