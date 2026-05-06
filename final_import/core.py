"""Stage 8 (final_import) の中核ハンドラ。

3 経路 (watchdog / HTTP / CLI) から呼ばれる純関数 import_final を中心に、
metadata.json の `final_versions` 配列で複数バージョンの取り込みを管理する。
canonical な final は analytics と publish の正本として扱う。
"""

import json
import logging
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import config
import progress_store
import staged_pipeline

logger = logging.getLogger(__name__)

FINAL_DIR_NAME = "final"
ALLOWED_EXTS = (".mp4", ".mov", ".m4v")
SourceLiteral = Literal["watch", "ui", "cli"]


@dataclass
class FinalVersion:
    filename: str
    imported_at: str
    duration_sec: float | None
    size_bytes: int
    audio_match_score: float | None
    source: str
    is_canonical: bool


def final_dir(ts_path: str) -> Path:
    return Path(ts_path) / FINAL_DIR_NAME


def ensure_final_dir(ts_path: str) -> Path:
    d = final_dir(ts_path)
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_final_versions(ts_path: str) -> list[FinalVersion]:
    meta = staged_pipeline.read_metadata(ts_path) or {}
    rows = meta.get("final_versions") or []
    out: list[FinalVersion] = []
    for r in rows:
        try:
            out.append(FinalVersion(**r))
        except TypeError:
            logger.warning("不正な final_versions エントリをスキップ: %r", r)
    return out


def canonical_final_path(ts_path: str) -> Path | None:
    """canonical な final ファイルの絶対パス。無ければ None。"""
    for v in list_final_versions(ts_path):
        if v.is_canonical:
            p = final_dir(ts_path) / v.filename
            if p.exists():
                return p
    return None


def resolve_canonical_video(ts_path: str) -> Path:
    """analytics / publish 用の正本動画パス。

    canonical final があればそれ、なければ pipeline raw (output/reels_<TS>.mp4)。
    どちらも無ければ FileNotFoundError。
    """
    canonical = canonical_final_path(ts_path)
    if canonical:
        return canonical
    ts = os.path.basename(os.path.normpath(ts_path))
    raw = Path(config.OUTPUT_DIR) / f"reels_{ts}.mp4"
    if raw.exists():
        return raw
    raise FileNotFoundError(
        f"canonical final / pipeline raw のいずれも見つかりません: {ts}",
    )


def import_final(
    ts: str,
    src_path: Path | str,
    source: SourceLiteral = "cli",
    skip_fingerprint: bool = False,
) -> FinalVersion:
    """CapCut 出力を取り込み、Stage 8 を generated にマークする。

    - `temp/<TS>/final/<HHMMSS>.<ext>` にコピー (拡張子は元を保持)
    - 音声指紋スコアを記録 (skip_fingerprint=True で省略可)
    - metadata.json の `final_versions` に追記、最新を canonical 化
    - progress_store の `final_import` を generated に
    - 既存承認は新バージョン取り込み時にリセット (= 再確認が必要)
    """
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(f"source not found: {src}")

    ts_path = os.path.join(config.TEMP_DIR, ts)
    if not os.path.isdir(ts_path):
        raise FileNotFoundError(f"project not found: temp/{ts}")

    if not progress_store.is_approved(ts_path, "overlay"):
        raise RuntimeError(
            "Stage 7 (overlay) が未承認のため取り込めません — UI で承認してください",
        )

    ext = src.suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError(
            f"unsupported extension: {ext} (allowed: {ALLOWED_EXTS})",
        )

    final_d = ensure_final_dir(ts_path)
    src_size = src.stat().st_size

    for v in list_final_versions(ts_path):
        existing = final_d / v.filename
        if not existing.exists():
            continue
        if existing.stat().st_size != src_size:
            continue
        try:
            if existing.samefile(src):
                logger.info("既に取り込み済み (samefile): %s", v.filename)
                return v
        except OSError:
            pass

    stamp = datetime.now().strftime("%H%M%S")
    dst_name = f"{stamp}{ext}"
    if (final_d / dst_name).exists():
        dst_name = f"{stamp}_{datetime.now().strftime('%f')}{ext}"
    dst = final_d / dst_name

    if src.parent.resolve() == final_d.resolve():
        # 既に final/ 内にあるファイル (= watchdog 経由) は move せず、ファイル名だけ保持
        dst = src
        dst_name = src.name
    else:
        shutil.copyfile(src, dst)

    duration = _ffprobe_duration(dst)
    size = dst.stat().st_size

    score: float | None = None
    if not skip_fingerprint:
        try:
            from .fingerprint import compute_match_score
            score = compute_match_score(ts_path, dst)
        except Exception as e:
            logger.warning("fingerprint 計算失敗 (%s): %s", dst_name, e)

    new_version = FinalVersion(
        filename=dst_name,
        imported_at=_now_iso(),
        duration_sec=duration,
        size_bytes=size,
        audio_match_score=score,
        source=source,
        is_canonical=True,
    )

    _append_final_version(ts_path, new_version)

    if not progress_store.is_generated(ts_path, "final_import"):
        progress_store.mark_generated(ts_path, "final_import")
    else:
        prog = progress_store.load(ts_path)
        prog["stages"]["final_import"]["approved_at"] = None
        progress_store.save(ts_path, prog)

    score_label = f"{score:.2f}" if score is not None else "-"
    logger.info(
        "[Stage 8] 取込完了: %s (source=%s, duration=%.1fs, score=%s)",
        dst_name, source, duration or 0, score_label,
    )
    return new_version


def set_canonical_final(ts_path: str, filename: str) -> FinalVersion:
    """指定 filename を canonical に切替える。他バージョンは非 canonical。"""
    meta = staged_pipeline.read_metadata(ts_path) or {}
    versions = meta.get("final_versions") or []
    target: dict | None = None
    for v in versions:
        if v.get("filename") == filename:
            v["is_canonical"] = True
            target = v
        else:
            v["is_canonical"] = False
    if target is None:
        raise ValueError(f"final version not found: {filename}")
    meta["final_versions"] = versions
    _save_metadata(ts_path, meta)
    return FinalVersion(**target)


def delete_final_version(ts_path: str, filename: str) -> None:
    """final version を削除。canonical だった場合は最新の他バージョンが canonical に。

    全バージョンが消えると Stage 8 の進捗をリセット。
    """
    meta = staged_pipeline.read_metadata(ts_path) or {}
    versions = meta.get("final_versions") or []
    target = next((v for v in versions if v.get("filename") == filename), None)
    if target is None:
        raise ValueError(f"final version not found: {filename}")
    was_canonical = bool(target.get("is_canonical"))
    versions = [v for v in versions if v.get("filename") != filename]
    if was_canonical and versions:
        versions.sort(key=lambda v: v.get("imported_at", ""))
        for v in versions:
            v["is_canonical"] = False
        versions[-1]["is_canonical"] = True
    meta["final_versions"] = versions
    _save_metadata(ts_path, meta)

    file_path = final_dir(ts_path) / filename
    if file_path.exists():
        file_path.unlink()

    if not versions:
        progress_store.reset_stage(ts_path, "final_import")


def _append_final_version(ts_path: str, version: FinalVersion) -> None:
    meta = staged_pipeline.read_metadata(ts_path) or {}
    existing = meta.get("final_versions") or []
    for v in existing:
        v["is_canonical"] = False
    existing.append(asdict(version))
    meta["final_versions"] = existing
    _save_metadata(ts_path, meta)


def _save_metadata(ts_path: str, meta: dict) -> None:
    p = os.path.join(ts_path, "metadata.json")
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ffprobe_duration(path: Path) -> float | None:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return None
