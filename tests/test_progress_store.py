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
