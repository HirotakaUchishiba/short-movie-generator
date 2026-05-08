#!/usr/bin/env python3
"""Phase 1: 参考動画を yt-dlp で取得し analytics DB に登録する。

使い方:
    python3 scripts/fetch_reference.py <URL> --license user_owned [--max-duration 90]

動作:
    1. yt-dlp で URL から動画を DL (= mp4 優先)
    2. sha256 を計算し ``data/reference_videos_fetched/<sha>.mp4`` に保存
    3. analytics.reference_videos に source_url / fetched_at / license_status
       を必須項目として登録 (= analyze pipeline は license_status="unconfirmed"
       を弾く)

license は ``user_owned`` / ``fair_use_review`` / ``public_domain`` から
明示的に選ばせる。CLI 引数として必須化することで著作権配慮を運用に
組み込む (= "とりあえず DL" を防ぐ)。
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import log_setup  # noqa: E402
import config  # noqa: E402
from analytics import db  # noqa: E402

VALID_LICENSES = ("user_owned", "fair_use_review", "public_domain")

REFERENCE_DIR = Path(config.BASE_DIR) / "data" / "reference_videos_fetched"

logger = logging.getLogger(__name__)


def fetch_with_ytdlp(url: str, dest_dir: Path,
                     max_duration: float | None = None,
                     timeout_sec: int = 600) -> Path:
    """yt-dlp 経由で 1 動画を DL し、ローカル mp4 のパスを返す。

    `--merge-output-format mp4` で container を強制 mp4 化する
    (= ffmpeg 経由で remux されるので、best fallback (webm 等) でも .mp4 中身に
    なる)。失敗時は tmp ファイルを必ず unlink する (= leak 防止)。

    Raises:
        RuntimeError: yt-dlp が見つからない / 失敗 / timeout / 空ファイル。
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp_handle = tempfile.NamedTemporaryFile(
        suffix=".mp4", dir=str(dest_dir), delete=False,
    )
    tmp_path = Path(tmp_handle.name)
    tmp_handle.close()

    args = [
        "yt-dlp",
        "-f", "best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", str(tmp_path),
        "--no-progress", "--quiet",
        "--no-mtime",
    ]
    if max_duration is not None:
        args.extend(["--match-filter", f"duration <= {int(max_duration)}"])
    args.append(url)

    success = False
    try:
        try:
            subprocess.run(args, check=True, timeout=timeout_sec)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError) as e:
            raise RuntimeError(f"yt-dlp failed for {url!r}: {e}") from e
        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise RuntimeError(
                f"yt-dlp が空ファイルを返しました (URL skipped かも): {url}",
            )
        success = True
        return tmp_path
    finally:
        if not success and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def fetch_and_register(url: str, license_status: str,
                       max_duration: float | None = None) -> dict:
    """fetch + sha 計算 + ``data/reference_videos_fetched/<sha>.mp4`` 配置 +
    DB 登録までを 1 関数で行う。

    Returns:
        ``{"sha256", "path", "size_bytes", "source_url", "license_status"}``。

    Raises:
        ValueError: license_status が ``VALID_LICENSES`` 外。
        RuntimeError: yt-dlp の失敗。
    """
    if license_status not in VALID_LICENSES:
        raise ValueError(
            f"license は {VALID_LICENSES} のいずれかを明示してください "
            f"(= 著作権配慮の必須項目)",
        )
    db.init_db()
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)

    tmp_path = fetch_with_ytdlp(url, REFERENCE_DIR, max_duration)
    try:
        sha = _sha256_file(tmp_path)
        final_path = REFERENCE_DIR / f"{sha}.mp4"
        if final_path.exists():
            # 同じ sha が既に居る (= 同 URL の再 fetch / 別 URL でも同内容) → tmp 破棄
            try:
                tmp_path.unlink()
            except OSError:
                pass
        else:
            tmp_path.replace(final_path)
    except Exception:
        # sha256 計算失敗 / replace 失敗時は tmp が孤立するので必ず掃除する
        # (= disk full 等で leak しない保険)。
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise

    size = final_path.stat().st_size
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db.get_connection() as conn:
        existing = conn.execute(
            "SELECT sha256 FROM reference_videos WHERE sha256 = ?", (sha,),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE reference_videos
                   SET source_url = ?, fetched_at = ?, license_status = ?,
                       last_used_at = ?
                   WHERE sha256 = ?""",
                (url, now_iso, license_status, now_iso, sha),
            )
        else:
            conn.execute(
                """INSERT INTO reference_videos
                   (sha256, original_name, size_bytes, uploaded_at,
                    source_url, fetched_at, license_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (sha, final_path.name, size, now_iso,
                 url, now_iso, license_status),
            )
    logger.info(
        "reference_video registered: sha=%s license=%s size=%d url=%s",
        sha[:12], license_status, size, url,
    )
    return {
        "sha256": sha,
        "path": str(final_path),
        "size_bytes": size,
        "source_url": url,
        "license_status": license_status,
    }


def main() -> int:
    log_setup.setup()
    parser = argparse.ArgumentParser(prog="fetch_reference")
    parser.add_argument("url", help="参考動画の URL (yt-dlp 対応)")
    parser.add_argument(
        "--license", required=True, choices=VALID_LICENSES,
        help="ライセンス区分 (= 必須。analyze pipeline で gate される)",
    )
    parser.add_argument(
        "--max-duration", type=float, default=None,
        help="最大長 (秒)。超える動画は yt-dlp が skip する",
    )
    args = parser.parse_args()

    try:
        result = fetch_and_register(args.url, args.license, args.max_duration)
    except (ValueError, RuntimeError) as e:
        logger.error("fetch_reference failed: %s", e)
        return 1

    print(f"sha256: {result['sha256']}")
    print(f"path:   {result['path']}")
    print(f"size:   {result['size_bytes']:,} bytes")
    print(f"license: {result['license_status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
