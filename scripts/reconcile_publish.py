#!/usr/bin/env python3
"""publish 後の analytics DB 登録漏れを scan + 自動 retry する CLI。

``temp/<TS>/metadata.json.published_posts[]`` を全 project scan し、
``analytics_persisted=false`` の post に対して analytics DB への
``_ensure_video_in_analytics`` + ``register_post`` を retry する。

成功時は metadata.json の該当 entry の ``analytics_persisted`` を ``true``
に更新し ``analytics_warning`` を消す。失敗時は warning ログを残して次へ
進む (= 部分失敗を許容、cron で 1 日 1 回回す想定)。

使い方:
    python3 scripts/reconcile_publish.py
    python3 scripts/reconcile_publish.py --dry-run
    python3 scripts/reconcile_publish.py --ts 20260425_120000

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.9
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._cli_base import get_logger  # noqa: E402

logger = get_logger(__name__)


def _scan_unpersisted_posts(temp_dir: Path) -> list[tuple[Path, dict, int]]:
    """全 metadata.json を scan して analytics_persisted=false を集める。

    Returns: ``[(metadata_path, post_dict, index_in_published_posts), ...]``
    """
    found: list[tuple[Path, dict, int]] = []
    if not temp_dir.exists():
        return found
    for project_dir in sorted(p for p in temp_dir.iterdir() if p.is_dir()):
        meta_path = project_dir / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("metadata.json 読込失敗 %s: %s", meta_path, e)
            continue
        for i, post in enumerate(meta.get("published_posts") or []):
            if post.get("analytics_persisted") is False:
                found.append((meta_path, post, i))
    return found


def _retry_persist(ts: str, post: dict) -> tuple[bool, str | None]:
    """1 post を analytics DB に再登録。成功 (True, None) / 失敗 (False, error)。"""
    import config
    from analytics import db as analytics_db
    from final_import import publish as _publish

    ts_path = Path(config.TEMP_DIR) / ts
    try:
        video = _publish.resolve_canonical_video(str(ts_path))
    except Exception as e:
        return False, f"動画パス解決失敗: {e}"

    try:
        analytics_db.init_db()
        _publish._ensure_video_in_analytics(ts, video)
        analytics_db.register_post(
            video_id=ts,
            platform=post.get("platform", "youtube"),
            platform_post_id=post.get("video_id", ""),
            url=post.get("url"),
            posted_at=post.get("posted_at"),
            caption=post.get("caption"),
            hashtags=post.get("hashtags") or [],
        )
        return True, None
    except Exception as e:
        return False, str(e)


def _update_metadata_persisted(meta_path: Path, post_index: int) -> None:
    """metadata.json の published_posts[post_index].analytics_persisted を
    ``true`` に更新し ``analytics_warning`` を削除する (= 再登録成功時)。"""
    with open(meta_path) as f:
        meta = json.load(f)
    posts = meta.get("published_posts") or []
    if post_index >= len(posts):
        return
    posts[post_index]["analytics_persisted"] = True
    posts[post_index].pop("analytics_warning", None)
    tmp = meta_path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    tmp.replace(meta_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ts", help="指定 TS のみ処理")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="実際に DB 登録せず一覧のみ表示",
    )
    args = parser.parse_args()

    import config

    temp_dir = Path(config.TEMP_DIR)
    found = _scan_unpersisted_posts(temp_dir)
    if args.ts:
        found = [t for t in found if t[0].parent.name == args.ts]

    if not found:
        logger.info("analytics_persisted=false な published_posts はありません")
        return 0

    logger.info("対象 %d 件:", len(found))
    succeeded = 0
    failed = 0
    for meta_path, post, idx in found:
        ts = meta_path.parent.name
        platform = post.get("platform", "?")
        url = post.get("url", "(no url)")
        if args.dry_run:
            logger.info("  [dry-run] %s / %s / %s", ts, platform, url)
            continue
        ok, err = _retry_persist(ts, post)
        if ok:
            _update_metadata_persisted(meta_path, idx)
            logger.info("  ✓ %s / %s / %s", ts, platform, url)
            succeeded += 1
        else:
            logger.warning("  ✗ %s / %s / %s — %s", ts, platform, url, err)
            failed += 1

    logger.info("完了: 成功 %d / 失敗 %d", succeeded, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
