"""Phase X-2b: atomic_assets.build_prompt_menu の構造テスト。"""
from __future__ import annotations

import atomic_assets


def test_top_level_keys():
    menu = atomic_assets.build_prompt_menu()
    assert set(menu.keys()) == {"actions", "hooks", "arcs"}
    assert isinstance(menu["actions"], list)
    assert isinstance(menu["hooks"], list)
    assert isinstance(menu["arcs"], list)


def test_action_entry_required_fields():
    menu = atomic_assets.build_prompt_menu()
    assert len(menu["actions"]) >= 5
    for entry in menu["actions"]:
        for key in (
            "id", "label", "recommended_emotion",
            "recommended_camera_distance", "compatible_locations",
            "duration_bucket_sec",
        ):
            assert key in entry, f"action missing key: {key}"


def test_hook_entry_required_fields():
    menu = atomic_assets.build_prompt_menu()
    assert len(menu["hooks"]) >= 5
    for entry in menu["hooks"]:
        for key in (
            "id", "label", "description",
            "first_scene_action_id", "follow_arc_id_candidates",
        ):
            assert key in entry, f"hook missing key: {key}"


def test_arc_entry_required_fields():
    menu = atomic_assets.build_prompt_menu()
    assert len(menu["arcs"]) >= 3
    for entry in menu["arcs"]:
        for key in (
            "id", "label", "description",
            "emotion_sequence", "scene_count_range",
        ):
            assert key in entry, f"arc missing key: {key}"


def test_action_entries_exclude_internal_fields():
    """subject_state / animation_motion は menu に含めない。

    Claude にビジュアル詳細を見せると "似たシーンを自由生成" の方向に逸れて、
    menu の id 選択ではなく独自テキストを書く事故が起きやすい。
    """
    menu = atomic_assets.build_prompt_menu()
    for entry in menu["actions"]:
        assert "subject_state" not in entry
        assert "animation_motion" not in entry


def test_action_ids_match_list_action_ids():
    menu = atomic_assets.build_prompt_menu()
    menu_ids = {a["id"] for a in menu["actions"]}
    assert menu_ids == set(atomic_assets.list_action_ids())


def test_hook_ids_match_list_hook_ids():
    menu = atomic_assets.build_prompt_menu()
    menu_ids = {h["id"] for h in menu["hooks"]}
    assert menu_ids == set(atomic_assets.list_hook_ids())


def test_arc_ids_match_list_arc_ids():
    menu = atomic_assets.build_prompt_menu()
    menu_ids = {a["id"] for a in menu["arcs"]}
    assert menu_ids == set(atomic_assets.list_arc_ids())
