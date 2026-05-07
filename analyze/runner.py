"""analyze ジョブを別 thread で実行する runner。

- threading.Semaphore(_MAX_CONCURRENT) で同時実行数を制限し、
  demucs / faster-whisper / Claude のメモリ衝突を物理的に回避
- 各フェーズ境界で SQLite の analyze_phases に状態と所要時間を記録
- progress.publish() で SSE subscriber に event を push
- コストゲート: Claude 呼び出し直前に awaiting_confirm に遷移し、
  ユーザー confirm or cancel を polling で待つ
"""
import logging
import threading
import time
from dataclasses import asdict

import video_analyzer
from analyze import cost, job, pipeline, progress
from analyze.pipeline import AnalyzeCancelled, AnalyzeOptions, default_output_path
from cost_tracking import estimator as cost_estimator
from cost_tracking import recorder as cost_recorder

logger = logging.getLogger(__name__)


class CostGateTimeout(Exception):
    """cost gate が timeout した時に raise される (AnalyzeCancelled とは別扱い)。

    AnalyzeCancelled は「ユーザーが意図的にキャンセル」を表すため、
    timeout を分けて failed 状態として記録する (UI 上の混乱を避ける)。
    """


# 同時実行数の上限
_MAX_CONCURRENT = 1
_CONCURRENT = threading.Semaphore(_MAX_CONCURRENT)

# コストゲート confirm 待ちの polling 間隔と timeout
CONFIRM_POLL_INTERVAL_SEC = 0.5
CONFIRM_TIMEOUT_SEC = 1800  # 30 分待っても confirm が来なければ failed


def _wait_for_confirm(job_id: str, timeout_sec: float = CONFIRM_TIMEOUT_SEC,
                       poll_interval_sec: float = CONFIRM_POLL_INTERVAL_SEC,
                       ) -> bool:
    """awaiting_confirm のジョブが confirm or cancel されるのを polling で待つ。

    Returns:
        True なら confirm 成功 (Claude 続行可)、False ならユーザーキャンセル。
    Raises:
        CostGateTimeout: timeout 時。failed 状態と error 文字列が SQLite に
        記録され、failed event も publish 済みの状態で raise する。
    """
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        j = job.get_job(job_id)
        if j.cancellation_requested:
            return False
        if j.status == "running":
            return True
        time.sleep(poll_interval_sec)

    timeout_min = max(1, int(round(timeout_sec / 60)))
    err = (
        f"コスト確認の timeout ({timeout_min} 分以内に "
        "Claude 呼び出しが confirm されませんでした)"
    )
    job.transition_status(job_id, "failed", error=err)
    progress.publish(job_id, "failed", {"error": err, "phase": "cost_gate"})
    raise CostGateTimeout(err)


class _PhaseTracker:
    """analyze pipeline 各フェーズの開始 / 完了 / skip を SQLite に記録する helper。"""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.phase_start_times: dict[str, float] = {}

    def handle(self, event: str, data: dict) -> None:
        phase = data.get("phase")
        if event == "phase_start" and phase:
            self.phase_start_times[phase] = time.time()
            try:
                job.start_phase(self.job_id, phase)
            except Exception:
                logger.exception(
                    "start_phase failed: %s/%s", self.job_id, phase,
                )
        elif event == "phase_complete" and phase:
            started = self.phase_start_times.get(phase)
            duration_ms = (
                int((time.time() - started) * 1000) if started else None
            )
            try:
                job.complete_phase(
                    self.job_id, phase, duration_ms=duration_ms,
                )
            except Exception:
                logger.exception(
                    "complete_phase failed: %s/%s", self.job_id, phase,
                )
        elif event == "phase_skipped" and phase:
            try:
                job.skip_phase(self.job_id, phase)
            except Exception:
                logger.exception(
                    "skip_phase failed: %s/%s", self.job_id, phase,
                )
        elif event == "claude_usage":
            self._record_claude_cost(data)

    def _record_claude_cost(self, data: dict) -> None:
        input_tokens = data.get("input_tokens")
        output_tokens = data.get("output_tokens")
        if input_tokens is None or output_tokens is None:
            return
        try:
            rec = cost_recorder.record_analyze(
                project_ts=self.job_id,
                model=video_analyzer.ANALYZER_MODEL,
                input_tokens=int(input_tokens),
                output_tokens=int(output_tokens),
            )
            job.update_job(self.job_id, actual_cost_usd=rec.cost_usd)
        except Exception:
            logger.exception(
                "cost recording failed (analyze): %s", self.job_id,
            )


