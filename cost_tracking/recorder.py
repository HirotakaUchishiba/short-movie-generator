"""各 stage 用の記録 facade。

呼び出し側の各 client (video_analyzer / elevenlabs_client / imagen_client /
fal_video_client / lipsync_client) がここを叩くだけで良いように、
provider / stage / pricing 計算 / 永続化を 1 関数に集約する。

各 ``record_*`` 関数の責務:
  1. pricebook から単価を取得
  2. pricing の純粋関数で USD コストを計算
  3. records.make_record で CostRecord を構築
  4. records.append で JSONL に追記
  5. 構築した CostRecord を返す
"""
from __future__ import annotations

from typing import Any

from cost_tracking import pricebook, pricing, records


def record_analyze(
    *,
    project_ts: str | None,
    model: str,
    input_tokens: int,
    output_tokens: int,
    operation: str = "generate",
    metadata: dict[str, Any] | None = None,
) -> records.CostRecord:
    unit_prices = pricebook.get_unit_prices("anthropic", model)
    cost_usd = pricing.compute_anthropic_cost(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        unit_prices=unit_prices,
    )
    rec = records.make_record(
        project_ts=project_ts,
        stage="analyze",
        operation=operation,
        provider="anthropic",
        model=model,
        units={"input_tokens": float(input_tokens), "output_tokens": float(output_tokens)},
        unit_prices=unit_prices,
        cost_usd=cost_usd,
        metadata=metadata,
    )
    records.append(rec)
    return rec


def record_tts(
    *,
    project_ts: str | None,
    model: str,
    characters: int,
    scene_index: int | None = None,
    line_index: int | None = None,
    operation: str = "generate",
    metadata: dict[str, Any] | None = None,
) -> records.CostRecord:
    unit_prices = pricebook.get_unit_prices("elevenlabs", model)
    cost_usd = pricing.compute_elevenlabs_cost(
        characters=characters,
        unit_prices=unit_prices,
    )
    rec = records.make_record(
        project_ts=project_ts,
        stage="tts",
        operation=operation,
        provider="elevenlabs",
        model=model,
        units={"characters": float(characters)},
        unit_prices=unit_prices,
        cost_usd=cost_usd,
        scene_index=scene_index,
        line_index=line_index,
        metadata=metadata,
    )
    records.append(rec)
    return rec


def record_imagen(
    *,
    project_ts: str | None,
    model: str,
    image_count: int = 1,
    scene_index: int | None = None,
    operation: str = "generate",
    metadata: dict[str, Any] | None = None,
) -> records.CostRecord:
    unit_prices = pricebook.get_unit_prices("google", model)
    cost_usd = pricing.compute_imagen_cost(
        images=image_count,
        unit_prices=unit_prices,
    )
    rec = records.make_record(
        project_ts=project_ts,
        stage="bg",
        operation=operation,
        provider="google",
        model=model,
        units={"images": float(image_count)},
        unit_prices=unit_prices,
        cost_usd=cost_usd,
        scene_index=scene_index,
        metadata=metadata,
    )
    records.append(rec)
    return rec


def record_kling(
    *,
    project_ts: str | None,
    model: str,
    duration_sec: float,
    scene_index: int | None = None,
    operation: str = "generate",
    metadata: dict[str, Any] | None = None,
) -> records.CostRecord:
    """Kling 動画生成の記録。``duration_sec`` は実際に課金される秒数 (5/10 等)。"""
    unit_prices = pricebook.get_unit_prices("fal", model)
    cost_usd = pricing.compute_kling_cost(
        duration_sec=duration_sec,
        unit_prices=unit_prices,
    )
    rec = records.make_record(
        project_ts=project_ts,
        stage="kling",
        operation=operation,
        provider="fal",
        model=model,
        units={"duration_sec": float(duration_sec)},
        unit_prices=unit_prices,
        cost_usd=cost_usd,
        scene_index=scene_index,
        metadata=metadata,
    )
    records.append(rec)
    return rec


def record_lipsync(
    *,
    project_ts: str | None,
    model: str,
    duration_sec: float,
    scene_index: int | None = None,
    operation: str = "generate",
    metadata: dict[str, Any] | None = None,
) -> records.CostRecord:
    unit_prices = pricebook.get_unit_prices("sync", model)
    cost_usd = pricing.compute_sync_cost(
        duration_sec=duration_sec,
        unit_prices=unit_prices,
    )
    rec = records.make_record(
        project_ts=project_ts,
        stage="lipsync",
        operation=operation,
        provider="sync",
        model=model,
        units={"duration_sec": float(duration_sec)},
        unit_prices=unit_prices,
        cost_usd=cost_usd,
        scene_index=scene_index,
        metadata=metadata,
    )
    records.append(rec)
    return rec
