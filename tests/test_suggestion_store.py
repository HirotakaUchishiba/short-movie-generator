"""analyze.suggestion_store のユニットテスト。

設計 doc: docs/plannings/2026-05-10_intent-suggestion-flow.md §2
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from analyze.suggestion_store import (
    IntentSuggestionRecord,
    SuggestionInput,
    compute_id,
    counts_by_status,
    list_by_status,
    load,
    mark_merged_against_yaml,
    save,
    update_status,
    upsert,
)


# ───────────── compute_id ─────────────


class TestComputeId:
    def test_deterministic_for_same_input(self) -> None:
        a = compute_id("foo", "bar baz")
        b = compute_id("foo", "bar baz")
        assert a == b
        assert len(a) == 16

    def test_strips_description_whitespace(self) -> None:
        a = compute_id("foo", "bar baz")
        b = compute_id("foo", "  bar baz  \n")
        assert a == b

    def test_different_for_different_proposed_id(self) -> None:
        assert compute_id("foo", "x") != compute_id("foo2", "x")

    def test_different_for_different_description(self) -> None:
        assert compute_id("foo", "x") != compute_id("foo", "y")


# ───────────── load / save round-trip ─────────────


def _make_record(
    proposed_id: str = "frantic_typing",
    description: str = "subject types furiously",
    rationale: str = "no good match",
    scene_indices: tuple[int, ...] = (3, 7),
    status: str = "new",
) -> IntentSuggestionRecord:
    sid = compute_id(proposed_id, description)
    return IntentSuggestionRecord(
        id=sid,
        proposed_id=proposed_id,
        description=description,
        rationale=rationale,
        scene_indices=scene_indices,
        source_screenplay="screenplays/auto_test.json",
        source_analyze_job_id="job-test",
        status=status,  # type: ignore[arg-type]
        dismissed_reason=None,
        occurrences=1,
        created_at="2026-05-10T00:00:00Z",
        updated_at="2026-05-10T00:00:00Z",
    )


class TestLoadSaveRoundTrip:
    def test_empty_file_returns_empty_list(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        assert load(p) == []

    def test_save_then_load_preserves_data(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        r = _make_record()
        save([r], p)
        loaded = load(p)
        assert len(loaded) == 1
        assert loaded[0].id == r.id
        assert loaded[0].scene_indices == (3, 7)
        assert loaded[0].proposed_id == "frantic_typing"

    def test_corrupted_file_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        p.write_text("{not valid json", encoding="utf-8")
        assert load(p) == []

    def test_non_list_top_level_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        p.write_text('{"oops": 1}', encoding="utf-8")
        assert load(p) == []

    def test_skips_invalid_entries_keeps_valid(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        valid = _make_record().to_dict()
        # 不正 entry は scene_indices が dict (= list 期待) なので skip される
        invalid = {**valid, "id": "bad", "scene_indices": {"x": 1}}
        p.write_text(json.dumps([valid, invalid]), encoding="utf-8")
        result = load(p)
        assert len(result) == 1
        assert result[0].id == valid["id"]


# ───────────── upsert ─────────────


class TestUpsert:
    def test_insert_new_record(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        out = upsert(
            [
                SuggestionInput(
                    proposed_id="x",
                    description="d",
                    rationale="r",
                    scene_indices=(1, 2),
                    source_screenplay="screenplays/foo.json",
                )
            ],
            p,
        )
        assert len(out) == 1
        assert out[0].status == "new"
        assert out[0].occurrences == 1
        assert out[0].id == compute_id("x", "d")

    def test_dedupe_increments_occurrences(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        inp = SuggestionInput(
            proposed_id="x",
            description="d",
            rationale="r1",
            scene_indices=(1,),
            source_screenplay="screenplays/foo.json",
        )
        upsert([inp], p)
        # 同 id を再度 upsert → occurrences が +1
        upsert(
            [
                SuggestionInput(
                    proposed_id="x",
                    description="d",
                    rationale="r2",
                    scene_indices=(5, 9),
                    source_screenplay="screenplays/bar.json",
                )
            ],
            p,
        )
        out = load(p)
        assert len(out) == 1
        assert out[0].occurrences == 2
        # 最新 source / scene_indices / rationale で上書き
        assert out[0].source_screenplay == "screenplays/bar.json"
        assert out[0].scene_indices == (5, 9)
        assert out[0].rationale == "r2"

    def test_does_not_change_status_on_redetection(self, tmp_path: Path) -> None:
        """dismissed の entry を analyze が再検出しても status は維持される
        (= 自動再浮上を防ぐ)。"""

        p = tmp_path / "inbox.json"
        upsert(
            [
                SuggestionInput(
                    proposed_id="x", description="d", rationale="r",
                    scene_indices=(1,), source_screenplay="screenplays/foo.json",
                )
            ],
            p,
        )
        sid = compute_id("x", "d")
        update_status(sid, "dismissed", reason="duplicate", path=p)
        upsert(
            [
                SuggestionInput(
                    proposed_id="x", description="d", rationale="r",
                    scene_indices=(2,), source_screenplay="screenplays/foo.json",
                )
            ],
            p,
        )
        out = load(p)
        assert out[0].status == "dismissed"
        assert out[0].dismissed_reason == "duplicate"
        assert out[0].occurrences == 2

    def test_empty_inputs_returns_existing(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        upsert(
            [
                SuggestionInput(
                    proposed_id="x", description="d", rationale="r",
                    scene_indices=(1,), source_screenplay="s",
                )
            ],
            p,
        )
        out = upsert([], p)
        assert len(out) == 1


# ───────────── update_status ─────────────


class TestUpdateStatus:
    def test_new_to_reviewing(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        save([_make_record(status="new")], p)
        sid = compute_id("frantic_typing", "subject types furiously")
        result = update_status(sid, "reviewing", path=p)
        assert result.status == "reviewing"
        assert load(p)[0].status == "reviewing"

    def test_dismiss_requires_reason(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        save([_make_record(status="new")], p)
        sid = compute_id("frantic_typing", "subject types furiously")
        with pytest.raises(ValueError, match="non-empty reason"):
            update_status(sid, "dismissed", reason="", path=p)
        with pytest.raises(ValueError, match="non-empty reason"):
            update_status(sid, "dismissed", reason="   ", path=p)
        with pytest.raises(ValueError, match="non-empty reason"):
            update_status(sid, "dismissed", reason=None, path=p)

    def test_dismiss_with_reason_succeeds(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        save([_make_record(status="new")], p)
        sid = compute_id("frantic_typing", "subject types furiously")
        result = update_status(sid, "dismissed", reason="too niche", path=p)
        assert result.status == "dismissed"
        assert result.dismissed_reason == "too niche"

    def test_invalid_transition_dismissed_to_accepted(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "inbox.json"
        save([_make_record(status="dismissed")], p)
        sid = compute_id("frantic_typing", "subject types furiously")
        with pytest.raises(ValueError, match="invalid transition"):
            update_status(sid, "accepted", path=p)

    def test_invalid_transition_new_to_merged(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        save([_make_record(status="new")], p)
        sid = compute_id("frantic_typing", "subject types furiously")
        with pytest.raises(ValueError, match="invalid transition"):
            update_status(sid, "merged", path=p)

    def test_unknown_status_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        save([_make_record(status="new")], p)
        sid = compute_id("frantic_typing", "subject types furiously")
        with pytest.raises(ValueError, match="unknown status"):
            update_status(sid, "garbage", reason="x", path=p)  # type: ignore[arg-type]

    def test_missing_id_raises_keyerror(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        save([_make_record()], p)
        with pytest.raises(KeyError):
            update_status("nonexistent", "reviewing", path=p)


# ───────────── list_by_status / counts_by_status ─────────────


class TestListByStatus:
    def test_filter_each_status(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        save(
            [
                _make_record("a", "d1", status="new"),
                _make_record("b", "d2", status="reviewing"),
                _make_record("c", "d3", status="dismissed"),
            ],
            p,
        )
        assert {r.proposed_id for r in list_by_status("new", p)} == {"a"}
        assert {r.proposed_id for r in list_by_status("reviewing", p)} == {"b"}
        assert {r.proposed_id for r in list_by_status("dismissed", p)} == {"c"}
        assert len(list_by_status("all", p)) == 3

    def test_unknown_filter_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        save([_make_record()], p)
        with pytest.raises(ValueError, match="unknown status filter"):
            list_by_status("garbage", p)


class TestCountsByStatus:
    def test_counts(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        save(
            [
                _make_record("a", "d1", status="new"),
                _make_record("b", "d2", status="new"),
                _make_record("c", "d3", status="accepted"),
            ],
            p,
        )
        c = counts_by_status(p)
        assert c["new"] == 2
        assert c["accepted"] == 1
        assert c["dismissed"] == 0


# ───────────── mark_merged_against_yaml ─────────────


class TestMarkMergedAgainstYaml:
    def test_accepted_with_matching_id_becomes_merged(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "inbox.json"
        save([_make_record("frantic_typing", "d", status="accepted")], p)
        updated = mark_merged_against_yaml({"frantic_typing"}, p)
        assert len(updated) == 1
        assert load(p)[0].status == "merged"

    def test_non_accepted_status_untouched(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        save(
            [
                _make_record("a", "d1", status="new"),
                _make_record("b", "d2", status="reviewing"),
                _make_record("c", "d3", status="dismissed"),
            ],
            p,
        )
        updated = mark_merged_against_yaml({"a", "b", "c"}, p)
        assert updated == []
        statuses = {r.proposed_id: r.status for r in load(p)}
        assert statuses == {"a": "new", "b": "reviewing", "c": "dismissed"}

    def test_no_match_no_changes(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        save([_make_record("frantic_typing", "d", status="accepted")], p)
        updated = mark_merged_against_yaml({"unrelated"}, p)
        assert updated == []
        assert load(p)[0].status == "accepted"

    def test_empty_yaml_ids_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "inbox.json"
        save([_make_record(status="accepted")], p)
        assert mark_merged_against_yaml(set(), p) == []
        assert load(p)[0].status == "accepted"

    def test_inbox_missing_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "no_such.json"
        assert mark_merged_against_yaml({"x"}, p) == []
