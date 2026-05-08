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
    # 既定 fixture では human gate を OFF にして publish 経路を通す。
    # gate ON のケースは個別テストで上書きする。
    monkeypatch.setattr("config.PRODUCTION_HUMAN_GATE_ENABLED", False)

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

    # production の命名は f"<stage>_{scene_idx:03d}.<ext>" (3 桁ゼロ詰め)。
    # auto_loop の glob (`tts_*_*.mp3` 等) と stage_artifact_paths が
    # マッチさせる対象。
    monkeypatch.setitem(
        sp_mod.STAGE_RUNNERS, "tts",
        _make_runner("tts", write_artifacts=["tts_000_000.mp3"]))
    monkeypatch.setitem(
        sp_mod.STAGE_RUNNERS, "bg",
        _make_runner("bg", write_artifacts=["bg_000.png"]))
    monkeypatch.setitem(
        sp_mod.STAGE_RUNNERS, "kling",
        _make_runner("kling", write_artifacts=["kling_000.mp4"]))
    monkeypatch.setitem(
        sp_mod.STAGE_RUNNERS, "scene",
        _make_runner("scene", write_artifacts=["scene_000.mp4"]))

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


def test_active_strategy_logs_and_records_assignments(
    stub_pipeline, auto_loop_env, monkeypatch, caplog,
):
    """active 戦略で履歴があれば、log と experiment_assignments の両方に出る。"""
    al, _ = stub_pipeline
    _, db = auto_loop_env
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "active")
    monkeypatch.setattr("config.BANDIT_AXES", ("hook_type",))
    monkeypatch.setattr("config.BANDIT_EPSILON", 0.0)  # 必ず exploit

    # 軸別 view が空だと bandit が assignments を返さないので、history を仕込む
    with db.get_connection() as conn:
        for i, (hook, comp) in enumerate(
            (("共感型", 0.4), ("結論先出し", 0.7)),
        ):
            sp = f"sp_seed_{i}"
            v = f"v_seed_{i}"
            p = f"p_seed_{i}"
            conn.execute(
                """INSERT INTO screenplays (id, path, name, sha256, created_at,
                   raw_json, hook_type) VALUES (?, '/x', 'x', ?, datetime('now'),
                   '{}', ?)""", (sp, sp + "_sha", hook),
            )
            conn.execute(
                """INSERT INTO videos (id, screenplay_id, output_path,
                   generated_at) VALUES (?, ?, '/x', datetime('now'))""",
                (v, sp),
            )
            conn.execute(
                """INSERT INTO posts (id, video_id, platform, platform_post_id,
                   posted_at, registered_at) VALUES (?, ?, 'youtube', ?,
                   datetime('now', '-2 days'), datetime('now'))""",
                (p, v, p),
            )
            conn.execute(
                """INSERT INTO post_metrics (post_id, fetched_at, views,
                   completion_rate) VALUES (?, datetime('now'), 1000, ?)""",
                (p, comp),
            )

    # analyze.run の instructions が active 経路で string になることも確認
    captured: dict = {}

    def _fake_analyze(**kwargs):
        captured["instructions"] = (
            kwargs["options"].instructions if kwargs.get("options") else None
        )
        out = kwargs.get("output_path")
        Path(out).write_text(json.dumps(_fake_screenplay()), encoding="utf-8")
        return _fake_screenplay()
    monkeypatch.setattr("analyze.run", _fake_analyze)

    with caplog.at_level("INFO"):
        ts = al.run_one_video(
            "https://example.com/active",
            license_status="user_owned",
            dry_run=True,
        )

    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "strategy=active" in log_text
    assert "hook_type=結論先出し(exploit)" in log_text

    # experiment_assignments に書かれている
    rows = db.list_experiment_assignments(video_id=ts)
    assert len(rows) == 1
    assert rows[0]["axis"] == "hook_type"
    assert rows[0]["selected_value"] == "結論先出し"
    assert rows[0]["strategy"] == "active_exploit"

    # active なので analyze.run.instructions に注入文字列が乗っている
    assert captured.get("instructions")
    assert "結論先出し" in captured["instructions"]


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


def test_human_gate_skips_publish_and_marks_awaiting(
    stub_pipeline, auto_loop_env, monkeypatch,
):
    """PRODUCTION_HUMAN_GATE_ENABLED=True のとき publish を skip して
    status="awaiting_human_gate" で停止する。"""
    al, _ = stub_pipeline
    _, db = auto_loop_env
    monkeypatch.setattr("config.PRODUCTION_HUMAN_GATE_ENABLED", True)
    with patch("final_import.publish.publish") as p:
        ts = al.run_one_video(
            "https://example.com/gate",
            license_status="user_owned",
            dry_run=False,
        )
    p.assert_not_called()
    rec = db.get_generation_record(ts)
    assert rec["status"] == "awaiting_human_gate"


