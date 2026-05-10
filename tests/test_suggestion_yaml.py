"""analyze.suggestion_yaml のユニットテスト。

設計 doc: docs/plannings/2026-05-10_intent-suggestion-flow.md §3.1
"""

from __future__ import annotations

from analyze.suggestion_store import IntentSuggestionRecord
from analyze.suggestion_yaml import (
    _guess_motion_intensity,
    _normalize_yaml_id,
    _summarize_rationale,
    render_yaml_snippet,
)


# ───────────── helpers ─────────────


def _record(
    proposed_id: str = "proposed_frantic_typing",
    description: str = "subject types furiously",
    rationale: str = "",
) -> IntentSuggestionRecord:
    return IntentSuggestionRecord(
        id="abc1234567890abc",
        proposed_id=proposed_id,
        description=description,
        rationale=rationale,
        scene_indices=(3, 7),
        source_screenplay="screenplays/auto_x.json",
        source_analyze_job_id="job-x",
        status="accepted",
        dismissed_reason=None,
        occurrences=2,
        created_at="2026-05-10T00:00:00Z",
        updated_at="2026-05-10T00:00:00Z",
    )


# ───────────── _normalize_yaml_id ─────────────


class TestNormalizeYamlId:
    def test_strips_proposed_prefix(self) -> None:
        assert _normalize_yaml_id("proposed_frantic_typing") == "frantic_typing"

    def test_lowercases_and_replaces_invalid_chars(self) -> None:
        assert _normalize_yaml_id("MyIntent!Foo") == "myintent_foo"

    def test_collapses_multiple_underscores(self) -> None:
        assert _normalize_yaml_id("a__b___c") == "a_b_c"

    def test_empty_after_normalize_returns_placeholder(self) -> None:
        assert _normalize_yaml_id("!!!") == "TODO_RENAME_ME"


# ───────────── _guess_motion_intensity ─────────────


class TestGuessMotionIntensity:
    def test_high_for_frantic_keyword(self) -> None:
        assert _guess_motion_intensity("subject runs frantically", "") == "high"

    def test_medium_for_gesture_keyword(self) -> None:
        assert (
            _guess_motion_intensity("", "talking with gestures") == "medium"
        )

    def test_low_default(self) -> None:
        assert _guess_motion_intensity("standing still", "calm") == "low"

    def test_japanese_high_keyword(self) -> None:
        assert _guess_motion_intensity("被写体が走る", "") == "high"


# ───────────── _summarize_rationale ─────────────


class TestSummarizeRationale:
    def test_empty_returns_placeholder(self) -> None:
        out = _summarize_rationale("")
        assert "rationale なし" in out

    def test_collapses_whitespace(self) -> None:
        out = _summarize_rationale("foo\n\n   bar")
        assert "foo bar" in out

    def test_limits_to_max_lines(self) -> None:
        rationale = "一文目。二文目。三文目。四文目。"
        out = _summarize_rationale(rationale, max_lines=2)
        assert "一文目" in out
        assert "二文目" in out
        assert "三文目" not in out


# ───────────── render_yaml_snippet ─────────────


class TestRenderYamlSnippet:
    def test_includes_normalized_id(self) -> None:
        snippet = render_yaml_snippet(_record("proposed_frantic_typing"))
        assert "id: frantic_typing" in snippet

    def test_includes_todo_markers(self) -> None:
        snippet = render_yaml_snippet(_record(rationale="x"))
        assert "TODO" in snippet
        assert "valid_start_emotions: []" in snippet

    def test_motion_inferred_from_rationale(self) -> None:
        snippet = render_yaml_snippet(
            _record(rationale="subject typing rapidly")
        )
        assert "motion_intensity_bucket: high" in snippet

    def test_yaml_is_parseable(self) -> None:
        """生成 snippet が PyYAML で parse 可能 (= comment 等が syntax を壊さない)。"""

        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError:  # pragma: no cover
            return  # PyYAML 未インストール環境では skip
        snippet = render_yaml_snippet(_record(rationale="a normal scene"))
        # snippet 単体は - で始まる list entry。parse 用に dummy wrapper を被せる
        wrapped = "parts:\n" + "\n".join("  " + ln for ln in snippet.splitlines())
        loaded = yaml.safe_load(wrapped)
        assert isinstance(loaded, dict)
        assert isinstance(loaded["parts"], list)
        entry = loaded["parts"][0]
        assert entry["pool_target_size"] == 8
        assert entry["deprecated"] is False
        assert isinstance(entry["valid_start_emotions"], list)

    def test_uses_rationale_for_description(self) -> None:
        snippet = render_yaml_snippet(_record(rationale="a vivid moment"))
        assert "a vivid moment" in snippet
