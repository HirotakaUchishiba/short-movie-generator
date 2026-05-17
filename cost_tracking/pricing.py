"""units → USD の純粋計算関数。

副作用を持たない。pricebook の単価は呼び出し側 (recorder / estimator) で取得し、
``unit_prices`` 引数として渡す前提。
"""
from __future__ import annotations


def compute_anthropic_cost(
    *,
    input_tokens: float,
    output_tokens: float,
    unit_prices: dict[str, float],
) -> float:
    """Claude API: ``(input × in_per_mtok + output × out_per_mtok) / 1e6``。"""
    in_rate = unit_prices["input_per_mtok"]
    out_rate = unit_prices["output_per_mtok"]
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000


def compute_elevenlabs_cost(
    *,
    characters: float,
    unit_prices: dict[str, float],
) -> float:
    """ElevenLabs: ``characters × credit_multiplier × usd_per_credit``。"""
    multiplier = unit_prices["credit_multiplier"]
    usd_per_credit = unit_prices["usd_per_credit"]
    return characters * multiplier * usd_per_credit


def compute_imagen_cost(
    *,
    images: float,
    unit_prices: dict[str, float],
) -> float:
    """Imagen: ``images × usd_per_image``。"""
    return images * unit_prices["usd_per_image"]


def compute_gemini_text_cost(
    *,
    input_tokens: float,
    output_tokens: float,
    unit_prices: dict[str, float],
) -> float:
    """Gemini text: ``(input × in_per_mtok + output × out_per_mtok) / 1e6``。

    Anthropic と同じ MTok 単価ベース (= input/output 別レート)。
    """
    in_rate = unit_prices["input_per_mtok"]
    out_rate = unit_prices["output_per_mtok"]
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000


def compute_kling_cost(
    *,
    duration_sec: float,
    unit_prices: dict[str, float],
) -> float:
    """Kling: ``duration_sec × usd_per_sec``。

    課金 bucket (5/10s 切り上げ等) は呼び出し側で確定させてから渡す。
    本関数は受け取った ``duration_sec`` をそのまま単価に乗じるだけ。
    """
    return duration_sec * unit_prices["usd_per_sec"]


def compute_sync_cost(
    *,
    duration_sec: float,
    unit_prices: dict[str, float],
) -> float:
    """Sync.so / lipsync: ``duration_sec × usd_per_sec``。"""
    return duration_sec * unit_prices["usd_per_sec"]


def kling_billed_duration(audio_duration_sec: float, buckets: list[int]) -> int:
    """Kling の課金 bucket (5/10s 等) に audio_duration を切り上げる。

    ``buckets`` が空なら ``ceil(audio_duration_sec)`` を返す。
    すべての bucket より長ければ最大 bucket を返す (= 上限張り付き)。
    """
    if not buckets:
        import math

        return max(1, math.ceil(audio_duration_sec))
    sorted_buckets = sorted(int(b) for b in buckets)
    for b in sorted_buckets:
        if audio_duration_sec <= b:
            return b
    return sorted_buckets[-1]


def usd_to_jpy(usd: float, jpy_per_usd: float) -> float:
    return usd * jpy_per_usd
