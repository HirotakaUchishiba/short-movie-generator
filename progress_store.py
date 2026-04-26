import json
import os
from datetime import datetime

STAGES = ["script", "tts", "bg", "kling", "scene", "overlay", "final"]
PROGRESS_FILENAME = "tmp-progress.json"


def _path(ts_path: str) -> str:
    return os.path.join(ts_path, PROGRESS_FILENAME)


def _empty() -> dict:
    return {"stages": {s: {"generated_at": None, "approved_at": None,
                            "regen_count": 0} for s in STAGES}}


def load(ts_path: str) -> dict:
    p = _path(ts_path)
    if not os.path.exists(p):
        return _empty()
    try:
        with open(p) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty()
    base = _empty()
    base["stages"].update(data.get("stages") or {})
    return base


def save(ts_path: str, progress: dict) -> None:
    os.makedirs(ts_path, exist_ok=True)
    with open(_path(ts_path), "w") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def mark_generated(ts_path: str, stage: str) -> None:
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    progress = load(ts_path)
    progress["stages"][stage]["generated_at"] = _now()
    progress["stages"][stage]["approved_at"] = None
    save(ts_path, progress)


def mark_approved(ts_path: str, stage: str) -> None:
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    progress = load(ts_path)
    if not progress["stages"][stage]["generated_at"]:
        raise ValueError(f"stage not generated yet: {stage}")
    progress["stages"][stage]["approved_at"] = _now()
    save(ts_path, progress)


def increment_regen(ts_path: str, stage: str) -> None:
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    progress = load(ts_path)
    progress["stages"][stage]["regen_count"] = (
        progress["stages"][stage].get("regen_count", 0) + 1)
    progress["stages"][stage]["approved_at"] = None
    save(ts_path, progress)


def is_generated(ts_path: str, stage: str) -> bool:
    progress = load(ts_path)
    return bool(progress["stages"].get(stage, {}).get("generated_at"))


def is_approved(ts_path: str, stage: str) -> bool:
    progress = load(ts_path)
    return bool(progress["stages"].get(stage, {}).get("approved_at"))


def next_stage(ts_path: str) -> str | None:
    """次に実行すべきstage。全完了なら None。"""
    progress = load(ts_path)
    for stage in STAGES:
        s = progress["stages"][stage]
        if not s["generated_at"]:
            return stage
        if not s["approved_at"]:
            return None
    return None


def current_stage(ts_path: str) -> str | None:
    """現在ユーザーが確認すべきstage。生成済みで未承認のものを返す。"""
    progress = load(ts_path)
    for stage in STAGES:
        s = progress["stages"][stage]
        if s["generated_at"] and not s["approved_at"]:
            return stage
    for stage in STAGES:
        if not progress["stages"][stage]["generated_at"]:
            return stage
    return None


def reset_stage(ts_path: str, stage: str) -> None:
    """このstageと以降のstageをリセット（再生成扱い）。"""
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    progress = load(ts_path)
    idx = STAGES.index(stage)
    for s in STAGES[idx:]:
        progress["stages"][s]["generated_at"] = None
        progress["stages"][s]["approved_at"] = None
    save(ts_path, progress)
