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


def test_load_screenplay_finds_with_or_without_extension(fake_screenplays_dir) -> None:
    _write_sp(fake_screenplays_dir, "demo.json", _minimal_sp())
    sp = staged_pipeline.load_screenplay("demo")
    assert sp["caption"]
    sp = staged_pipeline.load_screenplay("demo.json")
    assert sp["caption"]


def test_save_screenplay_writes_back(fake_screenplays_dir) -> None:
    _write_sp(fake_screenplays_dir, "demo.json", _minimal_sp())
    sp = staged_pipeline.load_screenplay("demo")
    sp["caption"] = "updated"
    staged_pipeline.save_screenplay("demo", sp)
    sp2 = staged_pipeline.load_screenplay("demo")
    assert sp2["caption"] == "updated"


def test_run_script_marks_progress(fake_screenplays_dir, tmp_path) -> None:
    _write_sp(fake_screenplays_dir, "demo.json", _minimal_sp())
    sp = staged_pipeline.load_screenplay("demo")
    ts_path = str(tmp_path / "ts1")
    os.makedirs(ts_path)
    staged_pipeline.run_script(sp, "demo", ts_path)
    assert progress_store.is_generated(ts_path, "script")
    assert os.path.exists(os.path.join(ts_path, "metadata.json"))


def test_run_tts_blocks_when_script_unapproved(fake_screenplays_dir, tmp_path) -> None:
    _write_sp(fake_screenplays_dir, "demo.json", _minimal_sp())
    sp = staged_pipeline.load_screenplay("demo")
    ts_path = str(tmp_path / "ts2")
    os.makedirs(ts_path)
    staged_pipeline.run_script(sp, "demo", ts_path)
    with pytest.raises(RuntimeError, match="未承認"):
        staged_pipeline.run_tts(sp, ts_path)


def test_run_next_stage_advances_step_by_step(
    fake_screenplays_dir, tmp_path, monkeypatch
) -> None:
    _write_sp(fake_screenplays_dir, "demo.json", _minimal_sp())
    sp = staged_pipeline.load_screenplay("demo")
    ts_path = str(tmp_path / "ts3")
    os.makedirs(ts_path)

    # silent mode で TTS / kling / scene の重い処理をスキップ
    sp["audio_mode"] = "silent"
    monkeypatch.setattr(
        staged_pipeline.scene_gen, "generate_backgrounds",
        lambda screenplay, td: {f"bg_{i:03d}": "" for i in range(len(screenplay["scenes"]))},
    )
    monkeypatch.setattr(
        staged_pipeline.scene_gen, "generate_kling_for_screenplay",
        lambda screenplay, td: None,
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
    sp = staged_pipeline.load_screenplay("demo")
    ts_path = str(tmp_path / "ts4")
    os.makedirs(ts_path)
    progress_store.mark_generated(ts_path, "tts")

    monkeypatch.setattr(staged_pipeline.scene_gen, "regen_tts_line", MagicMock())
    staged_pipeline.regen("tts", sp, ts_path, scene_idx=0, line_idx=0)
    p = progress_store.load(ts_path)
    assert p["stages"]["tts"]["regen_count"] == 1
    assert not progress_store.is_approved(ts_path, "tts")
