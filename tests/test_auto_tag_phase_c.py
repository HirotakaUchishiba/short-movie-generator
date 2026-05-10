"""Phase C: auto_tag prompt が transformation taxonomy yaml を inject すること、
および v11 フィールド (transformation / tree_main_branch / pov_id) の出力指示が
prompt に含まれることを検証する。"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_taxonomy_yaml_exists():
    p = (Path(__file__).resolve().parent.parent
         / "config" / "transformation_taxonomy.yaml")
    assert p.exists(), "config/transformation_taxonomy.yaml が無い"


def test_taxonomy_yaml_parses():
    pytest.importorskip("yaml")
    import yaml
    p = (Path(__file__).resolve().parent.parent
         / "config" / "transformation_taxonomy.yaml")
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    for key in ("transformations", "tree_main_branches", "povs"):
        assert key in data, f"{key} が yaml に無い"
        assert isinstance(data[key], list)
        assert all("id" in item for item in data[key])


def test_system_prompt_includes_taxonomy_ids():
    """auto_tag.SYSTEM_PROMPT に yaml の id がいくつか inject されていること。"""
    from analytics import auto_tag
    prompt = auto_tag.SYSTEM_PROMPT
    assert "transformation の候補" in prompt
    assert "tree_main_branch の候補" in prompt
    assert "pov_id の候補" in prompt
    # 代表 id が含まれている (= yaml 拡張時もここに新 id が出ること)
    for sample_id in ("career_pivot", "how_to_solve", "data_driven"):
        assert sample_id in prompt, f"taxonomy id {sample_id} が prompt に inject されていない"


def test_system_prompt_includes_v11_output_keys():
    """SYSTEM_PROMPT が transformation / tree_main_branch / pov_id を出力指示に含むこと。"""
    from analytics import auto_tag
    prompt = auto_tag.SYSTEM_PROMPT
    for key in ('"transformation"', '"tree_main_branch"', '"pov_id"'):
        assert key in prompt, f"{key} の出力指示が SYSTEM_PROMPT に無い"


def test_taxonomy_load_handles_missing_file(monkeypatch, tmp_path):
    """yaml が無くても SYSTEM_PROMPT 構築が壊れないこと (= graceful degradation)。"""
    from analytics import auto_tag
    fake_path = tmp_path / "nope.yaml"
    monkeypatch.setattr(auto_tag, "_TAXONOMY_PATH", fake_path)
    taxonomy = auto_tag._load_taxonomy()
    assert taxonomy["transformations"] == []
    assert taxonomy["tree_main_branches"] == []
    assert taxonomy["povs"] == []
    prompt = auto_tag._build_system_prompt(taxonomy)
    assert "taxonomy 未定義" in prompt
