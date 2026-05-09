"""Stage 7 (final_import) の中核ハンドラ。

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
import io_utils
import preflight
import progress_store
import project_state
import staged_pipeline

logger = logging.getLogger(__name__)

FINAL_DIR_NAME = "final"
ALLOWED_EXTS = (".mp4", ".mov", ".m4v")
SourceLiteral = Literal["watch", "ui", "cli"]


def has_mp4_ftyp_atom(path: Path | str) -> bool:
    """MP4 / MOV / M4V は先頭 box が ftyp で、bytes 4-7 が "ftyp" になる。

    `.txt` を `.mp4` にリネームしただけ等の事故を弾く。攻撃対策ではなく事故防止。
    """
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return False
    if len(head) < 8:
        return False
    return head[4:8] == b"ftyp"


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
    meta = project_state.read_metadata(ts_path) or {}
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
    preflight.check_stage("final_import")

    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(f"source not found: {src}")

    ts_path = os.path.join(config.TEMP_DIR, ts)
    if not os.path.isdir(ts_path):
        raise FileNotFoundError(f"project not found: temp/{ts}")

    if not progress_store.is_approved(ts_path, "overlay"):
        raise RuntimeError(
            "字幕 が未承認のため取り込めません — UI で承認してください",
        )

    ext = src.suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError(
            f"unsupported extension: {ext} (allowed: {ALLOWED_EXTS})",
        )
    if not has_mp4_ftyp_atom(src):
        raise ValueError(
            f"not a valid MP4/MOV file (ftyp atom missing): {src.name}",
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

    # 経路に依らず安全な一意名 (HHMMSS[.MICRO].<ext>) にリネーム / コピーする。
    # 元ファイル名が unsafe (= 空白や記号入り) でも API regex `^[\w\.\-]+$` を必ず通過し、
    # 同名再ドロップでも一意の history エントリになる。
    dst_name = _allocate_unique_name(final_d, ext)
    dst = final_d / dst_name

    if src.parent.resolve() == final_d.resolve():
        # 既に final/ 内 (= watchdog がドロップを検知) → in-place rename
        if src.name != dst_name:
            os.rename(src, dst)
        else:
            dst = src
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
    if score is not None and score < config.FINGERPRINT_THRESHOLD:
        logger.warning(
            "[取込] fingerprint score=%.2f が閾値 %.2f 未満 — "
            "pipeline raw との音声乖離の可能性: %s",
            score, config.FINGERPRINT_THRESHOLD, dst_name,
        )

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
    _on_canonical_change(ts_path, ensure_generated=True)

    score_label = f"{score:.2f}" if score is not None else "-"
    logger.info(
        "[取込] 完了: %s (source=%s, duration=%.1fs, score=%s)",
        dst_name, source, duration or 0, score_label,
    )
    return new_version


def set_canonical_final(ts_path: str, filename: str) -> FinalVersion:
    """指定 filename を canonical に切替える。他バージョンは非 canonical。

    canonical が実際に変わったときは Stage 7 (final_import) の承認と
    Stage 8 (publish) の進捗を取り直しさせる (= 旧 canonical の publish 承認が
    新 canonical に流用されないように)。`metadata.json.published_posts` の
    投稿履歴は残る。
    """
    meta = project_state.read_metadata(ts_path) or {}
    versions = meta.get("final_versions") or []
    target: dict | None = None
    canonical_changed = False
    for v in versions:
        if v.get("filename") == filename:
            if not v.get("is_canonical"):
                canonical_changed = True
            v["is_canonical"] = True
            target = v
        else:
            if v.get("is_canonical"):
                canonical_changed = True
            v["is_canonical"] = False
    if target is None:
        raise ValueError(f"final version not found: {filename}")
    meta["final_versions"] = versions
    _save_metadata(ts_path, meta)
    if canonical_changed:
        _on_canonical_change(ts_path, ensure_generated=False)
    return FinalVersion(**target)


def delete_final_version(ts_path: str, filename: str) -> None:
    """final version を削除。canonical だった場合は最新の他バージョンが canonical に。

    canonical が変わったときは Stage 7/8 の承認を取り直しにする。
    全バージョンが消えると Stage 7 の進捗そのものをリセット (= reset_stage が
    Stage 8 もまとめて消す)。
    """
    meta = project_state.read_metadata(ts_path) or {}
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
        # Stage 7 を完全リセット → reset_stage が STAGES[idx:] を全消去するので
        # Stage 8 (publish) もまとめてクリアされる
        progress_store.reset_stage(ts_path, "final_import")
    elif was_canonical:
        _on_canonical_change(ts_path, ensure_generated=False)


def _append_final_version(ts_path: str, version: FinalVersion) -> None:
    meta = project_state.read_metadata(ts_path) or {}
    existing = meta.get("final_versions") or []
    for v in existing:
        v["is_canonical"] = False
    existing.append(asdict(version))
    meta["final_versions"] = existing
    _save_metadata(ts_path, meta)


def _allocate_unique_name(final_d: Path, ext: str) -> str:
    """`HHMMSS<ext>` を返す。衝突時は microsec 込みで再試行、それでも被ったら uuid。"""
    now = datetime.now()
    stamp = now.strftime("%H%M%S")
    candidate = f"{stamp}{ext}"
    if not (final_d / candidate).exists():
        return candidate
    candidate = f"{stamp}_{now.strftime('%f')}{ext}"
    if not (final_d / candidate).exists():
        return candidate
    import uuid as _uuid
    return f"{stamp}_{_uuid.uuid4().hex[:8]}{ext}"


def _on_canonical_change(ts_path: str, *, ensure_generated: bool) -> None:
    """canonical が変わったときに呼ぶ進捗リセット。

    - ``ensure_generated=True`` → ``final_import`` を generated に (= 取込新規)
    - 常に ``final_import.approved_at`` を消す (= 再確認を強制)
    - 常に ``publish`` を generated/approved とも消す (= 旧 canonical の
      publish 承認や generated フラグが新 canonical に流用されないように。
      published_posts 履歴は metadata 側に残す)
    """
    if ensure_generated:
        if not progress_store.is_generated(ts_path, "final_import"):
            progress_store.mark_generated(ts_path, "final_import")
    prog = progress_store.load(ts_path)
    prog["stages"]["final_import"]["approved_at"] = None
    prog["stages"]["publish"]["generated_at"] = None
    prog["stages"]["publish"]["approved_at"] = None
    progress_store.save(ts_path, prog)


def _save_metadata(ts_path: str, meta: dict) -> None:
    """metadata.json を fsync 込みで atomic に書き出す。
    手書きの open+replace は fsync が抜けて kill -9 で 0byte ファイルが
    残ったり .tmp が孤立する可能性があったので、io_utils.atomic_write_json
    に統一する (= preview_server の _cleanup_partial_artifacts も同じ規約で
    .tmp を回収できる)。"""
    io_utils.atomic_write_json(os.path.join(ts_path, "metadata.json"), meta)


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
