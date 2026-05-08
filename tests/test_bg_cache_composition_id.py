"""Phase X-1: scene_gen._build_bg_cache_meta が composition_id を埋めるテスト。"""
from __future__ import annotations

import composition_id
from scene_gen import _build_bg_cache_meta


def _inputs(model_id="imagen-test", prompt="test prompt"):
    return {"model_id": model_id, "background_prompt_resolved": prompt}


def test_bg_cache_meta_includes_composition_id():
    scene = {
        "location_ref": "home_office",
        "character_refs": ["f1__office"],
        "camera_distance": "medium-close",
    }
    meta = _build_bg_cache_meta(scene, scene_idx=0, inputs=_inputs())

    assert "composition_id" in meta
    assert "composition_version" in meta
    assert meta["composition_version"] == "v1"
    assert len(meta["composition_id"]) == 16


def test_bg_cache_meta_composition_id_matches_helper():
    scene = {
        "location_ref": "home_office",
        "character_refs": ["f1__office"],
    }
    meta = _build_bg_cache_meta(scene, scene_idx=0, inputs=_inputs())
    expected = composition_id.compute_composition_id(
        location_ref="home_office", character_refs=["f1__office"],
    )
    assert meta["composition_id"] == expected


def test_bg_cache_meta_handles_missing_location():
    scene = {"location_ref": None, "character_refs": ["f1"]}
    meta = _build_bg_cache_meta(scene, scene_idx=0, inputs=_inputs())
    assert len(meta["composition_id"]) == 16


def test_bg_cache_meta_character_refs_order_independent():
    scene_a = {
        "location_ref": "home_office",
        "character_refs": ["f1", "m1"],
    }
    scene_b = {
        "location_ref": "home_office",
        "character_refs": ["m1", "f1"],
    }
    meta_a = _build_bg_cache_meta(scene_a, scene_idx=0, inputs=_inputs())
    meta_b = _build_bg_cache_meta(scene_b, scene_idx=0, inputs=_inputs())
    assert meta_a["composition_id"] == meta_b["composition_id"]


def test_bg_cache_meta_existing_fields_preserved():
    """既存フィールドが v1 追加で潰れていないこと。"""
    scene = {
        "location_ref": "home_office",
        "character_refs": ["f1"],
        "camera_distance": "wide",
    }
    meta = _build_bg_cache_meta(
        scene, scene_idx=3,
        inputs=_inputs(model_id="imagen-x", prompt="foo bar"),
    )
    assert meta["scene_idx"] == 3
    assert meta["model"] == "imagen-x"
    assert meta["model_id"] == "imagen-x"
    assert meta["background_prompt_resolved"] == "foo bar"
    assert meta["location_ref"] == "home_office"
    assert meta["character_refs"] == ["f1"]
    assert meta["camera_distance"] == "wide"
