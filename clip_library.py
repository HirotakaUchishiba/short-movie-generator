"""Layer 1: Clip Library (= 重い AI 生成パーツの再利用層)。

screenplay の identity (= character_refs / location_ref / start_emotion /
camera_distance) で entry をフィルタし、annotation (= visual_intent_id /
duration_bucket / motion_intensity) でランクして top-k を variant pool として返す。

設計 doc:
    docs/plannings/2026-05-10_compositional-architecture.md §3

不変条件:
- identity は **hard match** (= 一致しない entry は絶対に hit しない)
- annotation は **soft rank** (= 完全一致が無くても compatible_with 経由で fallback)
- compositional パーツ (= subtitle_style / sticker / transition 等) は entry の
  identity / annotation には含めない。Layer 2 / 3 で都度合成するため
- variant 選択は (ts, scene_idx) を seed とする決定論的 hash

本モジュールは **データ層と lookup ロジックのみ** を提供する。
AI 生成 (= Imagen / Kling 呼び出し) は scene_gen / bg_cache / kling_cache 経由で行い、
本モジュールへの register は cold path から呼ばれる (= Phase 2 で wire)。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

import config

logger = logging.getLogger(__name__)


# ───────────── データクラス ─────────────


@dataclass(frozen=True)
class ClipIdentity:
    """hard match される視覚アイデンティティ (= ここが揃わない entry は絶対 hit しない)。

    `character_refs` は順序非依存。`==` 比較は frozenset 経由で行う。
    """

    character_refs: tuple[str, ...]
    location_ref: str
    start_emotion: str
    camera_distance: str = "medium-close"

    def char_set(self) -> frozenset[str]:
        return frozenset(self.character_refs)

    def matches(self, other: "ClipIdentity") -> bool:
        return (
            self.char_set() == other.char_set()
            and self.location_ref == other.location_ref
            and self.start_emotion == other.start_emotion
            and self.camera_distance == other.camera_distance
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_refs": list(self.character_refs),
            "location_ref": self.location_ref,
            "start_emotion": self.start_emotion,
            "camera_distance": self.camera_distance,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ClipIdentity":
        return cls(
            character_refs=tuple(d["character_refs"]),
            location_ref=d["location_ref"],
            start_emotion=d["start_emotion"],
            camera_distance=d.get("camera_distance", "medium-close"),
        )


@dataclass
class ClipAnnotation:
    """soft rank に使う注釈情報 (= 一致しなくても hit はする、スコアが下がるだけ)。"""

    visual_intent_id: str | None = None
    duration_bucket: int | None = None
    motion_intensity: str = "low"
    generation_seed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ClipAnnotation":
        return cls(
            visual_intent_id=d.get("visual_intent_id"),
            duration_bucket=d.get("duration_bucket"),
            motion_intensity=d.get("motion_intensity", "low"),
            generation_seed=d.get("generation_seed"),
        )


@dataclass
class ClipProvenance:
    """デバッグ + 再生成の根拠。lookup には使わない。"""

    imagen_prompt: str = ""
    kling_prompt: str = ""
    ref_image_shas: dict[str, str] = field(default_factory=dict)
    location_sha: str | None = None
    model_versions: dict[str, str] = field(default_factory=dict)
    generated_at: str = ""
    source_screenplay: str | None = None
    source_scene_idx: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ClipProvenance":
        return cls(
            imagen_prompt=d.get("imagen_prompt", ""),
            kling_prompt=d.get("kling_prompt", ""),
            ref_image_shas=dict(d.get("ref_image_shas") or {}),
            location_sha=d.get("location_sha"),
            model_versions=dict(d.get("model_versions") or {}),
            generated_at=d.get("generated_at", ""),
            source_screenplay=d.get("source_screenplay"),
            source_scene_idx=d.get("source_scene_idx"),
        )


ClipStatus = Literal["pending_review", "active", "blacklisted"]


@dataclass
class ClipLifecycle:
    """承認 / 利用統計 / blacklist 等の lifecycle 管理。"""

    status: ClipStatus = "pending_review"
    approved_at: str | None = None
    hit_count: int = 0
    last_used_at: str | None = None
    blacklisted: bool = False
    blacklist_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ClipLifecycle":
        status = d.get("status", "pending_review")
        if status not in ("pending_review", "active", "blacklisted"):
            status = "pending_review"
        return cls(
            status=status,  # type: ignore[arg-type]
            approved_at=d.get("approved_at"),
            hit_count=int(d.get("hit_count", 0)),
            last_used_at=d.get("last_used_at"),
            blacklisted=bool(d.get("blacklisted", False)),
            blacklist_reason=d.get("blacklist_reason"),
        )


@dataclass
class ClipEntry:
    """Layer 1 cache の 1 entry。

    対応する物理ファイル:
        cache/clips/<id>/meta.json       ← この entry のシリアライズ
        cache/clips/<id>/bg.png          ← Imagen 出力 (静止画)
        cache/clips/<id>/kling_clean.mp4 ← Kling 出力 (lipsync 前)
        cache/clips/<id>/preview.gif     ← (任意、UI 表示用)
    """

    id: str
    identity: ClipIdentity
    annotation: ClipAnnotation
    provenance: ClipProvenance
    lifecycle: ClipLifecycle

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "identity": self.identity.to_dict(),
            "annotation": self.annotation.to_dict(),
            "provenance": self.provenance.to_dict(),
            "lifecycle": self.lifecycle.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ClipEntry":
        return cls(
            id=d["id"],
            identity=ClipIdentity.from_dict(d["identity"]),
            annotation=ClipAnnotation.from_dict(d["annotation"]),
            provenance=ClipProvenance.from_dict(d["provenance"]),
            lifecycle=ClipLifecycle.from_dict(d.get("lifecycle") or {}),
        )

    def entry_dir(self, root: Path | None = None) -> Path:
        return _entry_dir(self.id, root)

    def bg_path(self, root: Path | None = None) -> Path:
        return self.entry_dir(root) / "bg.png"

    def kling_path(self, root: Path | None = None) -> Path:
        return self.entry_dir(root) / "kling_clean.mp4"


# ───────────── ファイルシステムレイアウト ─────────────


def _library_root() -> Path:
    root = getattr(config, "CLIP_LIBRARY_DIR", None)
    if not root:
        root = os.path.join(config.BASE_DIR, "cache", "clips")
    p = Path(root)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _entry_dir(entry_id: str, root: Path | None = None) -> Path:
    root = root or _library_root()
    return root / entry_id


def _meta_path(entry_id: str, root: Path | None = None) -> Path:
    return _entry_dir(entry_id, root) / "meta.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _new_entry_id() -> str:
    """衝突回避用の short uuid (= 16 hex chars)。"""

    return uuid.uuid4().hex[:16]


# ───────────── 永続化 ─────────────


def load_entry(entry_id: str, root: Path | None = None) -> ClipEntry | None:
    """meta.json を読んで ClipEntry を復元する。存在しなければ None。"""

    mp = _meta_path(entry_id, root)
    if not mp.exists():
        return None
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[clip-library] meta load failed for %s: %s", entry_id, e)
        return None
    try:
        return ClipEntry.from_dict(data)
    except (KeyError, TypeError, ValueError) as e:
        logger.warning("[clip-library] meta parse failed for %s: %s", entry_id, e)
        return None


def save_entry(entry: ClipEntry, root: Path | None = None) -> None:
    """meta.json に書き込む。entry_dir を必要なら作成。"""

    d = _entry_dir(entry.id, root)
    d.mkdir(parents=True, exist_ok=True)
    mp = d / "meta.json"
    tmp = mp.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(entry.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, mp)


def iter_all_entries(root: Path | None = None) -> Iterator[ClipEntry]:
    """全 entry を yield する (= 順序保証なし、blacklist 含む)。"""

    base = root or _library_root()
    if not base.exists():
        return
    for entry_dir in base.iterdir():
        if not entry_dir.is_dir():
            continue
        entry = load_entry(entry_dir.name, root=base)
        if entry is not None:
            yield entry


def iter_active_entries(root: Path | None = None) -> Iterator[ClipEntry]:
    """status=="active" かつ blacklisted でない entry のみ yield。"""

    for entry in iter_all_entries(root):
        if entry.lifecycle.blacklisted:
            continue
        if entry.lifecycle.status != "active":
            continue
        yield entry


# ───────────── lookup / variant 選択 ─────────────


def _scene_to_identity(scene: dict) -> ClipIdentity:
    """screenplay scene dict から ClipIdentity を派生。

    analyze pipeline が nested `scene.identity` を SSOT として常に produce する
    前提で、flat schema (= scene root の `character_refs` 等) は受け付けない。
    nested identity 不在時は ValueError を raise する。
    """

    if "identity" in scene and isinstance(scene["identity"], dict):
        return ClipIdentity.from_dict(scene["identity"])
    raise ValueError("scene missing identity")


def _scene_to_annotation_request(scene: dict) -> dict[str, Any]:
    if "annotation" in scene and isinstance(scene["annotation"], dict):
        a = scene["annotation"]
        return {
            "visual_intent_id": a.get("visual_intent_id"),
            "duration_bucket": a.get("duration_bucket"),
            "motion_intensity": a.get("motion_intensity", "low"),
        }
    return {}


def _annotation_score(entry: ClipEntry, requested: dict[str, Any]) -> float:
    """annotation の degree match スコア。高いほど良い候補。

    **不変条件**: スコア計算に entry の動的状態 (= hit_count / last_used_at 等) を
    含めない。同 (ts, scene_idx) で同じ entry が選ばれる **決定論性** を保つため。
    variant 多様性は variant pool の母数 + (ts, scene_idx) seed で確保する。
    """

    score = 0.0
    a = entry.annotation
    req_intent = requested.get("visual_intent_id")
    if a.visual_intent_id is not None and a.visual_intent_id == req_intent:
        score += 3.0
    elif req_intent and _intent_compatible(a.visual_intent_id, req_intent):
        score += 1.5
    if (
        a.duration_bucket is not None
        and a.duration_bucket == requested.get("duration_bucket")
    ):
        score += 1.0
    if a.motion_intensity == requested.get("motion_intensity", "low"):
        score += 0.5
    return score


def _scene_has_override(scene: dict) -> bool:
    """scene が novel intent escape hatch (= `_override_*`) を設定しているか判定。

    satisfy / register / scene_gen の 3 箇所で同一 check を使うため共通化。
    どちらか片方でも非空なら True (= clip_library を bypass する判断は両者
    同等扱い)。
    """

    return bool(
        (scene.get("_override_background_prompt") or "").strip()
        if isinstance(scene.get("_override_background_prompt"), str)
        else False
    ) or bool(
        (scene.get("_override_animation_prompt") or "").strip()
        if isinstance(scene.get("_override_animation_prompt"), str)
        else False
    )


def lookup_clip_pool(
    scene: dict,
    top_k: int | None = None,
    root: Path | None = None,
) -> list[ClipEntry]:
    """scene の identity に hard match する active entry のうち、annotation で
    rank した top-k を variant pool として返す。

    引数:
        scene: screenplay の 1 scene (= identity / annotation を持つ新スキーマ、または
            character_refs / location_ref / start_emotion 等を直接持つ旧スキーマ)
        top_k: 返す件数。None なら config.CLIP_POOL_TOP_K (既定 10)
        root: cache root を上書き (= テスト用)

    返り値:
        annotation_score 降順の ClipEntry リスト。空の場合は cold path を起動すべき。
    """

    if top_k is None:
        top_k = int(getattr(config, "CLIP_POOL_TOP_K", 10))

    target_identity = _scene_to_identity(scene)
    candidates = [
        entry
        for entry in iter_active_entries(root)
        if entry.identity.matches(target_identity)
    ]
    if not candidates:
        return []

    requested_ann = _scene_to_annotation_request(scene)
    candidates.sort(key=lambda e: -_annotation_score(e, requested_ann))
    return candidates[:top_k]


def select_variant(pool: list[ClipEntry], ts: str, scene_idx: int) -> ClipEntry:
    """pool から (ts, scene_idx) seed で 1 entry を決定論的に選ぶ。

    同じ screenplay の rebuild では同じ ts / scene_idx になるため同じ entry が
    出る (= 字幕修正等で何度も rebuild する運用と整合)。別 project (= 別 ts)
    では別 entry が選ばれるため視聴者から見た多様性も担保される。
    """

    if not pool:
        raise ValueError("select_variant called on empty pool")
    seed = int(
        hashlib.sha256(f"{ts}|{scene_idx}".encode("utf-8")).hexdigest(),
        16,
    )
    return pool[seed % len(pool)]


# ───────────── intent_compatible (= part_registry yaml 経由) ─────────────


# yaml load + cache は part_registry_loader (= SSOT) に集約。
# 旧 _INTENT_COMPAT_CACHE / _load_intent_compat_map は削除済み。
import part_registry_loader as _registry


def _load_intent_compat_map() -> dict[str, frozenset[str]]:
    """visual_intents.yaml の id → compatible_with frozenset を返す (= SSOT 経由)。"""

    return _registry.compatible_with_map("visual_intents")


def _intent_compatible(a: str | None, b: str | None) -> bool:
    """visual_intents.yaml の compatible_with を双方向で参照する。"""

    if not a or not b or a == b:
        return False
    compat = _load_intent_compat_map()
    if b in compat.get(a, frozenset()):
        return True
    if a in compat.get(b, frozenset()):
        return True
    return False


def reset_intent_compat_cache() -> None:
    """テスト用: yaml を読み直すための cache クリア (= SSOT cache を消す)。"""

    _registry.reset_cache()


# ───────────── lifecycle 操作 ─────────────


def register_clip_entry(
    identity: ClipIdentity,
    annotation: ClipAnnotation,
    provenance: ClipProvenance,
    bg_src: str | os.PathLike[str] | None,
    kling_src: str | os.PathLike[str] | None,
    auto_approve: bool | None = None,
    root: Path | None = None,
) -> ClipEntry:
    """新規 entry を登録する。bg_src / kling_src があればコピーして所定パスに置く。

    auto_approve=None の場合は ``config.CLIP_POOL_AUTO_APPROVE`` を参照する。
    既定は False (= status=pending_review)。
    """

    if auto_approve is None:
        auto_approve = bool(getattr(config, "CLIP_POOL_AUTO_APPROVE", False))

    entry_id = _new_entry_id()
    now = _now_iso()
    lifecycle = ClipLifecycle(
        status="active" if auto_approve else "pending_review",
        approved_at=now if auto_approve else None,
        hit_count=0,
        last_used_at=None,
        blacklisted=False,
    )
    if not provenance.generated_at:
        provenance = ClipProvenance.from_dict(
            {**provenance.to_dict(), "generated_at": now}
        )
    entry = ClipEntry(
        id=entry_id,
        identity=identity,
        annotation=annotation,
        provenance=provenance,
        lifecycle=lifecycle,
    )

    # ── 並行登録時の partial state 防止 ──
    # `<id>.tmp` directory に書き切ってから atomic に `<id>` へ rename する。
    # rename は POSIX で同 filesystem 内なら atomic。これにより:
    #   - 別 process が iter_all_entries 中に途中状態を見ない
    #   - 失敗時 (= copy/Save 例外) は .tmp が残るだけで cache が破損しない
    final_dir = _entry_dir(entry_id, root)
    tmp_dir = final_dir.with_name(f".{entry_id}.tmp")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        if bg_src is not None:
            shutil.copyfile(os.fspath(bg_src), tmp_dir / "bg.png")
        if kling_src is not None:
            shutil.copyfile(os.fspath(kling_src), tmp_dir / "kling_clean.mp4")
        # meta.json も .tmp 内に書く (= save_entry は entry.id 経由で
        # 解決するため tmp_dir に直接 dump)
        (tmp_dir / "meta.json").write_text(
            json.dumps(entry.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # atomic rename: 同 parent dir 内なので POSIX で atomic
        os.replace(tmp_dir, final_dir)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    logger.info(
        "[clip-library] register %s identity=%s intent=%s status=%s",
        entry_id,
        _identity_repr(identity),
        annotation.visual_intent_id,
        lifecycle.status,
    )
    return entry


def approve_entry(entry_id: str, root: Path | None = None) -> bool:
    entry = load_entry(entry_id, root)
    if entry is None:
        return False
    entry.lifecycle.status = "active"
    entry.lifecycle.approved_at = _now_iso()
    entry.lifecycle.blacklisted = False
    entry.lifecycle.blacklist_reason = None
    save_entry(entry, root=root)
    return True


def blacklist_entry(
    entry_id: str, reason: str, root: Path | None = None
) -> bool:
    entry = load_entry(entry_id, root)
    if entry is None:
        return False
    entry.lifecycle.status = "blacklisted"
    entry.lifecycle.blacklisted = True
    entry.lifecycle.blacklist_reason = reason
    save_entry(entry, root=root)
    return True


def touch_entry(entry_id: str, root: Path | None = None) -> bool:
    """hit 時の hit_count++ + last_used_at 更新。

    並行 hit (= 複数 project が同時に同 entry を hit) で lost update が発生する
    のを防ぐため、meta.json を **直接 read-modify-write** + tmp + os.replace で
    atomic に行う。`load_entry` → mutate → `save_entry` の 3 step は使わない。

    厳密な mutex ではないが、書き込み window が小さいため衝突確率は十分低い
    (= 複数 process が ms 単位で重なった場合のみ lost update が起きる、その
    ケースでも file 自体は corrupt しない)。完全な correctness が必要になったら
    fcntl / portalocker での file lock を導入する。
    """

    mp = _meta_path(entry_id, root)
    if not mp.exists():
        return False
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("[clip-library] touch failed (parse): %s", e)
        return False
    lifecycle = data.setdefault("lifecycle", {})
    lifecycle["hit_count"] = int(lifecycle.get("hit_count", 0)) + 1
    lifecycle["last_used_at"] = _now_iso()
    tmp = mp.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, mp)
    except OSError as e:
        logger.warning("[clip-library] touch failed (write): %s", e)
        return False
    return True


# ───────────── production 経路への wire (= scene_gen / staged_pipeline 統合) ─────────────


def scene_has_identity(scene: dict) -> bool:
    """scene が identity 情報を持っているか (= public)。

    analyze pipeline が nested `scene.identity` を SSOT として常に produce する
    前提で、flat schema (= scene root の `character_refs` 等) は受け付けない。
    route blueprint からも参照する。
    """

    if isinstance(scene.get("identity"), dict):
        ident = scene["identity"]
        if all(
            ident.get(k) is not None
            for k in ("character_refs", "location_ref", "start_emotion")
        ):
            return True
    return False


# 旧 private 名 alias (= 内部 satisfy / register が依然 _scene_has_identity を
# 使うため)。新規参照は scene_has_identity を使うこと。
_scene_has_identity = scene_has_identity


def satisfy_scenes_from_library(
    screenplay: dict, ts_path: str, root: Path | None = None,
) -> dict[int, str]:
    """各 scene の identity に hit する clip があれば bg.png + kling_clean.mp4 を
    ``temp/<TS>/bg_<i>.png`` / ``temp/<TS>/kling_<i>.mp4`` に **コピー** する。

    既存の `_generate_single_background` / `_kling_for_scene` は当該パスが
    存在すれば AI 呼出をスキップする実装になっているため、このコピー操作
    だけで Stage 3 + 4 を短絡できる (= AI 課金 0)。

    miss / identity 無しの scene は何もしない (= 通常経路に fall-through)。

    Returns:
        ``{scene_idx: entry_id}`` の dict。hit した scene のみ含む。
    """

    if not bool(getattr(config, "CLIP_LIBRARY_ENABLED", False)):
        return {}

    ts = os.path.basename(os.path.normpath(ts_path))
    scenes = screenplay.get("scenes") or []
    out: dict[int, str] = {}

    for s_idx, scene in enumerate(scenes):
        if not _scene_has_identity(scene):
            continue
        if _scene_has_override(scene):
            # novel intent escape hatch が設定されている → clip_library を
            # bypass して旧 free-text 経路で生成させる
            continue

        try:
            pool = lookup_clip_pool(scene, root=root)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
            logger.warning(
                "[clip-library] scene %d lookup 失敗 (skip): %s", s_idx, e,
            )
            continue
        if not pool:
            continue

        try:
            entry = select_variant(pool, ts, s_idx)
        except ValueError:
            continue

        bg_dst = os.path.join(ts_path, f"bg_{s_idx:03d}.png")
        kling_dst = os.path.join(ts_path, f"kling_{s_idx:03d}.mp4")
        bg_src = entry.bg_path()
        kling_src = entry.kling_path()
        if not bg_src.exists() or not kling_src.exists():
            logger.warning(
                "[clip-library] scene %d: entry %s の bg/kling ファイル欠損 — skip",
                s_idx, entry.id,
            )
            continue

        try:
            shutil.copyfile(bg_src, bg_dst)
            shutil.copyfile(kling_src, kling_dst)
        except OSError as e:
            logger.warning(
                "[clip-library] scene %d: ファイルコピー失敗 (skip): %s",
                s_idx, e,
            )
            continue

        touch_entry(entry.id, root=root)
        out[s_idx] = entry.id
        logger.info(
            "[clip-library] HIT scene %d → entry %s (= bg + kling 取込済)",
            s_idx, entry.id,
        )

    if out:
        logger.info(
            "[clip-library] %d/%d scene が cache hit、AI 課金スキップ",
            len(out), len(scenes),
        )
    return out


def register_cold_path_clips(
    screenplay: dict,
    ts_path: str,
    satisfied: dict[int, str] | None = None,
    root: Path | None = None,
) -> dict[int, str]:
    """cold path で新規生成された bg + kling を clip_library に register する。

    対象: identity 情報を持ち、かつ `satisfied` (= 前段の satisfy_scenes_from_library
    が hit した scene_idx 集合) に **含まれない** scene。これらは Stage 3+4 で
    新規 AI 生成された bg / kling を持っているはずなので、library に追加する。

    `_override_*` が設定された scene も skip (= novel intent fallback は
    explicit に library 化しない、運用者が手動で promote する想定)。

    Returns:
        ``{scene_idx: new_entry_id}``。register された scene のみ。
    """

    if not bool(getattr(config, "CLIP_LIBRARY_ENABLED", False)):
        return {}

    satisfied = satisfied or {}
    scenes = screenplay.get("scenes") or []
    out: dict[int, str] = {}

    for s_idx, scene in enumerate(scenes):
        if s_idx in satisfied:
            continue
        if not _scene_has_identity(scene):
            continue
        if _scene_has_override(scene):
            continue

        bg_path = os.path.join(ts_path, f"bg_{s_idx:03d}.png")
        kling_path = os.path.join(ts_path, f"kling_{s_idx:03d}.mp4")
        if not (os.path.exists(bg_path) and os.path.exists(kling_path)):
            # cold path がまだ完了していない、または失敗したシーン
            continue

        try:
            identity = _scene_to_identity(scene)
        except (KeyError, ValueError) as e:
            logger.warning(
                "[clip-library] scene %d identity 抽出失敗 (skip): %s", s_idx, e,
            )
            continue
        ann_req = _scene_to_annotation_request(scene)
        annotation = ClipAnnotation(
            visual_intent_id=ann_req.get("visual_intent_id"),
            duration_bucket=ann_req.get("duration_bucket"),
            motion_intensity=ann_req.get("motion_intensity") or "low",
        )
        provenance = ClipProvenance(
            source_screenplay=os.path.basename(ts_path),
            source_scene_idx=s_idx,
        )
        try:
            entry = register_clip_entry(
                identity=identity,
                annotation=annotation,
                provenance=provenance,
                bg_src=bg_path,
                kling_src=kling_path,
                root=root,
            )
        except (OSError, ValueError) as e:
            logger.warning(
                "[clip-library] scene %d register 失敗 (skip): %s", s_idx, e,
            )
            continue
        out[s_idx] = entry.id

    if out:
        logger.info(
            "[clip-library] cold path %d 件を library に register "
            "(= status: %s、UI 承認後に hit 対象になる)",
            len(out),
            "active" if getattr(config, "CLIP_POOL_AUTO_APPROVE", False)
            else "pending_review",
        )
    return out


# ───────────── 内部ヘルパ ─────────────


def _identity_repr(identity: ClipIdentity) -> str:
    return (
        f"chars={','.join(identity.character_refs)}|"
        f"loc={identity.location_ref}|"
        f"start={identity.start_emotion}|"
        f"cam={identity.camera_distance}"
    )
