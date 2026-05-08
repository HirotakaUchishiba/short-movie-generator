#!/usr/bin/env python3
"""Phase 1: フルオート量産経路の orchestrator (= cron から 1 動画 / 1 invocation)。

`reference URL → fetch_reference → analyze → 各 stage → import_final → publish`
を 1 コマンドで実行する。実装計画 §3 (= Phase 1) の A-1.2 / A-1.3 に対応。

設計:
    - kill-switch (DISABLE_AUTO_LOOP=1) と cap (cost / video) を冒頭で fail-fast
    - 各 internal stage 後に provisional validator を回し、NG なら 1 回 retry
      (= 前世代を qa_failures/ に regenerate_implicit で archive してから regen)
    - retry も NG なら qa_failures に auto_flagged で記録 + Slack + abort
    - 公開先は AUTO_LOOP_ALLOW_PUBLIC=0 (default) の間 unlisted 強制
      (= youtube._resolve_privacy が二重防衛)
    - すべての abort で notify_slack + generation_records.status = "auto_rejected"

使い方:
    python3 scripts/auto_loop.py <URL> --license user_owned [--privacy unlisted] [--dry-run]
"""
from __future__ import annotations

import argparse
import glob
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import log_setup  # noqa: E402
import json  # noqa: E402
import config  # noqa: E402
import progress_store  # noqa: E402
import staged_pipeline  # noqa: E402
from analytics import db as _adb  # noqa: E402
from cost_tracking import budget  # noqa: E402
from notify import notify_slack  # noqa: E402
from qa import recorder as qa_recorder  # noqa: E402
from qa.artifact_paths import stage_artifact_paths  # noqa: E402
from qa.registry import (  # noqa: E402
    aggregate_scores,
    run_validators_for_stage,
)
from qa.validators.base import ValidationResult  # noqa: E402
from improvement import strategy as improvement_strategy  # noqa: E402
from improvement.prompt_injector import compose_instructions  # noqa: E402

logger = logging.getLogger(__name__)

INTERNAL_STAGES = ("tts", "bg", "kling", "scene", "overlay")
VALID_LICENSES = ("user_owned", "fair_use_review", "public_domain")


class AutoLoopAborted(RuntimeError):
    """auto_loop の途中で停止する場合。caller で notify_slack 済みの想定。"""


# ───────────── kill-switch / cap ─────────────


def _kill_switch_guard() -> None:
    if os.environ.get("DISABLE_AUTO_LOOP") == "1":
        notify_slack("warning",
                     "auto_loop kill-switch active (DISABLE_AUTO_LOOP=1)")
        raise SystemExit("auto_loop disabled by env DISABLE_AUTO_LOOP=1")


def _budget_guard() -> None:
    try:
        budget.assert_within_caps()
    except budget.BudgetExceeded as e:
        notify_slack("warning", f"auto_loop budget exceeded: {e}")
        raise


# ───────────── fetch / analyze / project create ─────────────


def _fetch_reference(reference_url: str, license_status: str,
                     max_duration: float | None) -> dict:
    from scripts.fetch_reference import fetch_and_register
    try:
        return fetch_and_register(reference_url, license_status, max_duration)
    except (ValueError, RuntimeError) as e:
        notify_slack("error", f"fetch_reference failed: {e}",
                     context={"url": reference_url})
        raise AutoLoopAborted(str(e)) from e


def _run_analyze(ref_path: str, ref_sha: str,
                 *, instructions: str | None = None) -> str:
    """analyze.run() を呼んで screenplay 名 (= "auto_<sha12>") を返す。

    Phase 3: ``instructions`` で improvement.prompt_injector の組み立て結果を
    Claude system prompt に注入する経路。``IMPROVEMENT_STRATEGY=baseline``
    なら呼び出し側で ``None`` を渡してくる。
    """
    from analyze import AnalyzeOptions, run as analyze_run

    output_path = os.path.join(
        config.SCREENPLAYS_DIR, f"auto_{ref_sha[:12]}.json",
    )
    os.makedirs(config.SCREENPLAYS_DIR, exist_ok=True)
    options = AnalyzeOptions(instructions=instructions) if instructions else None
    try:
        analyze_run(
            video_path=ref_path, output_path=output_path,
            options=options,
        )
    except Exception as e:
        notify_slack("error", f"analyze failed: {e}",
                     context={"ref_path": ref_path})
        raise AutoLoopAborted(f"analyze failed: {e}") from e
    return Path(output_path).stem


