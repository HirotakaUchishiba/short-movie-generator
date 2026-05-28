import os
from datetime import datetime

import io_utils

STAGES = [
    "analyze",  # Stage 0: 参考動画 → 台本 (= analyze pipeline、from-reference-video 経由でのみ立つ)
    "script", "tts", "bg", "kling", "scene", "overlay", "download",
]
# CLI / UI から自動 run_next で起動できないステージ。ユーザの外部アクション
# (CapCut 取り込み / プラットフォームへの投稿) によって generated_at が立つ。
EXTERNAL_ACTION_STAGES = frozenset()
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
    block = progress["stages"][stage]
    block["generated_at"] = _now()
    block["approved_at"] = None
    # 生成成功は直前の failed 状態を解除する。これをしないと、一度失敗した stage を
    # 再生成して成功しても status="failed" / error_detail が残り、UI のエラー
    # バナーが消えない (= mark_stage_failed の逆操作)。
    block["status"] = None
    block.pop("error_detail", None)
    block.pop("error", None)
    save(ts_path, progress)


def mark_approved(ts_path: str, stage: str) -> None:
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    progress = load(ts_path)
    if not progress["stages"][stage]["generated_at"]:
        raise ValueError(f"stage not generated yet: {stage}")
    progress["stages"][stage]["approved_at"] = _now()
    save(ts_path, progress)


# ─── Stage 0 (analyze) 専用 helpers ─────────────────────
# 通常の mark_generated/mark_approved は人間 confirm を介する 2 段ゲート用。
# analyze は SSE event で完了が確定するため、save phase 完了 hook で
# mark_analyze_completed を一発呼ぶだけで Stage 1 を unlock する。

def mark_analyze_started(ts_path: str) -> None:
    """Stage 0 (analyze) を running 状態にする。
    POST /api/projects/from-reference-video から呼ばれる初期化。"""
    progress = load(ts_path)
    progress["stages"]["analyze"] = {
        "generated_at": _now(),
        "approved_at": None,
        "regen_count": 0,
        "status": "running",
    }
    save(ts_path, progress)


def mark_analyze_completed(ts_path: str) -> None:
    """Stage 0 (analyze) save phase 完了 → Stage 1 unlock。
    人間 confirm を介さない (= save 完了 = 自動承認) ので generated と
    approved を同時に立てる。analyze.runner._on_save_complete から呼ぶ。
    """
    progress = load(ts_path)
    now = _now()
    progress["stages"]["analyze"] = {
        "generated_at": now,
        "approved_at": now,
        "regen_count": 0,
        "status": "completed",
    }
    save(ts_path, progress)


def mark_analyze_failed(ts_path: str, error: str) -> None:
    """Stage 0 (analyze) を failed 状態にする。UI 側で retry / 削除を
    選択させるため approved_at は None のまま。runner の except 経路から呼ぶ。

    内部的には :func:`mark_stage_failed` の analyze 専用ラッパー。
    raw error 文字列を受け、構造化 ``error_detail`` envelope に変換して保存する。
    legacy ``error`` field (= :500 截断) も後方互換のため残す。
    """
    from errors import build_error_detail

    mark_stage_failed(
        ts_path,
        "analyze",
        build_error_detail(error),
        set_generated_at=True,
    )


def mark_stage_failed(
    ts_path: str,
    stage: str,
    error_detail: dict,
    *,
    set_generated_at: bool = False,
) -> None:
    """任意 stage を failed 状態にする (= UI が原因を表示するための SSOT)。

    ``tmp-progress.json`` の ``stages.<stage>`` block に以下を書く:

    - ``status = "failed"``
    - ``error_detail`` (= 構造化 envelope。:func:`errors.build_error_detail` で生成)
    - ``error`` (= 後方互換のため raw message を :500 截断したもの)

    Args:
        ts_path: project の temp ディレクトリ絶対パス
        stage: STAGES のいずれか
        error_detail: ``errors.build_error_detail()`` で生成した dict
        set_generated_at: True なら ``generated_at`` を現在時刻にセット
            (= analyze の既存挙動。Stage 1-6 では既定 False)

    Note:
        本関数は **best-effort**。書き込みに失敗しても caller の例外伝播は
        妨げない (= staged_pipeline の except 経路は raise を維持する)。
    """
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    progress = load(ts_path)
    block = progress["stages"].get(stage) or {}
    block["status"] = "failed"
    block["error_detail"] = error_detail
    block["error"] = (error_detail.get("message") or "")[:500]
    if set_generated_at:
        block["generated_at"] = _now()
    block.setdefault("generated_at", None)
    block.setdefault("approved_at", None)
    block.setdefault("regen_count", 0)
    progress["stages"][stage] = block
    save(ts_path, progress)


def analyze_status(ts_path: str) -> str | None:
    """Stage 0 (analyze) の現在状態を返す。
    "running" / "completed" / "failed" / None。None は legacy template 経由
    project (= Stage 0 を経由しない) を意味する。
    """
    progress = load(ts_path)
    block = progress["stages"].get("analyze") or {}
    return block.get("status")


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
    """Stage 1+ の承認だけを解除する。生成物 (assets) は保持したまま、
    再承認/再生成を促す。Stage 1「素材編集」セクションで抽象台本を
    差し替えたとき、後続 Stage が古い素材で承認済みのままにならないように
    するため。

    Stage 0 (analyze) は対象外: 参考動画分析は素材編集の範囲ではなく、
    再走は POST /api/projects/<ts>/retry-analyze で別 endpoint として扱う。
    """
    progress = load(ts_path)
    for s in STAGES:
        if s == "analyze":
            continue
        progress["stages"][s]["approved_at"] = None
    save(ts_path, progress)


def revoke_overlay_only(ts_path: str) -> None:
    """Stage 6 (overlay) の承認だけを解除する。Stage 2-5 (= TTS / 音声合成 /
    動画生成) は承認状態を維持する。

    `revoke_all_approvals` の overlay 限定版。abstract 保存時に Stage 6 にしか
    影響しない field (= subtitle_y_from_bottom 等) だけが変わったケースで使う。
    CLAUDE.md「コストのかかる操作を安易に実行しない」原則に従い、再 TTS /
    再動画生成を促す承認解除を抑止する。
    """
    progress = load(ts_path)
    if "overlay" in progress["stages"]:
        progress["stages"]["overlay"]["approved_at"] = None
    save(ts_path, progress)


# cascade reset 対象は内部 stage のみ (script〜overlay)。
# download は最終 stage で artifact を持たないのでチェーンに含めない。
_CASCADE_STAGES = ["script", "tts", "bg", "kling", "scene", "overlay"]


def cascade_reset_after(ts_path: str, stage: str) -> list[str]:
    """指定 stage の **後続** 内部 stage の approved_at だけを解除する。
    artifact (= generated_at) は保持。個別シーン再生成で BG だけ作り直した時に
    kling / scene / overlay が古い BG ベースのまま承認済みでスルーされるのを防ぐ。

    Returns: reset した stage 名のリスト (= ログ / UI 表示用)。
    """
    if stage not in _CASCADE_STAGES:
        raise ValueError(f"cascade 対象外の stage: {stage}")
    progress = load(ts_path)
    idx = _CASCADE_STAGES.index(stage)
    reset: list[str] = []
    for s in _CASCADE_STAGES[idx + 1:]:
        if progress["stages"][s].get("approved_at"):
            progress["stages"][s]["approved_at"] = None
            reset.append(s)
    if reset:
        save(ts_path, progress)
    return reset


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
