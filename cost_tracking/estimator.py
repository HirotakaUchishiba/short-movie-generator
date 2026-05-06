"""動的見積もり (cost_records.jsonl の実コスト履歴のみを参照)。

catalog fallback は持たない。履歴が ``MIN_HISTORY_SAMPLES`` 未満なら
``confidence="insufficient"`` を返し、UI 側で「履歴不足」を明示する。

戦略:
  - tts / bg / kling / lipsync: ``cost_usd / units`` の median を per-unit rate とし、
    新しい units に乗じて見積もり (= 実コストベース)
  - analyze: input / output token 単価が record の ``unit_prices`` に保存されているので、
    それぞれの median を取って線形結合 (= input/output 比で歪まない)
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from cost_tracking import pricebook, records

MIN_HISTORY_SAMPLES = 3


@dataclass(frozen=True)
class Estimate:
    cost_usd: float | None
    cost_jpy: float | None
    confidence: str  # "history" | "insufficient" | "partial"
    sample_size: int
    breakdown: dict[str, Any] = field(default_factory=dict)
    note: str = ""


@dataclass(frozen=True)
class MedianRate:
    stage: str
    model: str
    usd_per_unit: float | None
    unit_label: str  # "character" | "image" | "sec" | "input_token" 等
    confidence: str  # "history" | "insufficient"
    sample_size: int
    jpy_per_usd: float


def _insufficient(sample_size: int, reason: str) -> Estimate:
    return Estimate(
        cost_usd=None,
        cost_jpy=None,
        confidence="insufficient",
        sample_size=sample_size,
        breakdown={},
        note=reason,
    )


def _per_unit_rates(history: list[records.CostRecord], unit_key: str) -> list[float]:
    rates: list[float] = []
    for r in history:
        units = r.units.get(unit_key)
        if units and units > 0:
            rates.append(r.cost_usd / units)
    return rates


def _from_history_per_unit(
    *,
    stage: str,
    model: str,
    units_value: float,
    unit_key: str,
    unit_label: str,
) -> Estimate:
    history = list(records.iter_filtered(stage=stage, model=model))
    rates = _per_unit_rates(history, unit_key)
    if len(rates) < MIN_HISTORY_SAMPLES:
        return _insufficient(
            len(rates),
            f"{stage}/{model} の履歴が不足 ({len(rates)}/{MIN_HISTORY_SAMPLES})",
        )
    median_rate = statistics.median(rates)
    cost_usd = units_value * median_rate
    cost_jpy = cost_usd * pricebook.jpy_per_usd()
    return Estimate(
        cost_usd=cost_usd,
        cost_jpy=cost_jpy,
        confidence="history",
        sample_size=len(rates),
        breakdown={
            unit_label: units_value,
            f"median_usd_per_{unit_label}": median_rate,
        },
    )


def estimate_tts(*, characters: int, model: str) -> Estimate:
    return _from_history_per_unit(
        stage="tts",
        model=model,
        units_value=float(characters),
        unit_key="characters",
        unit_label="character",
    )


def estimate_imagen(*, image_count: int, model: str) -> Estimate:
    return _from_history_per_unit(
        stage="bg",
        model=model,
        units_value=float(image_count),
        unit_key="images",
        unit_label="image",
    )


def estimate_kling(*, duration_sec: float, model: str) -> Estimate:
    return _from_history_per_unit(
        stage="kling",
        model=model,
        units_value=float(duration_sec),
        unit_key="duration_sec",
        unit_label="sec",
    )


def estimate_lipsync(*, duration_sec: float, model: str) -> Estimate:
    return _from_history_per_unit(
        stage="lipsync",
        model=model,
        units_value=float(duration_sec),
        unit_key="duration_sec",
        unit_label="sec",
    )


def estimate_analyze(
    *, input_tokens: int, output_tokens: int, model: str
) -> Estimate:
    """Analyze は in/out 単価を別々に median して線形結合する。"""
    history = list(records.iter_filtered(stage="analyze", model=model))
    in_rates = [
        r.unit_prices["input_per_mtok"]
        for r in history
        if "input_per_mtok" in r.unit_prices
    ]
    out_rates = [
        r.unit_prices["output_per_mtok"]
        for r in history
        if "output_per_mtok" in r.unit_prices
    ]
    if len(in_rates) < MIN_HISTORY_SAMPLES or len(out_rates) < MIN_HISTORY_SAMPLES:
        return _insufficient(
            min(len(in_rates), len(out_rates)),
            f"analyze/{model} の履歴が不足 ({len(in_rates)}/{MIN_HISTORY_SAMPLES})",
        )
    median_in = statistics.median(in_rates)
    median_out = statistics.median(out_rates)
    cost_usd = (input_tokens * median_in + output_tokens * median_out) / 1_000_000
    cost_jpy = cost_usd * pricebook.jpy_per_usd()
    return Estimate(
        cost_usd=cost_usd,
        cost_jpy=cost_jpy,
        confidence="history",
        sample_size=min(len(in_rates), len(out_rates)),
        breakdown={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "median_input_per_mtok": median_in,
            "median_output_per_mtok": median_out,
        },
    )


_STAGE_TO_UNIT: dict[str, tuple[str, str]] = {
    "tts": ("characters", "character"),
    "bg": ("images", "image"),
    "kling": ("duration_sec", "sec"),
    "lipsync": ("duration_sec", "sec"),
}


def median_rate(stage: str, model: str) -> MedianRate:
    """履歴から per-unit cost の median を返す (= frontend が rate × units で見積もる用)。

    analyze は input/output 別単価のため非対応。代わりに ``estimate_analyze`` を使う。
    """
    if stage not in _STAGE_TO_UNIT:
        raise ValueError(f"median_rate: unsupported stage {stage}")
    unit_key, unit_label = _STAGE_TO_UNIT[stage]
    history = list(records.iter_filtered(stage=stage, model=model))
    rates = _per_unit_rates(history, unit_key)
    jpy = pricebook.jpy_per_usd()
    if len(rates) < MIN_HISTORY_SAMPLES:
        return MedianRate(
            stage=stage,
            model=model,
            usd_per_unit=None,
            unit_label=unit_label,
            confidence="insufficient",
            sample_size=len(rates),
            jpy_per_usd=jpy,
        )
    return MedianRate(
        stage=stage,
        model=model,
        usd_per_unit=statistics.median(rates),
        unit_label=unit_label,
        confidence="history",
        sample_size=len(rates),
        jpy_per_usd=jpy,
    )


def combine(items: list[tuple[str, Estimate]]) -> Estimate:
    """複数の Estimate を ``(label, estimate)`` の組で集約する。

    cost_usd が ``None`` の項は除外して合計。
    1 件でも insufficient があれば confidence は ``"partial"``、
    全件 history なら ``"history"``、全件 insufficient なら ``"insufficient"``。
    """
    valid = [(label, e) for label, e in items if e.cost_usd is not None]
    insufficient = [(label, e) for label, e in items if e.cost_usd is None]
    if not valid:
        return _insufficient(0, "全項目で履歴不足")

    total_usd = sum(e.cost_usd for _, e in valid)
    total_jpy = sum(e.cost_jpy for _, e in valid if e.cost_jpy is not None)
    confidence = "partial" if insufficient else "history"
    sample_size = sum(e.sample_size for _, e in valid)
    breakdown = {label: e.cost_usd for label, e in valid}
    if insufficient:
        breakdown["_insufficient"] = [label for label, _ in insufficient]
    note = (
        f"{len(insufficient)} 項目で履歴不足 (見積もりから除外)"
        if insufficient
        else ""
    )
    return Estimate(
        cost_usd=total_usd,
        cost_jpy=total_jpy,
        confidence=confidence,
        sample_size=sample_size,
        breakdown=breakdown,
        note=note,
    )
