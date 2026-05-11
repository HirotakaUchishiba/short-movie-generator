"""publish() / _import_raw_as_final() 失敗時の progress_store 記録テスト。"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

import progress_store


@pytest.fixture
def project_ts(tmp_path, monkeypatch):
    """Stage 7 (final_import) を approved 状態にした project を 1 つ用意。"""
    ts = "20260511_220521"
    ts_dir = tmp_path / "temp" / ts
    ts_dir.mkdir(parents=True)
    monkeypatch.setattr("config.TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setattr("config.OUTPUT_DIR", str(tmp_path / "output"))
    (tmp_path / "output").mkdir()

    ts_path = str(ts_dir)
    # final_import を approved にしておく (= publish の事前条件)
    for s in ("script", "tts", "bg", "kling", "scene", "overlay", "final_import"):
        progress_store.mark_generated(ts_path, s)
        progress_store.mark_approved(ts_path, s)
    return ts, ts_path


# ─────────── publish() 失敗 ───────────


def test_publish_youtube_failure_writes_structured_detail(project_ts) -> None:
    """YouTube upload 失敗時に progress_store.stages.publish.error_detail に記録される。"""
    from final_import import publish as publish_mod

    ts, ts_path = project_ts
    # resolve_canonical_video / read_post_caption_for_ts は mock しないと
    # 早期失敗する。実 publish 経路に入った所で _publish_youtube が
    # OAuth 失敗を raise するシナリオを mock する。
    with patch.object(publish_mod, "resolve_canonical_video") as mvideo, \
         patch.object(publish_mod, "read_post_caption_for_ts") as mcap, \
         patch.object(publish_mod, "_confirm_publish_channel"), \
         patch.object(publish_mod, "preflight"), \
         patch.object(
             publish_mod, "_publish_youtube",
             side_effect=RuntimeError("Error 401: invalid api key"),
         ):
        from pathlib import Path
        mvideo.return_value = Path("/tmp/fake.mp4")
        mcap.return_value = ("Title", "desc", ["tag"])

        with pytest.raises(RuntimeError, match="401"):
            publish_mod.publish(ts, "youtube")

    p = progress_store.load(ts_path)
    block = p["stages"]["publish"]
    assert block["status"] == "failed"
    detail = block["error_detail"]
    assert detail["type"] == "auth_failure"
    assert detail["failed_phase"] == "youtube"
    assert "API" in detail["actionable_hint"]


def test_publish_unknown_platform_raises_value_error_but_no_record(
    project_ts,
) -> None:
    """ValueError は publish() 内の最初の guard で raise されるが、
    progress_store には final_import / publish の事前承認状態を保ったまま。
    (= 設計判断: バリデーション失敗は UI gating で防げるので、progress_store には書かない)
    """
    from final_import import publish as publish_mod

    ts, ts_path = project_ts
    with pytest.raises(ValueError, match="unknown platform"):
        publish_mod.publish(ts, "bogus")

    # publish stage は failed になっていない (= 入口 guard より前で死ぬため)
    p = progress_store.load(ts_path)
    assert p["stages"]["publish"].get("status") != "failed"


# ─────────── _import_raw_as_final() 失敗 (= Stage 7) ───────────


def test_import_raw_as_final_failure_writes_structured_detail(
    project_ts,
) -> None:
    """final_import.import_final が raise したら Stage 7 が failed として記録される。"""
    from scripts import auto_loop

    ts, ts_path = project_ts
    raw_path = os.path.join(os.path.dirname(os.path.dirname(ts_path)), "output", f"reels_{ts}.mp4")
    # raw file は存在しないと AutoLoopAborted で先に死ぬ。空 file を作る。
    os.makedirs(os.path.dirname(raw_path), exist_ok=True)
    with open(raw_path, "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypmp42")  # 偽の ftyp (= import_final が validate する)

    with patch(
        "final_import.import_final",
        side_effect=RuntimeError("[Errno 28] No space left on device"),
    ):
        with pytest.raises(RuntimeError, match="No space"):
            auto_loop._import_raw_as_final(ts)

    p = progress_store.load(ts_path)
    block = p["stages"]["final_import"]
    assert block["status"] == "failed"
    detail = block["error_detail"]
    assert detail["type"] == "disk_full"
    assert "ディスク" in detail["actionable_hint"]


def test_import_raw_as_final_raw_missing_does_not_touch_progress(
    project_ts, monkeypatch,
) -> None:
    """raw 不在は AutoLoopAborted で即 raise、progress 変更なし。"""
    from scripts import auto_loop

    ts, ts_path = project_ts
    # raw_path は存在しないまま (project_ts は output dir 自体は作るが reels_<TS>.mp4 は無い)
    with pytest.raises(auto_loop.AutoLoopAborted):
        auto_loop._import_raw_as_final(ts)

    p = progress_store.load(ts_path)
    # 元の approved 状態が維持されている (= failed mark されない)
    assert p["stages"]["final_import"]["approved_at"] is not None
    assert p["stages"]["final_import"].get("status") != "failed"
