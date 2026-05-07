import pytest

import progress_store


def test_load_empty_returns_default(tmp_path) -> None:
    p = progress_store.load(str(tmp_path))
    assert set(p["stages"].keys()) == set(progress_store.STAGES)
    for stage in progress_store.STAGES:
        assert p["stages"][stage]["generated_at"] is None
        assert p["stages"][stage]["approved_at"] is None


def test_mark_generated_sets_timestamp(tmp_path) -> None:
    progress_store.mark_generated(str(tmp_path), "tts")
    p = progress_store.load(str(tmp_path))
    assert p["stages"]["tts"]["generated_at"]
    assert p["stages"]["tts"]["approved_at"] is None


def test_mark_approved_after_generated(tmp_path) -> None:
    progress_store.mark_generated(str(tmp_path), "tts")
    progress_store.mark_approved(str(tmp_path), "tts")
    assert progress_store.is_approved(str(tmp_path), "tts")


def test_mark_approved_before_generated_fails(tmp_path) -> None:
    with pytest.raises(ValueError, match="not generated"):
        progress_store.mark_approved(str(tmp_path), "tts")


def test_unknown_stage_fails(tmp_path) -> None:
    with pytest.raises(ValueError, match="unknown stage"):
        progress_store.mark_generated(str(tmp_path), "bogus")


def test_next_stage_returns_first_ungenerated(tmp_path) -> None:
    assert progress_store.next_stage(str(tmp_path)) == "script"
    progress_store.mark_generated(str(tmp_path), "script")
    progress_store.mark_approved(str(tmp_path), "script")
    assert progress_store.next_stage(str(tmp_path)) == "tts"


def test_next_stage_blocks_when_unapproved(tmp_path) -> None:
    progress_store.mark_generated(str(tmp_path), "script")
    assert progress_store.next_stage(str(tmp_path)) is None


def test_current_stage_returns_unapproved(tmp_path) -> None:
    progress_store.mark_generated(str(tmp_path), "script")
    assert progress_store.current_stage(str(tmp_path)) == "script"


def test_increment_regen_resets_approval(tmp_path) -> None:
    progress_store.mark_generated(str(tmp_path), "tts")
    progress_store.mark_approved(str(tmp_path), "tts")
    progress_store.increment_regen(str(tmp_path), "tts")
    assert not progress_store.is_approved(str(tmp_path), "tts")
    p = progress_store.load(str(tmp_path))
    assert p["stages"]["tts"]["regen_count"] == 1


def test_reset_stage_clears_self_and_following(tmp_path) -> None:
    for s in ["script", "tts", "bg"]:
        progress_store.mark_generated(str(tmp_path), s)
        progress_store.mark_approved(str(tmp_path), s)
    progress_store.reset_stage(str(tmp_path), "tts")
    assert progress_store.is_approved(str(tmp_path), "script")
    assert not progress_store.is_generated(str(tmp_path), "tts")
    assert not progress_store.is_generated(str(tmp_path), "bg")


def test_all_stages_complete_returns_none(tmp_path) -> None:
    for s in progress_store.STAGES:
        progress_store.mark_generated(str(tmp_path), s)
        progress_store.mark_approved(str(tmp_path), s)
    assert progress_store.next_stage(str(tmp_path)) is None
    assert progress_store.current_stage(str(tmp_path)) is None


def test_revoke_all_approvals_keeps_generated(tmp_path) -> None:
    """Stage 1「素材編集」で再合成した時に呼ぶ関数。承認だけ消えて assets は残る。"""
    for s in progress_store.STAGES:
        progress_store.mark_generated(str(tmp_path), s)
        progress_store.mark_approved(str(tmp_path), s)
    progress_store.revoke_all_approvals(str(tmp_path))
    p = progress_store.load(str(tmp_path))
    for s in progress_store.STAGES:
        assert p["stages"][s]["approved_at"] is None
        # generated_at (= asset 生成済みフラグ) は保持される
        assert p["stages"][s]["generated_at"] is not None
    # next_stage は最初の未承認 = script で停止
    assert progress_store.current_stage(str(tmp_path)) == "script"


def _approve_through(ts_path: str, last_stage: str) -> None:
    for s in progress_store._CASCADE_STAGES:
        progress_store.mark_generated(ts_path, s)
        progress_store.mark_approved(ts_path, s)
        if s == last_stage:
            return


def test_cascade_reset_after_bg_clears_kling_scene_overlay(tmp_path) -> None:
    ts = str(tmp_path)
    _approve_through(ts, "overlay")
    reset = progress_store.cascade_reset_after(ts, "bg")
    assert reset == ["kling", "scene", "overlay"]
    p = progress_store.load(ts)
    # bg より前 (script / tts) と bg 自身は不変
    assert p["stages"]["script"]["approved_at"] is not None
    assert p["stages"]["tts"]["approved_at"] is not None
    assert p["stages"]["bg"]["approved_at"] is not None
    # 後続は approved_at だけ None、generated_at は保持
    for s in ("kling", "scene", "overlay"):
        assert p["stages"][s]["approved_at"] is None
        assert p["stages"][s]["generated_at"] is not None


def test_cascade_reset_after_overlay_is_noop(tmp_path) -> None:
    ts = str(tmp_path)
    _approve_through(ts, "overlay")
    reset = progress_store.cascade_reset_after(ts, "overlay")
    assert reset == []
    p = progress_store.load(ts)
    for s in progress_store._CASCADE_STAGES:
        assert p["stages"][s]["approved_at"] is not None


def test_cascade_reset_after_script_clears_all_following(tmp_path) -> None:
    ts = str(tmp_path)
    _approve_through(ts, "overlay")
    reset = progress_store.cascade_reset_after(ts, "script")
    assert reset == ["tts", "bg", "kling", "scene", "overlay"]
    p = progress_store.load(ts)
    assert p["stages"]["script"]["approved_at"] is not None
    for s in ("tts", "bg", "kling", "scene", "overlay"):
        assert p["stages"][s]["approved_at"] is None
        assert p["stages"][s]["generated_at"] is not None


def test_cascade_reset_after_idempotent_when_unapproved(tmp_path) -> None:
    ts = str(tmp_path)
    # bg まで承認、後続は未生成
    _approve_through(ts, "bg")
    reset = progress_store.cascade_reset_after(ts, "bg")
    assert reset == []
    # 二度目も例外なし
    reset2 = progress_store.cascade_reset_after(ts, "bg")
    assert reset2 == []


def test_cascade_reset_after_excludes_external_stages(tmp_path) -> None:
    """final_import / publish は外部アクション起点なので chain に含めない。"""
    ts = str(tmp_path)
    _approve_through(ts, "overlay")
    progress_store.mark_generated(ts, "final_import")
    progress_store.mark_approved(ts, "final_import")
    progress_store.cascade_reset_after(ts, "overlay")
    p = progress_store.load(ts)
    assert p["stages"]["final_import"]["approved_at"] is not None


def test_cascade_reset_after_unknown_stage_fails(tmp_path) -> None:
    with pytest.raises(ValueError, match="cascade 対象外"):
        progress_store.cascade_reset_after(str(tmp_path), "final_import")
    with pytest.raises(ValueError, match="cascade 対象外"):
        progress_store.cascade_reset_after(str(tmp_path), "bogus")
