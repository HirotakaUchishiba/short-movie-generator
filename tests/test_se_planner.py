"""se_planner.plan_se の自動配置導出テスト (emotion / visual_intent / 境界 / 上限)。

実 assets/se に依存しないよう、catalog に各 category 1 つずつダミー SE を置く。
"""
import json

import pytest

import config
import se_planner


@pytest.fixture
def isolated_se(tmp_path, monkeypatch):
    se_dir = tmp_path / "se"
    se_dir.mkdir()
    for f in ("react.mp3", "sting.mp3", "trans.mp3"):
        (se_dir / f).write_bytes(b"x")
    catalog = tmp_path / "se_catalog.json"
    catalog.write_text(json.dumps([
        {"id": "react", "file": "react.mp3", "category": "reaction"},
        {"id": "sting", "file": "sting.mp3", "category": "sting"},
        {"id": "trans", "file": "trans.mp3", "category": "transition"},
    ]), encoding="utf-8")
    monkeypatch.setattr(config, "SE_DIR", str(se_dir))
    monkeypatch.setattr(config, "SE_CATALOG_PATH", str(catalog))
    return se_dir, catalog


def test_emotion_maps_to_se_at_line_absolute_time(isolated_se):
    sp = {"scenes": [{"lines": [{"emotion": "驚き", "start": 1.0}]}]}
    items = se_planner.plan_se(sp, [0.0])
    assert len(items) == 1
    assert items[0]["se_id"] == "react"  # 驚き → reaction
    assert items[0]["time"] == 1.0
    assert items[0]["source"] == "auto"
    assert "emotion" in items[0]["reason"]


def test_emotion_absolute_time_uses_scene_offset(isolated_se):
    sp = {"scenes": [
        {"lines": []},
        {"lines": [{"emotion": "焦り", "start": 0.5}]},
    ]}
    items = se_planner.plan_se(sp, [0.0, 5.0])
    emo = [it for it in items if "emotion" in it["reason"]]
    assert emo[0]["time"] == 5.5  # scene offset 5.0 + line.start 0.5
    assert emo[0]["se_id"] == "sting"  # 焦り → sting


def test_visual_intent_maps_to_reaction_at_scene_start(isolated_se):
    sp = {"scenes": [
        {"annotation": {"visual_intent_id": "reaction_surprise"}, "lines": []},
    ]}
    items = se_planner.plan_se(sp, [0.0])
    assert len(items) == 1
    assert items[0]["se_id"] == "react"
    assert items[0]["time"] == 0.0
    assert "intent" in items[0]["reason"]


def test_scene_boundary_adds_transition(isolated_se):
    sp = {"scenes": [{"lines": []}, {"lines": []}]}
    items = se_planner.plan_se(sp, [0.0, 4.0])
    assert len(items) == 1  # scene0 は境界なし、scene1 開始に transition
    assert items[0]["se_id"] == "trans"
    assert items[0]["time"] == 4.0
    assert "transition" in items[0]["reason"]


def test_se_max_per_scene_cap(isolated_se, monkeypatch):
    monkeypatch.setattr(config, "SE_MAX_PER_SCENE", 2)
    sp = {"scenes": [{"lines": [
        {"emotion": "驚き", "start": 0.1},
        {"emotion": "焦り", "start": 0.2},
        {"emotion": "喜び", "start": 0.3},
    ]}]}
    items = se_planner.plan_se(sp, [0.0])
    assert len(items) == 2  # 3 候補 → 上限 2


def test_unmapped_emotion_ignored(isolated_se):
    sp = {"scenes": [{"lines": [{"emotion": "中立", "start": 1.0}]}]}
    assert se_planner.plan_se(sp, [0.0]) == []


def test_empty_category_skipped(isolated_se):
    """catalog に reaction が無ければ驚きの placement は skip (graceful)。"""
    _, catalog = isolated_se
    catalog.write_text(json.dumps([
        {"id": "trans", "file": "trans.mp3", "category": "transition"},
    ]), encoding="utf-8")
    sp = {"scenes": [{"lines": [{"emotion": "驚き", "start": 1.0}]}]}
    assert se_planner.plan_se(sp, [0.0]) == []
