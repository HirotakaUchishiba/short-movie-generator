"""Phase X-1: composition_id.compute_composition_id の単体テスト。"""
from __future__ import annotations

import pytest

import composition_id


def test_basic_returns_16_hex():
    cid = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["f1__office"],
    )
    assert len(cid) == 16
    assert all(c in "0123456789abcdef" for c in cid)


def test_deterministic_same_input_same_output():
    a = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["f1__office", "m1__suit"],
    )
    b = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["f1__office", "m1__suit"],
    )
    assert a == b


def test_character_refs_order_independent():
    """character_refs の順序が変わっても同じ id になる (= sorted で正規化)。"""
    a = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["f1", "m1"],
    )
    b = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["m1", "f1"],
    )
    assert a == b


def test_different_location_yields_different_id():
    a = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["f1"],
    )
    b = composition_id.compute_composition_id(
        location_ref="cafe_window", character_refs=["f1"],
    )
    assert a != b


def test_different_character_yields_different_id():
    a = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["f1"],
    )
    b = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["f2"],
    )
    assert a != b


def test_none_inputs_handled():
    """location_ref=None / character_refs=None でも例外を投げず id が返る。"""
    cid = composition_id.compute_composition_id(
        location_ref=None, character_refs=None,
    )
    assert len(cid) == 16


def test_empty_character_refs_equivalent_to_none():
    a = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=None,
    )
    b = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=[],
    )
    assert a == b


def test_unknown_version_raises():
    with pytest.raises(ValueError, match="unknown composition version"):
        composition_id.compute_composition_id(
            location_ref="home_office", character_refs=["f1"],
            version="v99",
        )


def test_composition_version_v1_constant():
    assert composition_id.COMPOSITION_VERSION_V1 == "v1"
