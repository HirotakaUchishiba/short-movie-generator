"""Stage 4 (Kling V3 動画) のグローバルキャッシュ。

入力 (= augmented animation_prompt + kling_duration + bg_image_sha +
model_id + aspect_ratio + cache_version) が同一の組み合わせで生成された
raw mp4 を ``cache/kling_videos/`` に保存し、別動画でも使い回せるようにする
(= FAL Kling API 呼び出しスキップ → コスト節約 + 速度向上)。

snapshot は live derivation で abstract のまま。cache は派生キャッシュ
(= 削除しても再生成で復元可能、SSOT は ``screenplays/`` + ``locations/`` +
``characters/`` のまま)。

ストレージ (= bg_cache.py と完全対称、flat 構造):
    cache/kling_videos/<hash16>.mp4         raw 動画 (5s or 10s)
    cache/kling_videos/<hash16>.json        メタ (prompt / model / hit_count /
                                                 created_at / last_used_at /
                                                 original_audio_duration /
                                                 frontload_ratio /
                                                 quality 状態 等)

判定階層 (詳細は kling cache 設計ドキュメント):
    L1: cache key の完全一致 (= build_cache_key の hash)
    L2: 適合度判定 (動作完了点 / 乖離率 / camera_distance)
    L3: 品質ガード (blacklist / TTL / approval / ffprobe ok)
    L4: ユーザ override (force_fresh / project disable)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)

_CACHE_LOCK = threading.RLock()


# ───────────── ストレージ root ─────────────

def _cache_root() -> Path:
    """cache 格納ルート。`config.KLING_CACHE_DIR` から取得し、無ければ既定パス。"""
    root = getattr(config, "KLING_CACHE_DIR", None)
    if not root:
        root = os.path.join(config.BASE_DIR, "cache", "kling_videos")
    p = Path(root)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _entry_paths(key: str) -> tuple[Path, Path]:
    root = _cache_root()
    return root / f"{key}.mp4", root / f"{key}.json"


def _now() -> str:
    # ms 精度: 連続生成時に last_used_at がぶつかって LRU 順が崩れるのを防ぐ
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ───────────── cache key ─────────────


def _file_sha256(path: str | Path) -> str:
    """ファイル content の sha256 (16 文字 prefix)。
    bg_cache._file_sha256 と同じアルゴリズム (= 互換性)。"""
    h = hashlib.sha256()
    with open(str(path), "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def build_cache_key(
    augmented_animation_prompt: str,
    kling_duration: int,
    bg_image_sha: str,
    model_id: str,
    aspect_ratio: str = "9:16",
    cache_version: str | None = None,
) -> str:
    """augmented prompt + duration + bg sha + model + aspect + version
    から決定論的に hash を派生する。

    augmented_animation_prompt は scene_gen._augment_animation_prompt の戻り値
    (= base prompt + emotion arc + visual cues + audio_dynamics + frontload
    指示 + KLING_NEGATIVE_CONSTRAINT が baked in されたもの)。
    """
    if cache_version is None:
        cache_version = getattr(config, "KLING_CACHE_VERSION", "v1")
    payload = {
        "augmented_animation_prompt": augmented_animation_prompt,
        "kling_duration": int(kling_duration),
        "bg_image_sha": bg_image_sha,
        "model_id": model_id,
        "aspect_ratio": aspect_ratio,
        "cache_version": cache_version,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ───────────── lookup / candidates ─────────────


def lookup(key: str) -> Path | None:
    """key 完全一致の mp4 が存在すればパスを返す。L2/L3 判定は行わない。"""
    if not key:
        return None
    mp4, _ = _entry_paths(key)
    return mp4 if mp4.exists() else None


def load_meta(key: str) -> dict | None:
    """metadata sidecar を読み込む。無ければ None。"""
    if not key:
        return None
    _, meta_path = _entry_paths(key)
    if not meta_path.exists():
        return None
    try:
        with open(meta_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.debug("kling_cache load_meta failed (%s): %s", meta_path, e)
        return None


def lookup_all_candidates(
    key: str,
    new_audio_duration: float,
    scene_camera_distance: str | None,
) -> list[dict]:
    """L1 一致 + L2 適合度 + L3 品質 を pass した候補のみを fitness 降順で返す。

    現状は L1 hash 完全一致 = entry 1 件 (variant 蓄積は P4 で導入)。
    将来 variant 蓄積した場合は同 key 配下の複数 entry を返す。

    Returns:
        [{"key": ..., "mp4_path": str, "meta": {...}, "fitness": float,
          "warnings": [...], "ok": True}, ...]
    """
    if not getattr(config, "KLING_CACHE_ENABLED", True):
        return []
    mp4 = lookup(key)
    if mp4 is None:
        return []
    meta = load_meta(key) or {}
    fit = _evaluate_fitness(meta, new_audio_duration, scene_camera_distance)
    if not fit["ok"]:
        return []
    qual = _evaluate_quality(meta)
    if not qual["ok"]:
        return []
    return [{
        "key": key,
        "mp4_path": str(mp4),
        "meta": meta,
        "fitness": fit["fitness"],
        "warnings": fit["warnings"] + qual["warnings"],
        "ok": True,
    }]


def diagnose_candidate(
    key: str,
    new_audio_duration: float,
    scene_camera_distance: str | None,
) -> dict:
    """key の cache entry が L2/L3 を満たすか診断する (= UI で reject 理由
    表示するためのヘルパ)。

    Returns:
        {
          "exists": bool,
          "ok": bool,
          "fitness": float,
          "warnings": list[str],
          "rejected_reasons": list[str],
        }
    """
    out: dict[str, Any] = {
        "exists": False, "ok": False, "fitness": 0.0,
        "warnings": [], "rejected_reasons": [],
    }
    if not getattr(config, "KLING_CACHE_ENABLED", True):
        out["rejected_reasons"].append("kling cache disabled")
        return out
    mp4 = lookup(key)
    if mp4 is None:
        return out
    out["exists"] = True
    meta = load_meta(key) or {}
    fit = _evaluate_fitness(meta, new_audio_duration, scene_camera_distance)
    qual = _evaluate_quality(meta)
    out["fitness"] = fit["fitness"]
    out["warnings"] = fit["warnings"] + qual["warnings"]
    out["rejected_reasons"] = (
        [r for r in fit["rejected_reasons"]] + [r for r in qual["rejected_reasons"]]
    )
    out["ok"] = fit["ok"] and qual["ok"]
    return out


# ───────────── L2: 適合度判定 ─────────────


def _evaluate_fitness(
    meta: dict,
    new_audio_duration: float,
    scene_camera_distance: str | None,
) -> dict:
    """L2 全 4 項目を判定。fitness は 0.0〜1.0 (= 1.0 が完全一致)。

    判定:
      1. 動作完了点が trim 後に生き残るか
      2. slow_mo 許容範囲 (`_pick_duration` の保険)
      3. 元 audio との乖離率 (`KLING_CACHE_MISMATCH_THRESHOLD`)
      4. camera_distance 互換性
    """
    warnings: list[str] = []
    rejected: list[str] = []
    kling_duration = float(meta.get("kling_duration", 0) or 0)
    frontload = float(meta.get("frontload_ratio") or config.ACTION_FRONTLOAD_RATIO)
    orig = float(meta.get("original_audio_duration") or 0)

    # 1. 動作完了点
    action_end = kling_duration * frontload
    if new_audio_duration < action_end - 0.05:
        rejected.append(
            f"動作完了点 {action_end:.1f}s より新 audio {new_audio_duration:.1f}s が短い"
        )

    # 2. slow_mo 許容範囲
    tol = float(getattr(config, "KLING_DURATION_TOLERANCE_RATIO", 1.2))
    if kling_duration > 0 and new_audio_duration > kling_duration * tol + 0.05:
        rejected.append(
            f"slow_mo 上限超過: 新 audio {new_audio_duration:.1f}s > "
            f"{kling_duration:.0f}s × {tol:.1f}"
        )

    # 3. 乖離率
    threshold = float(getattr(config, "KLING_CACHE_MISMATCH_THRESHOLD", 0.30))
    diff_ratio = 0.0
    if orig > 0:
        diff_ratio = abs(new_audio_duration - orig) / orig
        if diff_ratio > threshold:
            rejected.append(
                f"audio 乖離率 {diff_ratio*100:.0f}% > {threshold*100:.0f}%"
            )
        elif diff_ratio > threshold * 0.5:
            warnings.append(
                f"audio 乖離率 {diff_ratio*100:.0f}% (元 {orig:.1f}s / 新 {new_audio_duration:.1f}s)"
            )

    # 4. camera_distance
    cached_cam = meta.get("camera_distance")
    if (cached_cam and scene_camera_distance
            and cached_cam != scene_camera_distance):
        rejected.append(
            f"camera_distance 不一致: cached={cached_cam} / scene={scene_camera_distance}"
        )

    fitness = max(0.0, 1.0 - diff_ratio)
    if rejected:
        fitness = 0.0
    return {
        "ok": not rejected,
        "fitness": round(fitness, 3),
        "warnings": warnings,
        "rejected_reasons": rejected,
    }


# ───────────── L3: 品質ガード ─────────────


def _evaluate_quality(meta: dict) -> dict:
    warnings: list[str] = []
    rejected: list[str] = []
    quality = meta.get("quality") or {}
    if quality.get("blacklisted"):
        reason = quality.get("blacklist_reason") or "blacklisted"
        rejected.append(f"blacklist: {reason}")
    if quality.get("ffprobe_ok") is False:
        rejected.append("ffprobe NG")
    if getattr(config, "KLING_CACHE_REQUIRE_APPROVAL", False):
        if not quality.get("approved_at_origin"):
            rejected.append("元プロジェクト未承認")
    ttl_days = int(getattr(config, "KLING_CACHE_TTL_DAYS", 365))
    created_at = meta.get("created_at")
    if created_at and ttl_days > 0:
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - created > timedelta(days=ttl_days):
                rejected.append(f"TTL 超過 ({ttl_days}日)")
        except Exception as e:
            logger.debug("kling_cache TTL parse failed: %s (%s)", created_at, e)
    if not quality.get("final_render_completed"):
        warnings.append("元プロジェクトで最終納品未到達")
    return {
        "ok": not rejected,
        "warnings": warnings,
        "rejected_reasons": rejected,
    }


# ───────────── store / commit / touch ─────────────


def store(key: str, mp4_path: str | Path, meta: dict[str, Any]) -> None:
    """生成済み raw mp4 をキャッシュに登録する。既存なら no-op (= idempotent)。

    auto prune (= ``KLING_CACHE_AUTO_PRUNE``) が True なら store 後に
    LRU prune を実行して上限内に収める。
    """
    if not key:
        return
    mp4_dst, meta_dst = _entry_paths(key)
    with _CACHE_LOCK:
        if mp4_dst.exists():
            touch(key)
            return
        # atomic write: tmp ファイル → rename
        tmp_dst = mp4_dst.with_suffix(".mp4.tmp")
        try:
            shutil.copyfile(str(mp4_path), tmp_dst)
            os.replace(tmp_dst, mp4_dst)
        except Exception as e:
            logger.warning("kling_cache store copy failed: %s", e)
            try:
                if tmp_dst.exists():
                    os.remove(tmp_dst)
            except Exception:
                pass
            return
        full_meta = {
            **meta,
            "key": key,
            "schema_version": 1,
            "created_at": _now(),
            "last_used_at": _now(),
            "hit_count": 0,
        }
        # quality ブロックの初期化
        quality = dict(full_meta.get("quality") or {})
        quality.setdefault("blacklisted", False)
        quality.setdefault("blacklist_reason", None)
        quality.setdefault("ffprobe_ok", True)
        quality.setdefault("approved_at_origin", None)
        quality.setdefault("final_render_completed", False)
        full_meta["quality"] = quality
        try:
            with open(meta_dst, "w", encoding="utf-8") as f:
                json.dump(full_meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("kling_cache store meta write failed: %s", e)
        logger.info("[kling cache STORE] key=%s", key)
    if getattr(config, "KLING_CACHE_AUTO_PRUNE", True):
        try:
            prune(int(getattr(config, "KLING_CACHE_MAX_BYTES", 2_000 * 1024 ** 3)))
        except Exception as e:
            logger.warning("kling_cache auto prune failed: %s", e)


def commit_to_project(key: str, dest_mp4_path: str | Path) -> Path:
    """cache の raw mp4 を project の kling_<S>.mp4 に atomic copy + touch する。

    Returns:
        コピー先パス (= dest_mp4_path)
    """
    src = lookup(key)
    if src is None:
        raise FileNotFoundError(f"kling cache miss: {key}")
    dest = Path(dest_mp4_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = dest.with_suffix(dest.suffix + ".tmp")
    shutil.copyfile(str(src), tmp_dest)
    os.replace(tmp_dest, dest)
    touch(key)
    logger.info("[kling cache HIT] key=%s -> %s", key, dest.name)
    return dest


def touch(key: str) -> None:
    """hit_count を +1 し last_used_at を更新する。"""
    if not key:
        return
    _, meta_path = _entry_paths(key)
    if not meta_path.exists():
        return
    with _CACHE_LOCK:
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as e:
            logger.debug("kling_cache touch meta load failed (%s): %s",
                         meta_path, e)
            return
        meta["hit_count"] = int(meta.get("hit_count", 0)) + 1
        meta["last_used_at"] = _now()
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("kling_cache touch failed: %s", e)


# ───────────── L3 操作: blacklist / promote / verify ─────────────


def _update_quality(key: str, **fields: Any) -> bool:
    if not key:
        return False
    _, meta_path = _entry_paths(key)
    if not meta_path.exists():
        return False
    with _CACHE_LOCK:
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as e:
            logger.debug("kling_cache _update_quality meta load failed "
                         "(%s): %s", meta_path, e)
            return False
        quality = dict(meta.get("quality") or {})
        quality.update(fields)
        meta["quality"] = quality
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.warning("kling_cache update quality failed: %s", e)
            return False


def blacklist(key: str, reason: str) -> bool:
    """key を blacklist する (= 以後 hit しない)。"""
    return _update_quality(key, blacklisted=True, blacklist_reason=str(reason or ""))


def unblacklist(key: str) -> bool:
    return _update_quality(key, blacklisted=False, blacklist_reason=None)


def promote(key: str) -> bool:
    """元プロジェクトが最終納品 (= reels_<TS>.mp4 書き出し) に到達したことを
    記録する。L3 の信頼度を上げる。"""
    return _update_quality(key, final_render_completed=True)


def mark_origin_approved(key: str) -> bool:
    """元プロジェクトで Stage 4 が承認されたことを記録する。"""
    return _update_quality(key, approved_at_origin=_now())


def verify(key: str) -> bool:
    """ffprobe で mp4 の整合性を検証。NG なら quality.ffprobe_ok=False。"""
    mp4, _ = _entry_paths(key)
    if not mp4.exists():
        return False
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-print_format", "json", str(mp4)],
            capture_output=True, text=True, timeout=30,
        )
        ok = r.returncode == 0
    except Exception as e:
        logger.debug("kling_cache verify ffprobe failed (%s): %s", mp4, e)
        ok = False
    _update_quality(key, ffprobe_ok=ok)
    return ok


# ───────────── 一覧 / prune ─────────────


def list_entries() -> list[dict[str, Any]]:
    """全エントリの (key, size_bytes, hit_count, last_used_at, meta) をリストする。"""
    root = _cache_root()
    out: list[dict[str, Any]] = []
    for mp4 in root.glob("*.mp4"):
        # tmp ファイルを除外
        if mp4.name.endswith(".tmp.mp4") or mp4.name.endswith(".mp4.tmp"):
            continue
        meta_path = mp4.with_suffix(".json")
        meta: dict = {}
        if meta_path.exists():
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception as e:
                logger.debug("kling_cache list_entries meta load failed "
                             "(%s): %s", meta_path, e)
                meta = {}
        out.append({
            "key": mp4.stem,
            "mp4_path": str(mp4),
            "meta_path": str(meta_path) if meta_path.exists() else None,
            "size_bytes": mp4.stat().st_size,
            "hit_count": int(meta.get("hit_count", 0)),
            "last_used_at": meta.get("last_used_at", meta.get("created_at", "")),
            "created_at": meta.get("created_at", ""),
            "kling_duration": meta.get("kling_duration"),
            "original_audio_duration": meta.get("original_audio_duration"),
            "location_ref": meta.get("location_ref"),
            "quality": meta.get("quality") or {},
        })
    return out


def prune(max_total_bytes: int, dry_run: bool = False) -> dict[str, Any]:
    """LRU で max_total_bytes を超えないように古いエントリを削除する。

    優先度: last_used_at が古いもの (last_used_at が空なら created_at)。
    Returns: {"deleted": [{key, size_bytes}, ...], "total_bytes_after": int}
    """
    entries = list_entries()
    total = sum(e["size_bytes"] for e in entries)
    if total <= max_total_bytes:
        return {"deleted": [], "total_bytes_after": total}

    entries.sort(key=lambda e: e["last_used_at"] or e["created_at"] or "")
    deleted: list[dict[str, Any]] = []
    for e in entries:
        if total <= max_total_bytes:
            break
        deleted.append({"key": e["key"], "size_bytes": e["size_bytes"]})
        total -= e["size_bytes"]
        if dry_run:
            continue
        try:
            os.remove(e["mp4_path"])
            if e["meta_path"]:
                os.remove(e["meta_path"])
        except Exception as ex:
            logger.warning("kling_cache prune remove failed: %s", ex)
    return {"deleted": deleted, "total_bytes_after": total}
