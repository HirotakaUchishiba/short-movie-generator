"""staged_pipeline.run_next_stage の失敗時に progress_store.mark_stage_failed が
呼ばれ、構造化 error_detail が tmp-progress.json に書かれることを検証する。
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import progress_store
import staged_pipeline


@pytest.fixture
def project_ts(tmp_path):
    """script stage まで承認済の project を 1 つ用意する (= tts を next stage に)。"""
    ts_path = str(tmp_path)
    progress_store.mark_generated(ts_path, "script")
    progress_store.mark_approved(ts_path, "script")
    return ts_path


def test_run_next_stage_failure_writes_structured_error_detail(project_ts: str) -> None:
    """tts runner が例外を raise したとき、error_detail が書かれる。"""
    fake_screenplay = {"caption": "x", "scenes": []}

    with patch.object(
        staged_pipeline,
        "STAGE_RUNNERS",
        {
            **staged_pipeline.STAGE_RUNNERS,
            "tts": lambda sp, ts: (_ for _ in ()).throw(
                RuntimeError("Your credit balance is too low (ElevenLabs)")
            ),
        },
    ):
        with pytest.raises(RuntimeError):
            staged_pipeline.run_next_stage(fake_screenplay, "dummy", project_ts)

    p = progress_store.load(project_ts)
    block = p["stages"]["tts"]
    assert block["status"] == "failed"
    detail = block["error_detail"]
    assert detail["type"] == "credit_exhausted"
    assert "credit balance" in detail["message"]
    assert "クレジット" in detail["actionable_hint"]


def test_run_next_stage_propagates_exception(project_ts: str) -> None:
    """progress_store への書き込み有無に関わらず、上位への例外伝播は維持される。"""
    fake_screenplay = {"caption": "x", "scenes": []}

    with patch.object(
        staged_pipeline,
        "STAGE_RUNNERS",
        {
            **staged_pipeline.STAGE_RUNNERS,
            "tts": lambda sp, ts: (_ for _ in ()).throw(ValueError("boom")),
        },
    ):
        with pytest.raises(ValueError, match="boom"):
            staged_pipeline.run_next_stage(fake_screenplay, "dummy", project_ts)


def test_record_stage_failure_swallows_internal_errors(project_ts: str) -> None:
    """mark_stage_failed 内部で例外発生時、pipeline は止めない (= best-effort)。"""
    with patch.object(
        progress_store,
        "mark_stage_failed",
        side_effect=OSError("disk error"),
    ):
        # 呼出側 _record_stage_failure は logger.warning だけ出して raise しない
        staged_pipeline._record_stage_failure(
            project_ts, "tts", RuntimeError("foo"),
        )
    # ここまで到達すれば pass (= 例外が抜けてこなかった)


def test_run_next_stage_success_does_not_set_failed(project_ts: str) -> None:
    """成功 path は無変更 — error_detail は書かれない。"""
    fake_screenplay = {"caption": "x", "scenes": []}

    def fake_tts(sp, ts):
        progress_store.mark_generated(ts, "tts")

    with patch.object(
        staged_pipeline,
        "STAGE_RUNNERS",
        {**staged_pipeline.STAGE_RUNNERS, "tts": fake_tts},
    ):
        result = staged_pipeline.run_next_stage(fake_screenplay, "dummy", project_ts)

    assert result == "tts"
    p = progress_store.load(project_ts)
    assert p["stages"]["tts"].get("status") != "failed"
    assert p["stages"]["tts"].get("error_detail") is None
