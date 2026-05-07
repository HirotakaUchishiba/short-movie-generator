"""Phase 1: scripts/auto_loop.py の経路テスト。

外部 IO 系 (yt-dlp / Claude / Imagen / Kling / TTS / lipsync / YouTube upload)
は全て monkeypatch で差し替え、orchestrator の整合だけを検証する。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def auto_loop_env(tmp_path, monkeypatch):
    """auto_loop が触る paths / DB / SLACK を tmp_path に隔離する。"""
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    monkeypatch.setenv("COST_RECORDS_PATH", str(tmp_path / "cost.jsonl"))
    monkeypatch.delenv("DISABLE_AUTO_LOOP", raising=False)

    monkeypatch.setattr("config.TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setattr("config.OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr("config.SCREENPLAYS_DIR", str(tmp_path / "screenplays"))
    monkeypatch.setattr("config.BASE_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr("config.SLACK_WEBHOOK_URL", "")
    monkeypatch.setattr("config.DAILY_COST_CAP_USD", 0.0)
    monkeypatch.setattr("config.MONTHLY_COST_CAP_USD", 0.0)
    monkeypatch.setattr("config.DAILY_VIDEO_CAP", 0)

    Path(tmp_path / "screenplays").mkdir()
    Path(tmp_path / "temp").mkdir()
    Path(tmp_path / "output").mkdir()

    from analytics import db as _db
    _db.init_db()

    # qa archive 先も tmp に
    from qa import recorder as _rec
    archive_root = tmp_path / "qa_failures"
    monkeypatch.setattr(_rec, "qa_failures_root", lambda: str(archive_root))

    return tmp_path, _db


def _fake_screenplay() -> dict:
    return {
        "caption": "x #y",
        "scenes": [
            {
                "duration": 3.0,
                "background_prompt": "bg",
                "animation_prompt": "motion",
                "lines": [{"text": "hello", "start": 0.0, "end": 1.0}],
            },
        ],
    }


@pytest.fixture
def stub_pipeline(auto_loop_env, monkeypatch):
    """fetch / analyze / 各 stage runner / publish を stub に置換。"""
    tmp_path, _ = auto_loop_env
    import scripts.auto_loop as al

    # fetch_reference の中身をスタブ
    sp_path = tmp_path / "screenplays" / "auto_abc123.json"
    ref_path = tmp_path / "ref.mp4"
    ref_path.write_bytes(b"x")

    def _fake_fetch(url, license_status=None, max_duration=None):
        if license_status not in (
            "user_owned", "fair_use_review", "public_domain",
        ):
            raise ValueError(f"invalid license: {license_status}")
        sha = "abc123" * 10 + "abc1"
        # 実物の fetch_and_register と同様、reference_videos 行を確保しておく
        # (= update_generation_record の FK が通るように)
        from analytics import db as _db
        with _db.get_connection() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO reference_videos
                   (sha256, original_name, size_bytes, uploaded_at,
                    source_url, fetched_at, license_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (sha, "ref.mp4", 1, "2026-05-08T12:00:00",
                 "https://x", "2026-05-08T12:00:00", "user_owned"),
            )
        return {"sha256": sha, "path": str(ref_path),
                "size_bytes": 1, "source_url": "https://x",
                "license_status": "user_owned"}
    monkeypatch.setattr("scripts.fetch_reference.fetch_and_register", _fake_fetch)

    def _fake_analyze(**kwargs):
        out = kwargs.get("output_path")
        Path(out).write_text(json.dumps(_fake_screenplay()), encoding="utf-8")
        return _fake_screenplay()
    monkeypatch.setattr("analyze.run", _fake_analyze)

    # 各 stage runner を「mark_generated するだけ」の stub に
    import staged_pipeline as sp_mod

    def _make_runner(stage_name, write_artifacts=None):
        def _r(*args, **kwargs):
            ts_path = args[-1] if isinstance(args[-1], str) else kwargs.get("ts_path")
            if write_artifacts:
                for fname in write_artifacts:
                    Path(ts_path, fname).write_bytes(b"fakebytes")
            from progress_store import mark_generated
            mark_generated(ts_path, stage_name)
        return _r

    monkeypatch.setitem(sp_mod.STAGE_RUNNERS, "tts",
                        _make_runner("tts", write_artifacts=["tts_0_0.mp3"]))
    monkeypatch.setitem(sp_mod.STAGE_RUNNERS, "bg",
                        _make_runner("bg", write_artifacts=["bg_0.png"]))
    monkeypatch.setitem(sp_mod.STAGE_RUNNERS, "kling",
                        _make_runner("kling", write_artifacts=["kling_0.mp4"]))
    monkeypatch.setitem(sp_mod.STAGE_RUNNERS, "scene",
                        _make_runner("scene", write_artifacts=["scene_0.mp4"]))

    # overlay は mark_generated + output/reels_<ts>.mp4 を作る
    def _overlay_runner(screenplay, screenplay_name, ts_path):
        from progress_store import mark_generated
        mark_generated(ts_path, "overlay")
        ts = Path(ts_path).name
        Path(tmp_path / "output" / f"reels_{ts}.mp4").write_bytes(b"raw_video")
    monkeypatch.setitem(sp_mod.STAGE_RUNNERS, "overlay", _overlay_runner)

    # validator は常に空 (= 全 pass) にする。個別テストで NG にすり替える。
    monkeypatch.setattr("scripts.auto_loop._validate_stage",
                        lambda ts, stage: [])

    # final_import / publish も stub
    def _fake_import(*args, **kwargs):
        ts = args[0]
        # final/<ts> ディレクトリ作って canonical 設定する代わりに、
        # progress_store だけ進める。
        ts_path = os.path.join(tmp_path / "temp", ts)
        from progress_store import mark_generated
        mark_generated(ts_path, "final_import")
    monkeypatch.setattr("final_import.import_final", _fake_import)

    def _fake_publish(ts, platform, privacy="unlisted", **kw):
        return {"video_id": "vid_xyz", "url": "https://youtu.be/vid_xyz",
                "platform": platform, "manual": False}
    monkeypatch.setattr("final_import.publish.publish", _fake_publish)

    return al, tmp_path


# ─── 経路テスト ──────────────────────────────────────────


def test_run_one_video_happy_path(stub_pipeline, auto_loop_env):
    al, tmp_path = stub_pipeline
    _, db = auto_loop_env
    ts = al.run_one_video(
        "https://example.com/v1",
        license_status="user_owned",
        privacy="unlisted",
        dry_run=False,
    )
    assert ts
    rec = db.get_generation_record(ts)
    assert rec is not None
    assert rec["status"] == "completed"
    assert rec["reference_video_id"]


def test_dry_run_skips_publish(stub_pipeline, auto_loop_env):
    al, _ = stub_pipeline
    _, db = auto_loop_env
    with patch("final_import.publish.publish") as p:
        ts = al.run_one_video(
            "https://example.com/v2",
            license_status="user_owned",
            dry_run=True,
        )
    p.assert_not_called()
    rec = db.get_generation_record(ts)
    assert rec["status"] == "completed"


def test_kill_switch_blocks(monkeypatch, auto_loop_env):
    monkeypatch.setenv("DISABLE_AUTO_LOOP", "1")
    import scripts.auto_loop as al
    with pytest.raises(SystemExit):
        al.run_one_video(
            "https://example.com/x", license_status="user_owned",
        )


def test_budget_blocks(monkeypatch, auto_loop_env):
    monkeypatch.setattr("config.DAILY_COST_CAP_USD", 0.01)
    # cost_records.jsonl に大金を仕込む
    tmp_path, _ = auto_loop_env
    from datetime import datetime, timezone
    today_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rec = {"record_id": "r", "timestamp": today_iso, "project_ts": None,
           "stage": "tts", "operation": "generate",
           "scene_index": None, "line_index": None,
           "provider": "elevenlabs", "model": "x",
           "units": {}, "unit_prices": {}, "cost_usd": 100.0, "metadata": {}}
    cost_path = tmp_path / "cost.jsonl"
    cost_path.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    import scripts.auto_loop as al
    from cost_tracking import budget
    with pytest.raises(budget.BudgetExceeded):
        al.run_one_video(
            "https://example.com/y", license_status="user_owned",
        )


def test_validator_failure_triggers_retry_and_aborts_after_max(
    stub_pipeline, auto_loop_env, monkeypatch,
):
    """tts validator が常に NG → retry 上限まで試みて abort。"""
    al, _ = stub_pipeline
    _, db = auto_loop_env
    from qa.validators.base import ValidationResult, failed_result

    def _always_fail(ts, stage):
        if stage == "tts":
            r = failed_result(
                score=0.0, reason="silence_ratio=99%",
                tag="audio_silence", scene_idx=0, line_idx=0,
            )
            # 副作用: auto_loop の _validate_stage が record_failure を呼んでいる
            # 振る舞いを test stub でも再現しないと、qa_failures に行が入らない。
            from qa import recorder
            recorder.record_failure(
                ts=ts, stage=stage, source="auto_flagged",
                tags=["audio_silence"], note=r.reason,
                scene_idx=0, line_idx=0,
            )
            return [r]
        return []
    monkeypatch.setattr("scripts.auto_loop._validate_stage", _always_fail)
    monkeypatch.setattr("staged_pipeline.regen", lambda *a, **kw: None)

    with pytest.raises(al.AutoLoopAborted, match="validator NG"):
        al.run_one_video(
            "https://example.com/z",
            license_status="user_owned",
        )

    rows = db.list_qa_failures(source="auto_flagged")
    assert len(rows) >= 1

    last_ts = sorted(os.listdir(auto_loop_env[0] / "temp"))[-1]
    rec = db.get_generation_record(last_ts)
    assert rec["status"] == "auto_rejected"


def test_invalid_license_aborts_before_fetch(stub_pipeline, auto_loop_env):
    al, _ = stub_pipeline
    with pytest.raises(al.AutoLoopAborted):
        al.run_one_video(
            "https://example.com/x",
            license_status="not_a_license",
        )
