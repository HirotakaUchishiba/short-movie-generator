"""Phase 2: eval_validators の集計ロジックのテスト。"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def isolated_eval(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    monkeypatch.setattr("config.BASE_DIR", str(tmp_path), raising=False)
    from analytics import db as _db
    _db.init_db()
    return tmp_path, _db


def _seed(db, *, ts, source, tags, scene_idx=None, line_idx=None):
    db.insert_qa_failure(
        ts=ts, stage="bg", source=source, tags=tags,
        scene_idx=scene_idx, line_idx=line_idx,
    )


def test_eval_per_tag_counts_overlap(isolated_eval):
    _, db = isolated_eval
    # 同じ ts/scene_idx で human + auto 両方 → both カウント
    _seed(db, ts="t1", source="human_reject",
          tags=["character_drift"], scene_idx=0)
    _seed(db, ts="t1", source="auto_flagged",
          tags=["character_drift"], scene_idx=0)
    # human だけ
    _seed(db, ts="t2", source="human_reject",
          tags=["character_drift"], scene_idx=1)
    # auto だけ (= 別の不良)
    _seed(db, ts="t3", source="auto_flagged",
          tags=["character_drift"], scene_idx=2)

    from qa.eval_validators import load_recent_failures, evaluate_per_tag
    failures = load_recent_failures(days=30)
    per_tag = evaluate_per_tag(failures)
    cd = per_tag["character_drift"]
    assert cd["human_reject"] == 2
    assert cd["auto_flagged"] == 2
    assert cd["both"] == 1
    assert cd["recall"] == pytest.approx(0.5)  # 1/2 = 50%
    assert cd["precision"] == pytest.approx(0.5)


def test_run_eval_writes_json(isolated_eval, tmp_path):
    _, db = isolated_eval
    _seed(db, ts="t1", source="human_reject", tags=["audio_silence"])

    from qa.eval_validators import run_eval, _eval_dir
    summary = run_eval(days=30)
    assert summary["total_failures"] == 1
    out_files = list(_eval_dir().glob("*.json"))
    assert len(out_files) == 1
    written = json.loads(out_files[0].read_text())
    assert written["total_failures"] == 1
    assert "audio_silence" in written["per_tag"]


def test_eval_handles_no_failures(isolated_eval):
    from qa.eval_validators import run_eval
    summary = run_eval(days=30)
    assert summary["total_failures"] == 0
    assert summary["per_tag"] == {}
