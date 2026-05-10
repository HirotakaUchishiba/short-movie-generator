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


def test_init_pending_metadata_omits_screenplay_fields(tmp_path) -> None:
    """Stage 0 init: snapshot 未作成なので screenplay_* は dict に書かれない。"""
    ts_path = str(tmp_path / "pending")
    staged_pipeline.init_pending_metadata(ts_path, "analyze_xyz")
    meta = staged_pipeline.read_metadata(ts_path)
    assert meta["analyze_job_id"] == "analyze_xyz"
    assert meta["created_at"]
    assert "screenplay_name" not in meta
    assert "screenplay_template_name" not in meta
    assert "screenplay_path" not in meta
    assert "screenplay_sha256" not in meta


def test_update_metadata_after_analyze_preserves_existing(tmp_path) -> None:
    """save hook: init で書いた analyze_job_id / created_at は維持。"""
    ts_path = str(tmp_path / "afterhook")
    staged_pipeline.init_pending_metadata(ts_path, "analyze_xyz")
    created_at_before = staged_pipeline.read_metadata(ts_path)["created_at"]

    staged_pipeline.update_metadata_after_analyze(
        ts_path, "auto_abc.json", "sha_deadbeef",
    )
    meta = staged_pipeline.read_metadata(ts_path)
    assert meta["analyze_job_id"] == "analyze_xyz"
    assert meta["created_at"] == created_at_before
    assert meta["screenplay_name"] == "auto_abc.json"
    assert meta["screenplay_template_name"] == "auto_abc.json"
    assert meta["screenplay_path"] == "screenplay.json"
    assert meta["screenplay_sha256"] == "sha_deadbeef"


def test_write_metadata_nullable_screenplay_name(tmp_path) -> None:
    """write_metadata(screenplay_name=None) は screenplay_* を書かず、
    後で str を渡し直すと埋められる (= retry endpoint の atomic 書き直し用)。
    """
    ts_path = str(tmp_path / "nullable")
    os.makedirs(ts_path)
    staged_pipeline.write_metadata(
        ts_path, screenplay_name=None,
        analyze_job_id="analyze_1", sha256=None,
    )
    meta = staged_pipeline.read_metadata(ts_path)
    assert "screenplay_name" not in meta
    # str に切り替えて再書き込み: screenplay_* が dict に入る
    staged_pipeline.write_metadata(
        ts_path, screenplay_name="auto_x.json",
        analyze_job_id="analyze_1", sha256="sha_aaa",
    )
    meta2 = staged_pipeline.read_metadata(ts_path)
    assert meta2["screenplay_name"] == "auto_x.json"
    assert meta2["screenplay_sha256"] == "sha_aaa"


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
    # TTS one-shot は実 ElevenLabs API を叩くので CI / dummy key 環境では
    # 401 になる。本テストは dispatcher の進行検証なので no-op スタブで十分。
    monkeypatch.setattr(
        staged_pipeline.scene_gen, "generate_screenplay_tts_one_shot",
        lambda screenplay, ts_path: None,
    )
    monkeypatch.setattr(
        staged_pipeline.scene_gen, "generate_tts_for_screenplay",
        lambda screenplay, td: None,
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
    monkeypatch.setattr(staged_pipeline.scene_gen, "regen_tts_full", MagicMock())
    staged_pipeline.regen("tts", sp, ts_path, scene_idx=0, line_idx=0)
    p = progress_store.load(ts_path)
    assert p["stages"]["tts"]["regen_count"] == 1
    assert not progress_store.is_approved(ts_path, "tts")


def _approve_all_internal(ts_path: str) -> None:
    for s in ["script", "tts", "bg", "kling", "scene", "overlay"]:
        progress_store.mark_generated(ts_path, s)
        progress_store.mark_approved(ts_path, s)


def test_regen_bg_cascades_kling_scene_overlay(
    fake_screenplays_dir, tmp_path, monkeypatch,
) -> None:
    _write_sp(fake_screenplays_dir, "demo.json", _minimal_sp())
    sp = staged_pipeline.load_template("demo")
    ts_path = str(tmp_path / "ts_bg")
    os.makedirs(ts_path)
    _approve_all_internal(ts_path)

    monkeypatch.setattr(
        staged_pipeline.scene_gen, "regen_background_scene", MagicMock())
    staged_pipeline.regen("bg", sp, ts_path, scene_idx=0)

    # 自身は increment_regen で approved_at None
    assert not progress_store.is_approved(ts_path, "bg")
    # 後続 (kling / scene / overlay) も承認解除
    assert not progress_store.is_approved(ts_path, "kling")
    assert not progress_store.is_approved(ts_path, "scene")
    assert not progress_store.is_approved(ts_path, "overlay")
    # 上流 (script / tts) は維持
    assert progress_store.is_approved(ts_path, "script")
    assert progress_store.is_approved(ts_path, "tts")
    # artifact (= generated_at) は保持
    p = progress_store.load(ts_path)
    for s in ("kling", "scene", "overlay"):
        assert p["stages"][s]["generated_at"] is not None


def test_regen_kling_cascades_scene_overlay(
    fake_screenplays_dir, tmp_path, monkeypatch,
) -> None:
    _write_sp(fake_screenplays_dir, "demo.json", _minimal_sp())
    sp = staged_pipeline.load_template("demo")
    ts_path = str(tmp_path / "ts_kling")
    os.makedirs(ts_path)
    _approve_all_internal(ts_path)

    monkeypatch.setattr(
        staged_pipeline.scene_gen, "regen_kling_scene", MagicMock())
    staged_pipeline.regen("kling", sp, ts_path, scene_idx=0)

    assert not progress_store.is_approved(ts_path, "kling")
    assert not progress_store.is_approved(ts_path, "scene")
    assert not progress_store.is_approved(ts_path, "overlay")
    # bg は維持
    assert progress_store.is_approved(ts_path, "bg")


def test_regen_overlay_no_cascade(
    fake_screenplays_dir, tmp_path, monkeypatch,
) -> None:
    _write_sp(fake_screenplays_dir, "demo.json", _minimal_sp())
    sp = staged_pipeline.load_template("demo")
    ts_path = str(tmp_path / "ts_ov")
    os.makedirs(ts_path)
    _approve_all_internal(ts_path)

    monkeypatch.setattr(staged_pipeline, "run_overlay", MagicMock())
    staged_pipeline.regen("overlay", sp, ts_path, screenplay_name="demo")

    # overlay 自身は increment_regen で承認解除
    assert not progress_store.is_approved(ts_path, "overlay")
    # 上流は全部維持 (cascade なし = 最終 stage)
    for s in ("script", "tts", "bg", "kling", "scene"):
        assert progress_store.is_approved(ts_path, s)