def test_archive_before_retry_archives_per_scene_artifacts(
    stub_pipeline, auto_loop_env, tmp_path,
):
    """bg / kling / scene stage の retry で、scene_idx=None でも
    実 production 命名 (= bg_000.png 等) の per-scene artifact が
    qa_failures に regenerate_implicit で残ることを確認する。

    Phase 2 の validator しきい値学習は
    `qa_failures (auto_flagged) + (regenerate_implicit)` の両方を訓練データに
    使う前提なので、このアーカイブ抜けは Phase 0 の契約違反になる。"""
    al, tp = stub_pipeline
    _, db = auto_loop_env

    # 仮の TS ディレクトリを用意して production 命名で artifact を撒く
    ts = "20260507_990000"
    ts_dir = tp / "temp" / ts
    ts_dir.mkdir(parents=True)
    (ts_dir / "screenplay.json").write_text("{}")
    (ts_dir / "bg_000.png").write_bytes(b"old_bg_0")
    (ts_dir / "bg_001.png").write_bytes(b"old_bg_1")
    (ts_dir / "kling_000.mp4").write_bytes(b"old_kling")
    (ts_dir / "scene_000.mp4").write_bytes(b"old_scene")

    al._archive_before_retry(ts, "bg")
    al._archive_before_retry(ts, "kling")
    al._archive_before_retry(ts, "scene")

    rows = db.list_qa_failures(ts=ts, source="regenerate_implicit")
    by_stage = {r["stage"]: r for r in rows}
    assert {"bg", "kling", "scene"} <= set(by_stage.keys()), (
        f"per-scene artifact が archive されていない: {by_stage}"
    )
    # bg は 2 シーン分、archive_dir に両方コピー済みである
    bg_arc = by_stage["bg"]["artifact_path"]
    assert bg_arc and os.path.exists(bg_arc)
    bg_dir = os.path.dirname(bg_arc)
    assert {"bg_000.png", "bg_001.png"} <= set(os.listdir(bg_dir))


# ─── _retry_failed_scenes の per-scene / full-regen 切替 ──────────


def test_retry_failed_scenes_per_scene_when_all_have_scene_idx(monkeypatch):
    """全 fails に scene_idx=N が付いていれば per-scene regen を呼ぶ。"""
    import scripts.auto_loop as al
    from qa.validators.base import failed_result

    calls: list[tuple[str, int | None]] = []

    def _stub_retry(sp_name, ts, stage, scene_idx=None):
        calls.append((stage, scene_idx))
    monkeypatch.setattr(al, "_retry_stage", _stub_retry)

    fails = [
        failed_result(score=0.0, reason="x", tag="audio_silence",
                      scene_idx=0, line_idx=0),
        failed_result(score=0.0, reason="x", tag="audio_silence",
                      scene_idx=2, line_idx=1),
    ]
    al._retry_failed_scenes("sp", "ts", "tts", fails)

    # scene 0 と scene 2 の 2 回 (= 重複 dedup 済み、scene_idx=None は呼ばれない)
    assert calls == [("tts", 0), ("tts", 2)]


def test_retry_failed_scenes_falls_back_to_full_when_global_fail_mixed(monkeypatch):
    """scene_idx=None が 1 つでも混ざっていれば full-stage regen に倒す。"""
    import scripts.auto_loop as al
    from qa.validators.base import failed_result

    calls: list[tuple[str, int | None]] = []

    def _stub_retry(sp_name, ts, stage, scene_idx=None):
        calls.append((stage, scene_idx))
    monkeypatch.setattr(al, "_retry_stage", _stub_retry)

    fails = [
        failed_result(score=0.0, reason="x", tag="audio_silence",
                      scene_idx=0, line_idx=0),
        failed_result(score=0.0, reason="stage-wide", tag="audio_silence",
                      scene_idx=None, line_idx=None),
    ]
    al._retry_failed_scenes("sp", "ts", "tts", fails)

    # scene-idx=None があれば 1 回だけ full regen が呼ばれて scene 0 はスキップ
    assert calls == [("tts", None)]


def test_retry_failed_scenes_noop_when_empty(monkeypatch):
    """fails が空なら何も呼ばない (= 防御的 no-op)。"""
    import scripts.auto_loop as al
    calls: list = []
    monkeypatch.setattr(al, "_retry_stage",
                        lambda *a, **kw: calls.append((a, kw)))
    al._retry_failed_scenes("sp", "ts", "tts", [])
    assert calls == []


# ─── kill-switch の env 真偽値解釈 ──────────


def test_is_truthy_env_accepts_common_truthy_values():
    import scripts.auto_loop as al
    assert al._is_truthy_env("1") is True
    assert al._is_truthy_env("true") is True
    assert al._is_truthy_env("True") is True
    assert al._is_truthy_env("yes") is True
    assert al._is_truthy_env(" 1 ") is True  # 空白許容


def test_is_truthy_env_rejects_falsy_values():
    import scripts.auto_loop as al
    assert al._is_truthy_env(None) is False
    assert al._is_truthy_env("") is False
    assert al._is_truthy_env("0") is False
    assert al._is_truthy_env("false") is False
    assert al._is_truthy_env("no") is False


def test_kill_switch_truthy_value_blocks(monkeypatch, auto_loop_env):
    """DISABLE_AUTO_LOOP=true (= 1 以外の truthy) でも kill-switch が発火する。"""
    monkeypatch.setenv("DISABLE_AUTO_LOOP", "true")
    import scripts.auto_loop as al
    with pytest.raises(SystemExit):
        al.run_one_video(
            "https://example.com/x", license_status="user_owned",
        )
