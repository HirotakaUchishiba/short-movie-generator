"""analyze.intent_resolver のユニットテスト。

設計 doc: docs/plannings/2026-05-10_compositional-architecture.md §8
"""

from __future__ import annotations

from pathlib import Path

import pytest

from analyze.intent_resolver import (
    IntentEntry,
    NovelIntentCandidate,
    SceneIntentAssignment,
    detect_novel_intent_candidates,
    format_catalog_for_prompt,
    load_intent_catalog,
    parse_intent_assignment,
)


# ───────────── load_intent_catalog ─────────────


class TestLoadIntentCatalog:
    def test_loads_real_yaml(self) -> None:
        # 本番 yaml が読めて、talking_head_calm 等が入っているはず
        catalog = load_intent_catalog()
        ids = {e.id for e in catalog}
        assert "talking_head_calm" in ids
        assert "reaction_surprise" in ids

    def test_filters_deprecated(self, tmp_path: Path) -> None:
        yaml_text = """
version: 1
parts:
  - id: alive
    description: still here
    valid_start_emotions: [中立]
    duration_buckets: [5]
    motion_intensity_bucket: low
    deprecated: false
  - id: dead
    description: gone
    valid_start_emotions: [中立]
    duration_buckets: [5]
    motion_intensity_bucket: low
    deprecated: true
"""
        p = tmp_path / "visual_intents.yaml"
        p.write_text(yaml_text)
        catalog = load_intent_catalog(p)
        ids = {e.id for e in catalog}
        assert ids == {"alive"}

    def test_missing_yaml_returns_empty(self, tmp_path: Path) -> None:
        catalog = load_intent_catalog(tmp_path / "nope.yaml")
        assert catalog == []


# ───────────── format_catalog_for_prompt ─────────────


class TestFormatCatalog:
    def test_includes_id_and_description(self) -> None:
        catalog = [
            IntentEntry(
                id="talking_head_calm",
                description="Subject talks calmly to camera.",
                valid_start_emotions=("中立", "喜び"),
                duration_buckets=(5, 10),
                motion_intensity_bucket="low",
                compatible_with=(),
            )
        ]
        text = format_catalog_for_prompt(catalog)
        assert "talking_head_calm" in text
        assert "中立/喜び" in text
        assert "Subject talks calmly" in text

    def test_empty_catalog_message(self) -> None:
        text = format_catalog_for_prompt([])
        assert "(none defined)" in text


# ───────────── parse_intent_assignment ─────────────


class TestParseIntent:
    def _catalog(self) -> list[IntentEntry]:
        return [
            IntentEntry(
                id="talking_head_calm",
                description="x",
                valid_start_emotions=("中立",),
                duration_buckets=(5,),
                motion_intensity_bucket="low",
                compatible_with=(),
            )
        ]

    def test_parses_well_formed_response(self) -> None:
        raw = [
            {
                "scene_idx": 0,
                "visual_intent_id": "talking_head_calm",
                "confidence": 0.92,
                "start_emotion": "中立",
                "duration_bucket": 5,
                "motion_intensity": "low",
                "rationale": "matches",
            },
        ]
        out = parse_intent_assignment(raw, catalog=self._catalog())
        assert len(out) == 1
        assert out[0].scene_idx == 0
        assert out[0].visual_intent_id == "talking_head_calm"
        assert out[0].confidence == 0.92
        assert out[0].start_emotion == "中立"
        assert out[0].duration_bucket == 5

    def test_demotes_unknown_intent_id(self) -> None:
        raw = [
            {
                "scene_idx": 0,
                "visual_intent_id": "ghost_intent",
                "confidence": 0.95,
            }
        ]
        out = parse_intent_assignment(raw, catalog=self._catalog())
        assert out[0].visual_intent_id is None  # unknown → demoted

    def test_low_confidence_flag(self) -> None:
        raw = [
            {
                "scene_idx": 0,
                "visual_intent_id": None,
                "confidence": 0.4,
            }
        ]
        out = parse_intent_assignment(raw)
        assert out[0].is_low_confidence

    def test_skips_malformed_entries(self) -> None:
        raw = [
            "not_a_dict",
            {"scene_idx": "x"},  # invalid type
            {"scene_idx": 0, "confidence": "x"},  # invalid type
            {"scene_idx": 1, "visual_intent_id": "talking_head_calm", "confidence": 0.9},
        ]
        out = parse_intent_assignment(raw, catalog=self._catalog())
        assert len(out) == 1
        assert out[0].scene_idx == 1

    def test_non_list_input_returns_empty(self) -> None:
        assert parse_intent_assignment({"not": "list"}) == []
        assert parse_intent_assignment(None) == []


# ───────────── detect_novel_intent_candidates ─────────────


class TestDetectNovel:
    def test_no_candidates_when_all_resolved(self) -> None:
        assignments = [
            SceneIntentAssignment(0, "talking_head_calm", 0.9),
            SceneIntentAssignment(1, "talking_head_calm", 0.95),
        ]
        assert detect_novel_intent_candidates(assignments) == []

    def test_streak_of_unresolved_yields_candidate(self) -> None:
        assignments = [
            SceneIntentAssignment(0, "talking_head_calm", 0.9),
            SceneIntentAssignment(
                1, None, 0.4, rationale="subject is gardening with tools"
            ),
            SceneIntentAssignment(
                2, None, 0.3, rationale="subject is gardening with tools"
            ),
            SceneIntentAssignment(3, "talking_head_calm", 0.85),
        ]
        cands = detect_novel_intent_candidates(assignments, min_streak=2)
        assert len(cands) == 1
        assert cands[0].scene_indices == (1, 2)
        assert "gardening" in cands[0].description

    def test_min_streak_threshold(self) -> None:
        # 1 件だけの不一致は候補にしない
        assignments = [
            SceneIntentAssignment(0, "talking_head_calm", 0.9),
            SceneIntentAssignment(1, None, 0.4, rationale="anomaly"),
            SceneIntentAssignment(2, "talking_head_calm", 0.9),
        ]
        cands = detect_novel_intent_candidates(assignments, min_streak=2)
        assert cands == []

    def test_multiple_streaks(self) -> None:
        assignments = [
            SceneIntentAssignment(0, None, 0.4, rationale="A"),
            SceneIntentAssignment(1, None, 0.4, rationale="A"),
            SceneIntentAssignment(2, "talking_head_calm", 0.9),
            SceneIntentAssignment(3, None, 0.3, rationale="B"),
            SceneIntentAssignment(4, None, 0.3, rationale="B"),
        ]
        cands = detect_novel_intent_candidates(assignments, min_streak=2)
        assert len(cands) == 2
        assert cands[0].scene_indices == (0, 1)
        assert cands[1].scene_indices == (3, 4)
