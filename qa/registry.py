"""Phase 2: stage → validators マッピング + 一括実行 helper。

auto_loop / preview_server / eval_validators がここを叩くだけで全 stage 横断の
validator フローが揃う。

無効化:
    config.QA_VALIDATORS_ENABLED = False  ... 全 validator skip
    config.QA_VALIDATOR_BLACKLIST = ("lipsync_quality",)  ... 個別 skip
"""
from __future__ import annotations

import logging
from typing import Callable

import config
from qa.validators.audio_clipping import check_audio_clipping
from qa.validators.audio_silence import check_audio_silence
from qa.validators.base import ValidationResult
from qa.validators.character_drift import check_character_drift
from qa.validators.lipsync_quality import check_lipsync_quality
from qa.validators.story_pacing import check_story_pacing
from qa.validators.subtitle_audio_sync import check_subtitle_audio_sync
from qa.validators.subtitle_overlap import check_subtitle_overlap
from qa.validators.subtitle_readability import check_subtitle_readability
from qa.validators.subtitle_render import check_subtitle_render
from qa.validators.subtitle_timing import check_subtitle_timing

logger = logging.getLogger(__name__)

ValidatorFn = Callable[..., list[ValidationResult]]

VALIDATORS_BY_STAGE: dict[str, list[tuple[str, ValidatorFn]]] = {
    "tts": [
        ("audio_silence", check_audio_silence),
        ("audio_clipping", check_audio_clipping),
        ("story_pacing", check_story_pacing),
    ],
    "bg": [
        ("subtitle_overlap", check_subtitle_overlap),
    ],
    "kling": [
        ("character_drift", check_character_drift),
    ],
    "scene": [
        ("lipsync_quality", check_lipsync_quality),
    ],
    "overlay": [
        ("subtitle_readability", check_subtitle_readability),
        ("subtitle_timing", check_subtitle_timing),
        ("subtitle_audio_sync", check_subtitle_audio_sync),
        ("subtitle_render", check_subtitle_render),
    ],
}


def _enabled_validators_for(stage: str) -> list[tuple[str, ValidatorFn]]:
    if not config.QA_VALIDATORS_ENABLED:
        return []
    blacklist = set(config.QA_VALIDATOR_BLACKLIST or ())
    return [(name, fn) for name, fn in VALIDATORS_BY_STAGE.get(stage, [])
            if name not in blacklist]


def run_validators_for_stage(
    ts_path: str, stage: str, *,
    screenplay: dict | None = None,
) -> list[ValidationResult]:
    """指定 stage の全 enabled validator を実行し結果を結合して返す。"""
    out: list[ValidationResult] = []
    for name, fn in _enabled_validators_for(stage):
        try:
            results = fn(ts_path, screenplay=screenplay)
        except Exception as e:
            logger.warning("[validator %s] crashed: %s", name, e)
            continue
        if results is None:
            continue
        if isinstance(results, list):
            out.extend(results)
        else:
            out.append(results)
    return out


def stage_validator_names(stage: str) -> list[str]:
    return [name for name, _ in VALIDATORS_BY_STAGE.get(stage, [])]


def aggregate_scores(results: list[ValidationResult]) -> dict[str, float]:
    """validator_scores カラム用の集計 (= 平均スコア + fail 件数)。"""
    if not results:
        return {"count": 0, "passed": 0, "failed": 0, "avg_score": 0.0}
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    avg = sum(r.score for r in results) / len(results)
    return {
        "count": float(len(results)),
        "passed": float(passed),
        "failed": float(failed),
        "avg_score": float(avg),
    }
