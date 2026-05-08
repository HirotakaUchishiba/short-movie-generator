"""Phase X-2a: atomic_assets ローダーの単体テスト。

リポジトリ直下の actions/ hooks/ arcs/ にコミットされた手書き SSOT を
ロードできることを確認する。テスト用の一時ディレクトリではなく、実 SSOT を
読む (= locations/ characters/ と同じ慣習)。
"""
from __future__ import annotations

import pytest

import atomic_assets


def test_list_action_ids_includes_handwritten_set():
    ids = set(atomic_assets.list_action_ids())
    assert "surprise_pc" in ids
    assert "decisive_stand" in ids
    assert len(ids) >= 5


def test_list_hook_ids_includes_handwritten_set():
    ids = set(atomic_assets.list_hook_ids())
    assert "paradox_q" in ids
    assert len(ids) >= 5


def test_list_arc_ids_includes_handwritten_set():
    ids = set(atomic_assets.list_arc_ids())
    assert "low_to_high" in ids
    assert len(ids) >= 3


def test_load_action_returns_dict_with_required_fields():
    action = atomic_assets.load_action("surprise_pc")
    assert action["id"] == "surprise_pc"
    for key in (
        "subject_state", "animation_motion",
        "recommended_emotion", "recommended_camera_distance",
        "compatible_locations", "duration_bucket_sec",
    ):
        assert key in action, f"missing key: {key}"


def test_load_hook_returns_dict():
    hook = atomic_assets.load_hook("paradox_q")
    assert hook["id"] == "paradox_q"
    assert "first_scene_template" in hook
    assert "follow_arc_id_candidates" in hook


def test_load_arc_returns_dict():
    arc = atomic_assets.load_arc("low_to_high")
    assert arc["id"] == "low_to_high"
    assert "emotion_sequence" in arc
    assert isinstance(arc["emotion_sequence"], list)
    assert "scene_count_range" in arc


def test_load_action_missing_raises():
    with pytest.raises(atomic_assets.AtomicAssetNotFound):
        atomic_assets.load_action("nonexistent_action_xyz")


def test_load_hook_missing_raises():
    with pytest.raises(atomic_assets.AtomicAssetNotFound):
        atomic_assets.load_hook("nonexistent_hook_xyz")


def test_load_arc_missing_raises():
    with pytest.raises(atomic_assets.AtomicAssetNotFound):
        atomic_assets.load_arc("nonexistent_arc_xyz")


@pytest.mark.parametrize(
    "bad_id",
    [
        "../config",
        "..",
        "/etc/passwd",
        "foo/bar",
        "Foo",
        "1abc",
        "",
        "foo.bar",
        "foo-bar",
    ],
)
def test_load_action_rejects_invalid_id_pattern(bad_id):
    with pytest.raises(atomic_assets.AtomicAssetNotFound):
        atomic_assets.load_action(bad_id)


def test_load_hook_rejects_invalid_id_pattern():
    with pytest.raises(atomic_assets.AtomicAssetNotFound):
        atomic_assets.load_hook("../foo")


def test_load_arc_rejects_invalid_id_pattern():
    with pytest.raises(atomic_assets.AtomicAssetNotFound):
        atomic_assets.load_arc("../foo")


def test_load_action_rejects_non_string_id():
    with pytest.raises(atomic_assets.AtomicAssetNotFound):
        atomic_assets.load_action(None)  # type: ignore[arg-type]


def test_compatible_locations_reference_existing_locations():
    """各 action.compatible_locations は実在する locations/ の id でなければならない。"""
    from analyze import location as loc_mod
    available = set(loc_mod.list_locations())
    for action_id in atomic_assets.list_action_ids():
        action = atomic_assets.load_action(action_id)
        for loc in action.get("compatible_locations") or []:
            assert loc in available, (
                f"action '{action_id}' references unknown location '{loc}'"
            )


def test_hook_first_scene_action_id_is_valid():
    """各 hook.first_scene_template.action_id は実在する actions/ の id。"""
    available = set(atomic_assets.list_action_ids())
    for hook_id in atomic_assets.list_hook_ids():
        hook = atomic_assets.load_hook(hook_id)
        template = hook.get("first_scene_template") or {}
        action_id = template.get("action_id")
        if action_id:
            assert action_id in available, (
                f"hook '{hook_id}' references unknown action '{action_id}'"
            )


def test_hook_follow_arcs_are_valid():
    """各 hook.follow_arc_id_candidates は実在する arcs/ の id。"""
    available = set(atomic_assets.list_arc_ids())
    for hook_id in atomic_assets.list_hook_ids():
        hook = atomic_assets.load_hook(hook_id)
        for arc_id in hook.get("follow_arc_id_candidates") or []:
            assert arc_id in available, (
                f"hook '{hook_id}' references unknown arc '{arc_id}'"
            )
