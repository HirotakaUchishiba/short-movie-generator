"""Stage 3 (背景画像) のグローバルキャッシュ。

入力 (= background_prompt + character_refs の sha + location の sha + Imagen
モデル ID) が同一の組み合わせで生成された PNG を ``cache/bg_images/`` に
保存し、別動画でも使い回せるようにする (= Imagen 呼び出しスキップ → コスト
節約 + 速度向上)。

snapshot は live derivation で abstract のまま。cache は派生キャッシュ
(= 削除しても再生成で復元可能、SSOT は ``screenplays/`` + ``locations/`` +
``characters/`` のまま)。

ストレージ (= kling_cache.py と完全対称、flat 構造):
    cache/bg_images/<hash16>.png         画像本体
    cache/bg_images/<hash16>.json        メタ (prompt / model / hit_count /
                                              created_at / last_used_at /
                                              quality 状態 等)

判定階層 (kling_cache と同型):
    L1: cache key の完全一致 (= compute_bg_cache_key の hash)
    L2: 適合度判定 — BG は静止画なので時間軸関連の判定は不要、
        camera_distance も prompt 経由で key に内包されるため
        実質「常に ok」(L1 一致 ≒ 視覚一致)
    L3: 品質ガード (blacklist / TTL / approval / 整合性)
    L4: ユーザ override (force_fresh / project disable)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)

_CACHE_LOCK = threading.RLock()  # store 内で touch を呼ぶ再帰経路があるため
_FILE_SHA_CACHE: dict[str, str] = {}
_FILE_SHA_CACHE_LOCK = threading.Lock()


def _cache_root() -> Path:
    """cache 格納ルート。`config.BG_CACHE_DIR` から取得し、無ければ既定パス。"""
    root = getattr(config, "BG_CACHE_DIR", None)
    if not root:
        root = os.path.join(config.BASE_DIR, "cache", "bg_images")
    p = Path(root)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _file_sha256(path: str | Path) -> str:
    """ファイル content の sha256 (16 文字 prefix)。
    生成キャッシュキー用なので prefix で十分 (衝突確率は実質 0)。"""
    s = str(path)
    with _FILE_SHA_CACHE_LOCK:
        cached = _FILE_SHA_CACHE.get(s)
    if cached is not None:
        return cached
    h = hashlib.sha256()
    with open(s, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    digest = h.hexdigest()[:16]
    with _FILE_SHA_CACHE_LOCK:
        _FILE_SHA_CACHE[s] = digest
    return digest


def _ref_image_shas(refs: list[str]) -> list[dict[str, str]]:
    """character_refs の参照画像 sha を計算 (= 画像差し替えで cache 無効化)。

    Returns:
        [{"ref": "f1__office", "sha": "<16hex>"}, ...] (ref 昇順)。
    """
    from analyze import character_meta as cmeta_mod
    out: list[dict[str, str]] = []
    for ref in sorted(refs):
        if not ref:
            continue
        path = cmeta_mod.image_path(ref)
        if path is None or not path.exists():
            out.append({"ref": ref, "sha": "_missing_"})
            continue
        out.append({"ref": ref, "sha": _file_sha256(path)})
    return out


def _location_sha(loc_ref: str | None) -> str | None:
    """`locations/<id>.json` の sha (= ロケ編集で cache 無効化)。"""
    if not loc_ref:
        return None
    from analyze import location as loc_mod
    p = loc_mod.LOCATIONS_DIR / f"{loc_ref}.json"
    if not p.exists():
        return None
    return _file_sha256(p)


def _imagen_model_id() -> str:
    """Imagen モデル識別子 (= モデル変更で cache 無効化)。"""
    try:
        import imagen_client
        return getattr(imagen_client, "MODEL", "unknown")
    except Exception as e:
        logger.debug("bg_cache imagen_model_id resolution failed: %s", e)
        return "unknown"


def compute_bg_cache_key(scene: dict, screenplay: dict | None = None) -> str:
    """シーンの背景画像生成入力からキャッシュキーを派生する (決定論的)。

    入力要素:
      - background_prompt (compose 出力 = SSOT 派生)
      - character_refs の参照画像 sha
      - location_ref に紐づく locations/<id>.json の sha
      - Imagen モデル ID

    storyboard retry の `_storyboard_retry_neg` は意図的に除外
    (retry 通過後の最終画像のみ store するため)。
    """
    from scene_gen import _build_background_prompt
    identity = scene.get("identity") or {}
    parts = {
        "prompt": _build_background_prompt(scene, screenplay),
        "ref_shas": _ref_image_shas(list(identity.get("character_refs") or [])),
        "loc_sha": _location_sha(identity.get("location_ref")),
        "model": _imagen_model_id(),
    }
    payload = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _entry_paths(key: str) -> tuple[Path, Path]:
    root = _cache_root()
    return root / f"{key}.png", root / f"{key}.json"


def lookup(key: str) -> Path | None:
    """key に対応する PNG が存在すればパスを返す。無ければ None。"""
    if not key:
        return None
    img, _ = _entry_paths(key)
    return img if img.exists() else None


def _now() -> str:
    # ms 精度: 連続生成時に last_used_at がぶつかって LRU 順が崩れるのを防ぐ
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def store(key: str, image_path: str | Path, meta: dict[str, Any]) -> None:
    """生成済み画像をキャッシュに登録する。既存なら no-op (= idempotent)。

    quality ブロックを欠いた meta が渡された場合は既定値で初期化する
    (= kling_cache.store と対称)。
    """
    if not key:
        return
    img_dst, meta_dst = _entry_paths(key)
    with _CACHE_LOCK:
        if img_dst.exists():
            # 並行 miss で先勝ちが既に store 済 → 後続は touch のみ
            touch(key)
            return
        # atomic write: tmp ファイル → rename
        tmp_dst = img_dst.with_suffix(".png.tmp")
        try:
            shutil.copyfile(str(image_path), tmp_dst)
            os.replace(tmp_dst, img_dst)
        except Exception as e:
            logger.warning("bg_cache store copy failed: %s", e)
            try:
                if tmp_dst.exists():
                    os.remove(tmp_dst)
            except Exception as cleanup_err:
                logger.debug(
                    "bg_cache store cleanup failed (%s): %s",
                    tmp_dst, cleanup_err,
                )
            return
        full_meta = {
            **meta,
            "key": key,
            "schema_version": meta.get("schema_version", 1),
            "cache_version": meta.get(
                "cache_version", getattr(config, "BG_CACHE_VERSION", "v1")),
            "created_at": _now(),
            "last_used_at": _now(),
            "hit_count": 0,
        }
        quality = dict(full_meta.get("quality") or {})
        quality.setdefault("blacklisted", False)
        quality.setdefault("blacklist_reason", None)
        quality.setdefault("integrity_ok", True)
        quality.setdefault("approved_at_origin", None)
        quality.setdefault("final_render_completed", False)
        full_meta["quality"] = quality
        try:
            with open(meta_dst, "w", encoding="utf-8") as f:
                json.dump(full_meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("bg_cache store meta write failed: %s", e)
        logger.info("[bg cache STORE] key=%s", key)


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
            logger.debug("bg_cache touch meta load failed (%s): %s",
                         meta_path, e)
            return
        meta["hit_count"] = int(meta.get("hit_count", 0)) + 1
        meta["last_used_at"] = _now()
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("bg_cache touch failed: %s", e)


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
        logger.debug("bg_cache load_meta failed (%s): %s", meta_path, e)
        return None


def list_entries() -> list[dict[str, Any]]:
    """全エントリの (key, size_bytes, hit_count, last_used_at) をリストする。
    LRU prune 用。"""
    root = _cache_root()
    out: list[dict[str, Any]] = []
    for img in root.glob("*.png"):
        # tmp ファイルを除外
        if img.name.endswith(".png.tmp") or img.name.endswith(".tmp.png"):
            continue
        meta_path = img.with_suffix(".json")
        meta = {}
        if meta_path.exists():
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception as e:
                logger.debug(
                    "bg_cache list_entries meta load failed (%s): %s",
                    meta_path, e,
                )
                meta = {}
        out.append({
            "key": img.stem,
            "image_path": str(img),
            "meta_path": str(meta_path) if meta_path.exists() else None,
            "size_bytes": img.stat().st_size,
            "hit_count": int(meta.get("hit_count", 0)),
            "last_used_at": meta.get("last_used_at", meta.get("created_at", "")),
            "created_at": meta.get("created_at", ""),
            "location_ref": meta.get("location_ref"),
            "camera_distance": meta.get("camera_distance"),
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

    # last_used_at 昇順 (= 古いものから削除)
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
            os.remove(e["image_path"])
            if e["meta_path"]:
                os.remove(e["meta_path"])
        except Exception as ex:
            logger.warning("bg_cache prune remove failed: %s", ex)
    return {"deleted": deleted, "total_bytes_after": total}


# ───────────── 適合度判定 (L2) / 品質ガード (L3) ─────────────


def _evaluate_fitness(meta: dict, scene: dict | None) -> dict:
    """L2 適合度判定。BG では key 一致 ≒ 視覚一致のため常に ok。

    camera_distance も background_prompt 経由で key に内包されているので
    別途判定不要。kling_cache._evaluate_fitness と signature を揃える。
    """
    return {
        "ok": True,
        "fitness": 1.0,
        "warnings": [],
        "rejected_reasons": [],
    }


def _evaluate_quality(meta: dict) -> dict:
    """L3 品質ガード (= kling_cache._evaluate_quality と対称)。"""
    warnings: list[str] = []
    rejected: list[str] = []
    quality = meta.get("quality") or {}
    if quality.get("blacklisted"):
        reason = quality.get("blacklist_reason") or "blacklisted"
        rejected.append(f"blacklist: {reason}")
    if quality.get("integrity_ok") is False:
        rejected.append("PNG 整合性 NG")
    if getattr(config, "BG_CACHE_REQUIRE_APPROVAL", False):
        if not quality.get("approved_at_origin"):
            rejected.append("元プロジェクト未承認")
    ttl_days = int(getattr(config, "BG_CACHE_TTL_DAYS", 365))
    created_at = meta.get("created_at")
    if created_at and ttl_days > 0:
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - created > timedelta(days=ttl_days):
                rejected.append(f"TTL 超過 ({ttl_days}日)")
        except Exception as e:
            logger.debug("bg_cache TTL parse failed: %s (%s)", created_at, e)
    if not quality.get("final_render_completed"):
        warnings.append("元プロジェクトで最終納品未到達")
    return {
        "ok": not rejected,
        "warnings": warnings,
        "rejected_reasons": rejected,
    }


def lookup_all_candidates(key: str, scene: dict | None = None) -> list[dict]:
    """L1 一致 + L2 + L3 を pass した候補のみを fitness 降順で返す。

    現状は L1 hash 完全一致 = entry 1 件 (variant 蓄積は将来拡張)。
    kling_cache.lookup_all_candidates と signature を揃える。
    """
    if not getattr(config, "BG_CACHE_ENABLED", True):
        return []
    img = lookup(key)
    if img is None:
        return []
    meta = load_meta(key) or {}
    fit = _evaluate_fitness(meta, scene)
    if not fit["ok"]:
        return []
    qual = _evaluate_quality(meta)
    if not qual["ok"]:
        return []
    return [{
        "key": key,
        "image_path": str(img),
        "meta": meta,
        "fitness": fit["fitness"],
        "warnings": fit["warnings"] + qual["warnings"],
        "ok": True,
    }]


def diagnose_candidate(key: str, scene: dict | None = None) -> dict:
    """key の cache entry の状態を診断する (= UI で reject 理由表示用)。"""
    out: dict[str, Any] = {
        "exists": False, "ok": False, "fitness": 0.0,
        "warnings": [], "rejected_reasons": [],
    }
    if not getattr(config, "BG_CACHE_ENABLED", True):
        out["rejected_reasons"].append("bg cache disabled")
        return out
    img = lookup(key)
    if img is None:
        return out
    out["exists"] = True
    meta = load_meta(key) or {}
    fit = _evaluate_fitness(meta, scene)
    qual = _evaluate_quality(meta)
    out["fitness"] = fit["fitness"]
    out["warnings"] = fit["warnings"] + qual["warnings"]
    out["rejected_reasons"] = (
        list(fit["rejected_reasons"]) + list(qual["rejected_reasons"]))
    out["ok"] = fit["ok"] and qual["ok"]
    return out


# ───────────── commit_to_project ─────────────


def commit_to_project(key: str, dest_image_path: str | Path) -> Path:
    """cache の PNG を project の bg_<S>.png に atomic copy + touch する。

    Returns:
        コピー先パス (= dest_image_path)
    """
    src = lookup(key)
    if src is None:
        raise FileNotFoundError(f"bg cache miss: {key}")
    dest = Path(dest_image_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = dest.with_suffix(dest.suffix + ".tmp")
    shutil.copyfile(str(src), tmp_dest)
    os.replace(tmp_dest, dest)
    touch(key)
    logger.info("[bg cache HIT] key=%s -> %s", key, dest.name)
    return dest


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
            logger.debug("bg_cache _update_quality meta load failed "
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
            logger.warning("bg_cache update quality failed: %s", e)
            return False


def blacklist(key: str, reason: str) -> bool:
    """key を blacklist する (= 以後 hit しない)。"""
    return _update_quality(key, blacklisted=True, blacklist_reason=str(reason or ""))


def unblacklist(key: str) -> bool:
    return _update_quality(key, blacklisted=False, blacklist_reason=None)


def promote(key: str) -> bool:
    """元プロジェクトが最終納品 (= reels_<TS>.mp4 書き出し) に到達したことを記録。"""
    return _update_quality(key, final_render_completed=True)


def mark_origin_approved(key: str) -> bool:
    """元プロジェクトで Stage 3 が承認されたことを記録する。"""
    return _update_quality(key, approved_at_origin=_now())


def verify(key: str) -> bool:
    """PIL で PNG の整合性を検証。NG なら quality.integrity_ok=False。"""
    img, _ = _entry_paths(key)
    if not img.exists():
        return False
    try:
        from PIL import Image
        with Image.open(img) as im:
            im.verify()  # type: ignore[no-untyped-call]
        is_integrity_ok = True
    except Exception as e:
        logger.debug("bg_cache verify integrity failed (%s): %s", img, e)
        is_integrity_ok = False
    _update_quality(key, integrity_ok=is_integrity_ok)
    return is_integrity_ok
