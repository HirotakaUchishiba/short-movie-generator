"""main.py CLI の screenplay ソース選択をカバー。

Stage 1 が未生成なら template、生成済みなら project snapshot を読むことで、
UI 経由で編集された snapshot が CLI resume でも反映されることを確認する。
"""
import json
import os
from unittest.mock import patch

import pytest

import main
import progress_store
import staged_pipeline


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    """temp_dir + screenplays_dir を tmp に切替。"""
    temp_dir = tmp_path / "temp"
    sp_dir = tmp_path / "screenplays"
    temp_dir.mkdir()
    sp_dir.mkdir()
    monkeypatch.setattr("config.TEMP_DIR", str(temp_dir))
    monkeypatch.setattr("config.SCREENPLAYS_DIR", str(sp_dir))
    return temp_dir, sp_dir


def _write_template(sp_dir, name: str, body: dict):
    p = sp_dir / f"{name}.json"
    p.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return p


def _write_snapshot(ts_path, body: dict):
    os.makedirs(ts_path, exist_ok=True)
    p = os.path.join(ts_path, staged_pipeline.PROJECT_SCREENPLAY_FILENAME)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
    return p


def test_run_pipeline_uses_template_when_script_not_generated(tmp_project):
    temp_dir, sp_dir = tmp_project
    template_body = {
        "caption": "from template",
        "scenes": [{"lines": [{"text": "hello"}]}],
    }
    _write_template(sp_dir, "demo", template_body)

    captured = {}

    def fake_run(screenplay, name, ts_path):
        captured["caption"] = screenplay.get("caption")
        return "script"

    with patch.object(staged_pipeline, "run_next_stage", side_effect=fake_run):
        main._run_pipeline("demo", resume_ts="20990101_000000")

    assert captured["caption"] == "from template"


def test_run_pipeline_uses_snapshot_when_script_generated(tmp_project):
    temp_dir, sp_dir = tmp_project
    ts = "20990101_000000"
    ts_path = str(temp_dir / ts)

    template_body = {
        "caption": "old template",
        "scenes": [{"lines": [{"text": "hi"}]}],
    }
    snapshot_body = {
        "caption": "edited via UI",
        "scenes": [{"lines": [{"text": "edited"}]}],
    }
    _write_template(sp_dir, "demo", template_body)
    _write_snapshot(ts_path, snapshot_body)
    progress_store.mark_generated(ts_path, "script")
    progress_store.mark_approved(ts_path, "script")

    captured = {}

    def fake_run(screenplay, name, ts_path):
        captured["caption"] = screenplay.get("caption")
        return "tts"

    with patch.object(staged_pipeline, "run_next_stage", side_effect=fake_run):
        main._run_pipeline("demo", resume_ts=ts)

    assert captured["caption"] == "edited via UI"


def test_run_pipeline_template_fallback_for_new_project(tmp_project):
    temp_dir, sp_dir = tmp_project
    template_body = {
        "caption": "fresh start",
        "scenes": [{"lines": [{"text": "hello"}]}],
    }
    _write_template(sp_dir, "demo", template_body)

    captured = {}

    def fake_run(screenplay, name, ts_path):
        captured["caption"] = screenplay.get("caption")
        captured["ts_path"] = ts_path
        return "script"

    with patch.object(staged_pipeline, "run_next_stage", side_effect=fake_run):
        main._run_pipeline("demo", resume_ts=None)

    assert captured["caption"] == "fresh start"
    assert os.path.isdir(captured["ts_path"])
