#!/usr/bin/env python3
"""Phase 4: 公開済み動画を 1 コマンドで取り下げる。

- YouTube: Data API で ``privacyStatus=private`` に降格 (= 削除はしない)
- Instagram / TikTok: API 削除は Phase 4 では未実装。Slack に手動削除を
  促す通知を流して clipboard に URL をコピー、運用者が Studio から消す。

`posts` テーブルに ``rollback_at`` カラムを足す代わりに、Slack 通知 +
audit_freeze で履歴を残す方針 (= 既存スキーマを壊さない)。

使い方:
    python3 scripts/rollback.py <video_id>
    python3 scripts/rollback.py <video_id> --platform youtube
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import log_setup  # noqa: E402
from analytics import db  # noqa: E402
from notify import notify_slack  # noqa: E402

logger = logging.getLogger(__name__)


def rollback_youtube(platform_post_id: str) -> dict:
    """YouTube 動画を ``privacyStatus=private`` に降格する。

    Raises:
        RuntimeError: OAuth env が揃っていない / API エラー。
    """
    import requests

    client_id = os.getenv("YOUTUBE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_OAUTH_CLIENT_SECRET")
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN")
    if not all([client_id, client_secret, refresh_token]):
        raise RuntimeError(
            "YOUTUBE_OAUTH_CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN が必要",
        )

    from platform_clients.youtube import _oauth_access_token
    token = _oauth_access_token(client_id, client_secret, refresh_token)

    resp = requests.put(
        "https://www.googleapis.com/youtube/v3/videos?part=status",
        json={
            "id": platform_post_id,
            "status": {"privacyStatus": "private"},
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(
            f"YouTube rollback API error {resp.status_code}: {resp.text[:300]}",
        )
    return resp.json()


def _resolve_posts(video_id: str,
                   platform: str | None) -> list[dict]:
    posts = db.list_active_posts(platform=platform)
    return [p for p in posts if p.get("video_id") == video_id]


def rollback_video(video_id: str, *,
                   platform: str | None = None) -> dict:
    """``video_id`` に紐付く全 platform の post を取り下げる。

    Returns:
        ``{platform: {"post_id": ..., "status": "private"|"manual_required"|"failed"}}``
    """
    target = _resolve_posts(video_id, platform)
    if not target:
        raise ValueError(f"video_id={video_id} に対する post が見つかりません")

    results: dict[str, dict] = {}
    for p in target:
        plat = p["platform"]
        post_id = p.get("id")
        try:
            if plat == "youtube":
                rollback_youtube(p["platform_post_id"])
                notify_slack(
                    "warning",
                    f"rollback youtube: {p.get('url') or post_id}",
                    context={"video_id": video_id, "post_id": post_id},
                )
                results[plat] = {"post_id": post_id, "status": "private"}
            else:
                # IG / TikTok は API 削除を実装していない (= Phase 4 範囲外)
                notify_slack(
                    "warning",
                    f"manual rollback required for {plat}: "
                    f"{p.get('url') or post_id}",
                    context={"video_id": video_id, "post_id": post_id},
                )
                results[plat] = {"post_id": post_id,
                                 "status": "manual_required"}
        except Exception as e:
            logger.exception("rollback %s failed", plat)
            notify_slack(
                "error", f"rollback {plat} failed: {e}",
                context={"video_id": video_id, "post_id": post_id},
            )
            results[plat] = {"post_id": post_id, "status": "failed",
                             "error": str(e)}
    return results


def main() -> int:
    log_setup.setup()
    parser = argparse.ArgumentParser(prog="rollback")
    parser.add_argument("video_id", help="videos.id (= sha256[:12])")
    parser.add_argument("--platform",
                        choices=("youtube", "instagram", "tiktok"),
                        help="特定 platform のみ取り下げ")
    args = parser.parse_args()

    try:
        results = rollback_video(args.video_id, platform=args.platform)
    except ValueError as e:
        logger.error(str(e))
        return 1

    print(f"rollback results for video_id={args.video_id}:")
    for plat, info in results.items():
        print(f"  {plat}: {info['status']} (post_id={info['post_id']})")
        if info["status"] == "failed":
            print(f"    error: {info.get('error')}")
    has_failure = any(r["status"] == "failed" for r in results.values())
    return 1 if has_failure else 0


if __name__ == "__main__":
    sys.exit(main())
