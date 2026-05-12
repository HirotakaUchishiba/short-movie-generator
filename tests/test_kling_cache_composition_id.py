"""Phase X-1: scene_gen._build_kling_cache_meta が composition_id を埋めるテスト。"""
from __future__ import annotations

import composition_id
from scene_gen import _build_bg_cache_meta, _build_kling_cache_meta


def _kling_inputs(augmented="anim", duration=5, bg_sha="bg_abc",
                  model="kling-v3", final_dur=4.5):
    return {
        "augmented_prompt": augmented,
        "kling_duration": duration,
        "bg_image_sha": bg_sha,
        "model_id": model,
        "final_duration": final_dur,
    }


def test_kling_cache_meta_includes_composition_id():
    scene = {
        "identity": {
            "location_ref": "home_office",
            "character_refs": ["f1__office"],
            "camera_distance": "medium",
        },
    }
    meta = _build_kling_cache_meta(scene, _kling_inputs())

    assert "composition_id" in meta
    assert "composition_version" in meta
    assert meta["composition_version"] == "v1"
    assert len(meta["composition_id"]) == 16


def test_kling_cache_meta_matches_helper():
    scene = {
        "identity": {
            "location_ref": "office_desk",
            "character_refs": ["f2__office"],
        },
    }
    meta = _build_kling_cache_meta(scene, _kling_inputs())
    expected = composition_id.compute_composition_id(
        location_ref="office_desk", character_refs=["f2__office"],
    )
    assert meta["composition_id"] == expected


def test_kling_cache_meta_matches_bg_cache_for_same_scene():
    """同じ scene なら bg と kling の composition_id は一致する。"""
    scene = {
        "identity": {
            "location_ref": "cafe_window",
            "character_refs": ["m1__casual"],
        },
    }
    bg_meta = _build_bg_cache_meta(
        scene, scene_idx=0,
        inputs={"model_id": "imagen", "background_prompt_resolved": "x"},
    )
    kling_meta = _build_kling_cache_meta(scene, _kling_inputs())
    assert bg_meta["composition_id"] == kling_meta["composition_id"]


def test_kling_cache_meta_existing_fields_preserved():
    scene = {
        "identity": {
            "location_ref": "office_desk",
            "character_refs": ["f2"],
        },
    }
    meta = _build_kling_cache_meta(
        scene,
        _kling_inputs(augmented="subject leans forward",
                      duration=5, bg_sha="bg_xyz", model="kling-v3",
                      final_dur=4.0),
    )
    assert meta["augmented_animation_prompt"] == "subject leans forward"
    assert meta["kling_duration"] == 5
    assert meta["bg_image_sha"] == "bg_xyz"
    assert meta["model_id"] == "kling-v3"
    assert meta["aspect_ratio"] == "9:16"
    assert meta["original_audio_duration"] == 4.0
    assert meta["location_ref"] == "office_desk"
    assert meta["character_refs"] == ["f2"]
