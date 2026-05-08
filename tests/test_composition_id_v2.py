"""Phase X-2a: composition_id v2 (action_id 取り込み) のテスト。"""
from __future__ import annotations

import pytest

import composition_id


def test_resolve_version_v1_without_action_id():
    assert composition_id.resolve_version(action_id=None) == "v1"
    assert composition_id.resolve_version(action_id="") == "v1"


def test_resolve_version_v2_with_action_id():
    assert composition_id.resolve_version(action_id="surprise_pc") == "v2"


def test_v2_includes_action_id_in_hash():
    a = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["f1"],
        action_id="surprise_pc", version="v2",
    )
    b = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["f1"],
        action_id="decisive_stand", version="v2",
    )
    assert a != b


def test_v1_ignores_action_id_argument():
    """v1 で action_id を渡しても無視される (= back-compat)。"""
    a = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["f1"],
    )
    b = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["f1"],
        action_id="surprise_pc", version="v1",
    )
    assert a == b


def test_v1_and_v2_yield_different_hashes_for_same_scene():
    """同じ scene でも v1 と v2 では hash が違う (= 衝突しない設計)。"""
    a = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["f1"],
        version="v1",
    )
    b = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["f1"],
        action_id="", version="v2",
    )
    assert a != b


def test_v2_deterministic_same_input_same_output():
    a = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["f1__office"],
        action_id="surprise_pc", version="v2",
    )
    b = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["f1__office"],
        action_id="surprise_pc", version="v2",
    )
    assert a == b


def test_unknown_version_raises():
    with pytest.raises(ValueError, match="unknown composition version"):
        composition_id.compute_composition_id(
            location_ref="home_office", character_refs=["f1"],
            version="v99",
        )


def test_composition_version_v2_constant():
    assert composition_id.COMPOSITION_VERSION_V2 == "v2"