def _build_cost_gate(job_id: str):
    """Claude 呼び出し直前の cost gate callback を返す。awaiting_confirm に
    遷移して confirm を polling で待つ。

    token 数は ``analyze.cost.estimate_tokens`` で概算し、USD 換算は
    実コスト履歴から ``cost_tracking.estimator.estimate_analyze`` で算定する
    (= 履歴不足なら ``cost_usd`` は ``None``)。
    """

    def cost_gate(
        frame_count: int,
        transcript: dict,
        shot_count: int,
        known_furigana_count: int,
    ) -> bool:
        tokens = cost.estimate_tokens(
            frame_count=frame_count,
            transcript=transcript,
            shot_count=shot_count,
            known_furigana_count=known_furigana_count,
        )
        estimate = cost_estimator.estimate_analyze(
            input_tokens=tokens["input_tokens"],
            output_tokens=tokens["output_tokens"],
            model=video_analyzer.ANALYZER_MODEL,
        )
        job.transition_status(
            job_id, "awaiting_confirm",
            estimated_cost_usd=estimate.cost_usd,
        )
        progress.publish(job_id, "dryrun_complete", {
            "frame_count": frame_count,
            "input_tokens": tokens["input_tokens"],
            "output_tokens": tokens["output_tokens"],
            "token_breakdown": tokens["breakdown"],
            **asdict(estimate),
        })
        return _wait_for_confirm(job_id)

    return cost_gate


def start(job_id: str) -> threading.Thread:
    """ジョブを daemon thread で起動する。"""
    t = threading.Thread(
        target=_run_job, args=(job_id,),
        name=f"analyze-{job_id}", daemon=True,
    )
    t.start()
    return t


def _run_job(job_id: str) -> None:
    try:
        with _CONCURRENT:
            _run_job_impl(job_id)
    except Exception as e:
        logger.exception("analyze job %s failed in runner", job_id)
        try:
            job.transition_status(job_id, "failed", error=str(e))
            progress.publish(job_id, "failed",
                              {"error": str(e), "phase": "runner"})
        except Exception:
            logger.exception("post-error update failed for %s", job_id)


def _run_job_impl(job_id: str) -> None:
    j = job.get_job(job_id)
    video_path = job.reference_video_path(j.video_sha256)
    if video_path is None:
        raise FileNotFoundError(
            f"reference video not found: sha256={j.video_sha256}"
        )

    options = AnalyzeOptions.from_dict(j.options)

    job.transition_status(job_id, "running")
    progress.publish(job_id, "started",
                      {"job_id": job_id, "video_sha256": j.video_sha256})

    tracker = _PhaseTracker(job_id)

    def on_progress(event: str, data: dict) -> None:
        tracker.handle(event, data)
        progress.publish(job_id, event, data)

    def cancel_token() -> bool:
        return job.is_cancellation_requested(job_id)

    try:
        screenplay = pipeline.run(
            video_path=video_path,
            options=options,
            on_progress=on_progress,
            cancel_token=cancel_token,
            on_cost_gate=_build_cost_gate(job_id),
        )
        job.touch_reference_video(j.video_sha256)

        out_path = default_output_path(video_path)
        finished = job.transition_status(
            job_id, "completed",
            screenplay_path=out_path,
        )
        progress.publish(job_id, "completed", {
            "output_path": out_path,
            "scenes": len(screenplay.get("scenes", [])),
            "lines": sum(len(s.get("lines") or [])
                          for s in screenplay.get("scenes", [])),
        })
    except CostGateTimeout:
        # _wait_for_confirm で既に failed 遷移 + publish 済み
        return
    except AnalyzeCancelled:
        job.transition_status(job_id, "cancelled")
        progress.publish(job_id, "cancelled", {})


def confirm(job_id: str) -> None:
    """awaiting_confirm 状態のジョブを running に遷移させる (Claude 続行)。"""
    j = job.get_job(job_id)
    if j.status != "awaiting_confirm":
        raise ValueError(
            f"job {job_id} is not awaiting_confirm (current: {j.status})"
        )
    job.transition_status(job_id, "running")


def cancel(job_id: str) -> None:
    """ジョブのキャンセルを要求する (cooperative)。"""
    job.request_cancellation(job_id)
