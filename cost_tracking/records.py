"""``CostRecord`` dataclass と ``data/cost_records.jsonl`` の append-only I/O。

ファイル位置は環境変数 ``COST_RECORDS_PATH`` で上書き可。
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "cost_records.jsonl"

_WRITE_LOCK = threading.Lock()

VALID_STAGES = frozenset({
    "analyze", "analyze_rewrite", "tts", "bg", "kling", "lipsync",
})


def _path() -> Path:
    return Path(os.environ.get("COST_RECORDS_PATH", _DEFAULT_PATH))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class CostRecord:
    record_id: str
    timestamp: str
    project_ts: str | None
    stage: str
    operation: str
    scene_index: int | None
    line_index: int | None
    provider: str
    model: str
    units: dict[str, float]
    unit_prices: dict[str, float]
    cost_usd: float
    metadata: dict[str, Any] = field(default_factory=dict)


def make_record(
    *,
    project_ts: str | None,
    stage: str,
    operation: str,
    provider: str,
    model: str,
    units: dict[str, float],
    unit_prices: dict[str, float],
    cost_usd: float,
    scene_index: int | None = None,
    line_index: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> CostRecord:
    """``CostRecord`` を構築する (永続化はしない)。"""
    if stage not in VALID_STAGES:
        raise ValueError(f"invalid stage: {stage} (allowed: {sorted(VALID_STAGES)})")
    return CostRecord(
        record_id=str(uuid.uuid4()),
        timestamp=_now_iso(),
        project_ts=project_ts,
        stage=stage,
        operation=operation,
        scene_index=scene_index,
        line_index=line_index,
        provider=provider,
        model=model,
        units=dict(units),
        unit_prices=dict(unit_prices),
        cost_usd=float(cost_usd),
        metadata=dict(metadata or {}),
    )


def append(record: CostRecord) -> None:
    """JSONL ファイルに 1 行追記する (スレッドセーフ)。"""
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(asdict(record), ensure_ascii=False)
    with _WRITE_LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def iter_all() -> Iterator[CostRecord]:
    """すべてのレコードを yield。ファイルが無ければ空 iterator。"""
    path = _path()
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            yield CostRecord(**obj)


def iter_filtered(
    *,
    project_ts: str | None = None,
    stage: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> Iterator[CostRecord]:
    """フィールドの一致でフィルタした iterator。``None`` は無視 (= 全許容)。"""
    for rec in iter_all():
        if project_ts is not None and rec.project_ts != project_ts:
            continue
        if stage is not None and rec.stage != stage:
            continue
        if provider is not None and rec.provider != provider:
            continue
        if model is not None and rec.model != model:
            continue
        yield rec
