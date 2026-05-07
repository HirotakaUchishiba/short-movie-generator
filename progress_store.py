import os
from datetime import datetime

import io_utils

STAGES = [
    "script", "tts", "bg", "kling", "scene", "overlay",
    "final_import", "publish",
]
# CLI / UI から自動 run_next で起動できないステージ。ユーザの外部アクション
# (CapCut 取り込み / プラットフォームへの投稿) によって generated_at が立つ。
EXTERNAL_ACTION_STAGES = frozenset({"final_import", "publish"})
PROGRESS_FILENAME = "tmp-progress.json"


def _path(ts_path: str) -> str:
    return os.path.join(ts_path, PROGRESS_FILENAME)


def _empty() -> dict:
    return {"stages": {s: {"generated_at": None, "approved_at": None,
                            "regen_count": 0} for s in STAGES}}


def load(ts_path: str) -> dict:
    import json
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
    io_utils.atomic_write_json(_path(ts_path), progress)


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


def revoke_all_approvals(ts_path: str) -> None:
    """全 stage の承認だけを解除する。生成物 (assets) は保持したまま、
    再承認/再生成を促す。Stage 1「素材編集」セクションで抽象台本 / VideoStyle
    を差し替えたとき、後続 Stage が古い素材で承認済みのままにならないように
    するため。
    """
    progress = load(ts_path)
    for s in STAGES:
        progress["stages"][s]["approved_at"] = None
    save(ts_path, progress)


# ───────────── stage 共通: cache decisions ─────────────
#
# bg / kling は scan / commit / generate の 3 段階に分かれており、
# シーンごとに「キャッシュ採用 or 新規生成」をユーザが per-scene で判断する。
# 判断状態は ``progress["stages"][<stage>]["scene_decisions"]`` に保存する。
#
# scene_decisions の形式:
#   {
#     "<scene_idx>": {
#       "candidates": [{"key": ..., "fitness": ..., "warnings": [...], "meta": {...}}, ...],
#       "decision": "pending" | "cache" | "fresh",
#       "decided_key": <hash> | null,
#       "decided_at": <iso8601> | null,
#       "cache_key": <hash>,
#       "diagnostics": [...],
#     },
#     ...
#   }

_DECISION_STAGES = ("bg", "kling")


def _ensure_stage_block(progress: dict, stage: str) -> dict:
    if stage not in _DECISION_STAGES:
        raise ValueError(
            f"stage {stage!r} は scene_decisions をサポートしません "
            f"(対応: {_DECISION_STAGES})")
    block = progress["stages"].setdefault(
        stage, {"generated_at": None, "approved_at": None, "regen_count": 0})
    block.setdefault("scene_decisions", {})
    block.setdefault("cache_scanned_at", None)
    return block


def set_scan_result(ts_path: str, stage: str,
                    scene_decisions: dict) -> None:
    """scan の結果一式で scene_decisions を上書きする。"""
    progress = load(ts_path)
    block = _ensure_stage_block(progress, stage)
    block["scene_decisions"] = scene_decisions
    block["cache_scanned_at"] = _now()
    save(ts_path, progress)


def get_decisions(ts_path: str, stage: str) -> dict:
    """{"cache_scanned_at": ..., "scene_decisions": {...}} を返す。"""
    progress = load(ts_path)
    block = _ensure_stage_block(progress, stage)
    return {
        "cache_scanned_at": block.get("cache_scanned_at"),
        "scene_decisions": block.get("scene_decisions", {}),
    }


def set_scene_decision(ts_path: str, stage: str, scene_idx: int,
                       decision: str,
                       decided_key: str | None = None) -> None:
    """1 シーンの判断を更新する。decision は "cache"/"fresh"/"pending"。"""
    if decision not in ("cache", "fresh", "pending"):
        raise ValueError(f"invalid decision: {decision}")
    progress = load(ts_path)
    block = _ensure_stage_block(progress, stage)
    decisions = block["scene_decisions"]
    rec = dict(decisions.get(str(scene_idx)) or {})
    rec["decision"] = decision
    rec["decided_key"] = decided_key if decision == "cache" else None
    rec["decided_at"] = _now() if decision != "pending" else None
    decisions[str(scene_idx)] = rec
    save(ts_path, progress)


def reset_decisions(ts_path: str, stage: str) -> None:
    """scan 結果と判断状態をクリアする (= cache scan を再実行する前)。"""
    progress = load(ts_path)
    block = _ensure_stage_block(progress, stage)
    block["scene_decisions"] = {}
    block["cache_scanned_at"] = None
    save(ts_path, progress)


# ───────────── 旧名 (kling 専用) — 後方互換ラッパ ─────────────
# 既存呼び出し元を壊さないため残す。新規コードは新名 (set_scan_result 等) を使うこと。

def _ensure_kling_block(progress: dict) -> dict:
    return _ensure_stage_block(progress, "kling")


def set_kling_scan_result(ts_path: str, scene_decisions: dict) -> None:
    set_scan_result(ts_path, "kling", scene_decisions)


def get_kling_decisions(ts_path: str) -> dict:
    return get_decisions(ts_path, "kling")


def reset_kling_decisions(ts_path: str) -> None:
    reset_decisions(ts_path, "kling")