def _create_project(sp_name: str) -> str:
    """ts を発行 + run_script で snapshot 化 + Stage 1 を mark_generated。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_path = os.path.join(config.TEMP_DIR, ts)
    os.makedirs(ts_path, exist_ok=True)
    template = staged_pipeline.load_template(sp_name)
    staged_pipeline.run_script(template, sp_name, ts_path)
    logger.info("[auto-loop] project created: ts=%s sp=%s", ts, sp_name)
    return ts


# ───────────── stage chain + validator + retry ─────────────


def _load_screenplay(sp_name: str, ts_path: str) -> dict:
    if progress_store.is_generated(ts_path, "script"):
        return staged_pipeline.load_project_screenplay(ts_path)
    return staged_pipeline.load_template(sp_name)


def _run_one_stage(sp_name: str, ts: str, expected_stage: str) -> None:
    """次 stage を 1 つ実行する。expected_stage と一致しなければ raise。"""
    ts_path = os.path.join(config.TEMP_DIR, ts)
    nxt = progress_store.next_stage(ts_path)
    if nxt != expected_stage:
        raise AutoLoopAborted(
            f"stage 順序ずれ: expected={expected_stage}, next_stage={nxt}",
        )
    sp = _load_screenplay(sp_name, ts_path)
    started = time.time()
    staged_pipeline.run_next_stage(sp, sp_name, ts_path)
    elapsed = time.time() - started
    if elapsed > config.AUTO_LOOP_STAGE_TIMEOUT_SEC:
        notify_slack(
            "warning",
            f"stage {expected_stage} took {elapsed:.0f}s "
            f"(soft limit {config.AUTO_LOOP_STAGE_TIMEOUT_SEC}s)",
            context={"ts": ts},
        )


def _validate_stage(ts: str, stage: str) -> list[ValidationResult]:
    """Phase 2 validator スイートを stage 単位で実行する。

    `qa.registry.run_validators_for_stage` が disabled / blacklist を尊重しつつ
    全 validator の結果を返す。fail だけを caller (= run_one_video) が見る。
    """
    ts_path = os.path.join(config.TEMP_DIR, ts)
    sp = _load_screenplay_for_validate(ts_path)
    results = run_validators_for_stage(ts_path, stage, screenplay=sp)
    _record_validator_failures(ts, stage, [r for r in results if not r.passed])
    _update_validator_scores(ts, stage, results)
    return results


def _load_screenplay_for_validate(ts_path: str) -> dict | None:
    """validator が screenplay 引数を要する場合の lazy load (= 失敗を吸収)。"""
    try:
        return staged_pipeline.load_project_screenplay(ts_path)
    except Exception as e:
        logger.warning("[auto-loop] load_project_screenplay failed: %s", e)
        return None


def _record_validator_failures(ts: str, stage: str,
                               fails: list[ValidationResult]) -> None:
    ts_path = os.path.join(config.TEMP_DIR, ts)
    snapshot = staged_pipeline.project_screenplay_path(ts_path)
    snap = snapshot if os.path.exists(snapshot) else None
    for r in fails:
        if not r.tag:
            continue
        artifact_paths = stage_artifact_paths(
            ts_path, stage, r.scene_idx, r.line_idx,
        )
        try:
            qa_recorder.record_failure(
                ts=ts, stage=stage, source="auto_flagged",
                tags=[r.tag], note=r.reason,
                scene_idx=r.scene_idx, line_idx=r.line_idx,
                artifact_paths=artifact_paths,
                screenplay_snapshot_path=snap,
            )
        except Exception as e:
            logger.warning(
                "[auto-loop] qa_recorder.record_failure failed: %s", e,
            )


def _update_validator_scores(ts: str, stage: str,
                             results: list[ValidationResult]) -> None:
    """``generation_records.validator_scores`` の stage キーに集計を書き込む。"""
    summary = aggregate_scores(results)
    existing: dict = {}
    rec = _adb.get_generation_record(ts)
    if rec:
        try:
            existing = json.loads(rec.get("validator_scores") or "{}")
            if not isinstance(existing, dict):
                existing = {}
        except (json.JSONDecodeError, TypeError):
            existing = {}
    existing[stage] = summary
    try:
        _adb.update_generation_record(ts, validator_scores=existing)
    except Exception as e:
        logger.warning("[auto-loop] update_generation_record failed: %s", e)


def _archive_before_retry(ts: str, stage: str,
                          scene_idx: int | None = None) -> None:
    """retry 直前に前世代を regenerate_implicit でアーカイブ。"""
    ts_path = os.path.join(config.TEMP_DIR, ts)
    paths = stage_artifact_paths(ts_path, stage,
                                 scene_idx=scene_idx, line_idx=None)
    if not any(os.path.exists(p) for p in paths):
        return
    snapshot = staged_pipeline.project_screenplay_path(ts_path)
    snap = snapshot if os.path.exists(snapshot) else None
    try:
        qa_recorder.record_failure(
            ts=ts, stage=stage, source="regenerate_implicit",
            tags=None, note=None, scene_idx=scene_idx,
            artifact_paths=paths, screenplay_snapshot_path=snap,
        )
    except Exception as e:
        logger.warning("[auto-loop] retry archive failed: %s", e)


def _retry_stage(sp_name: str, ts: str, stage: str,
                 scene_idx: int | None = None) -> None:
    """stage を regen する。``scene_idx`` 指定で per-scene retry。"""
    _archive_before_retry(ts, stage, scene_idx=scene_idx)
    ts_path = os.path.join(config.TEMP_DIR, ts)
    sp = _load_screenplay(sp_name, ts_path)
    logger.info("[auto-loop] retry stage=%s scene=%s ts=%s",
                stage, scene_idx, ts)
    staged_pipeline.regen(stage, sp, ts_path,
                          scene_idx=scene_idx, line_idx=None,
                          force=True, screenplay_name=sp_name)


def _retry_failed_scenes(sp_name: str, ts: str, stage: str,
                         fails: list[ValidationResult]) -> None:
    """fail のあったシーンだけを regen する。stage 全体 fail なら full regen。"""
    fail_scenes = sorted({r.scene_idx for r in fails
                          if r.scene_idx is not None})
    if fail_scenes:
        for s_idx in fail_scenes:
            _retry_stage(sp_name, ts, stage, scene_idx=s_idx)
    else:
        _retry_stage(sp_name, ts, stage, scene_idx=None)


def _approve(ts: str, stage: str) -> None:
    ts_path = os.path.join(config.TEMP_DIR, ts)
    progress_store.mark_approved(ts_path, stage)


# ───────────── final import / publish ─────────────


def _import_raw_as_final(ts: str) -> None:
    """Stage 6 で書き出された pipeline raw を Stage 7 取込として canonical 化。"""
    raw_path = os.path.join(config.OUTPUT_DIR, f"reels_{ts}.mp4")
    if not os.path.exists(raw_path):
        raise AutoLoopAborted(f"pipeline raw が見つかりません: {raw_path}")
    from final_import import import_final
    import_final(ts, raw_path, source="cli", skip_fingerprint=False)


def _publish_youtube(ts: str, privacy: str) -> dict:
    from final_import.publish import publish
    return publish(ts, "youtube", privacy=privacy)


# ───────────── 全体経路 ─────────────


def run_one_video(
    reference_url: str,
    *,
    license_status: str,
    privacy: str = "unlisted",
    max_duration: float | None = 90,
    dry_run: bool = False,
) -> str:
    """1 動画分の全経路を実行し、ts を返す。"""
    if license_status not in VALID_LICENSES:
        # fetch_and_register でも reject されるが、orchestrator の責務として
        # 先に gate しておく (= 失敗の場所をテストで stub せず固定できる)。
        raise AutoLoopAborted(
            f"invalid license: {license_status} "
            f"(valid: {VALID_LICENSES})",
        )
    _kill_switch_guard()
    _budget_guard()

    ref = _fetch_reference(reference_url, license_status, max_duration)

    # Phase 3: bandit で各軸の値を選択し、analyze の instructions に注入する。
    # baseline は空 dict + None を返すので Phase 2 と同等の挙動になる。seed には
    # 参考動画の sha256 を渡し、同じ参考動画 + 同じ DB state なら同じ選択が再現
    # できる経路を確保する (= 監査 / デバッグ向け)。
    assignments = improvement_strategy.select_assignments_for_video(
        seed=ref["sha256"],
    )
    if assignments:
        logger.info(
            "[auto-loop] strategy=%s assignments=%s",
            config.IMPROVEMENT_STRATEGY,
            ", ".join(
                f"{ax}={v}({sub})"
                for ax, (v, sub) in sorted(assignments.items())
            ),
        )
    instructions = compose_instructions(assignments)

    sp_name = _run_analyze(
        ref["path"], ref["sha256"], instructions=instructions,
    )
    ts = _create_project(sp_name)
    _adb.update_generation_record(
        ts,
        reference_video_id=ref["sha256"],
        screenplay_sha=ref["sha256"][:12],
    )
    # shadow / active なら experiment_assignments に永続化 (= 後で
    # post_metrics と join して reward を更新する)。
    improvement_strategy.record_assignments(ts, assignments)
    # Stage 1 (script) は run_script で mark_generated 済み → approve のみ
    _approve(ts, "script")

    try:
        for stage in INTERNAL_STAGES:
            max_retries = config.QA_RETRY_LIMITS.get(stage, 1)
            _run_one_stage(sp_name, ts, stage)
            retries = 0
            while True:
                results = _validate_stage(ts, stage)
                fails = [r for r in results if not r.passed]
                if not fails:
                    break
                if retries >= max_retries:
                    notify_slack(
                        "error",
                        f"auto_loop: stage {stage} validator failed "
                        f"after {retries} retries",
                        context={"ts": ts, "fails": len(fails)},
                    )
                    raise AutoLoopAborted(
                        f"stage {stage} validator NG after retry: "
                        f"{[r.reason for r in fails][:3]}",
                    )
                retries += 1
                _retry_failed_scenes(sp_name, ts, stage, fails)
            _approve(ts, stage)

        # Stage 7: raw を canonical に (= CapCut 編集スキップ)
        _import_raw_as_final(ts)
        _approve(ts, "final_import")

        if dry_run:
            logger.info("[auto-loop] dry_run: publish skip ts=%s", ts)
            _adb.update_generation_record(ts, status="completed")
            return ts

        # Stage 8: publish (= unlisted 強制 by youtube._resolve_privacy)
        result = _publish_youtube(ts, privacy=privacy)
        notify_slack(
            "info",
            f"auto_loop published: ts={ts}",
            context={
                "url": result.get("url") or "",
                "video_id": result.get("video_id") or "",
                "privacy": privacy,
            },
        )
    except AutoLoopAborted:
        _adb.update_generation_record(ts, status="auto_rejected")
        raise
    except Exception as e:
        notify_slack("critical", f"auto_loop unexpected error: {e}",
                     context={"ts": ts})
        _adb.update_generation_record(ts, status="auto_rejected")
        raise

    _adb.update_generation_record(ts, status="completed")
    return ts


# ───────────── CLI ─────────────


def main() -> int:
    log_setup.setup()
    parser = argparse.ArgumentParser(prog="auto_loop")
    parser.add_argument("url", help="参考動画 URL (yt-dlp 対応)")
    parser.add_argument("--license", required=True, choices=VALID_LICENSES)
    parser.add_argument(
        "--privacy", default="unlisted",
        choices=("private", "unlisted", "public"),
        help="YouTube 公開範囲 (= AUTO_LOOP_ALLOW_PUBLIC=0 中は public→unlisted に降格)",
    )
    parser.add_argument("--max-duration", type=float, default=90)
    parser.add_argument("--dry-run", action="store_true",
                        help="publish 直前で停止 (= テスト / 検証用)")
    args = parser.parse_args()

    try:
        ts = run_one_video(
            args.url,
            license_status=args.license,
            privacy=args.privacy,
            max_duration=args.max_duration,
            dry_run=args.dry_run,
        )
    except SystemExit:
        # _kill_switch_guard が raise する SystemExit は通す
        return 2
    except AutoLoopAborted as e:
        logger.error("auto_loop aborted: %s", e)
        return 1
    except budget.BudgetExceeded as e:
        logger.error("auto_loop blocked by budget: %s", e)
        return 3
    except Exception as e:
        logger.exception("auto_loop unexpected error: %s", e)
        return 1

    print(f"ts: {ts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
