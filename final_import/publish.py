"""Stage 9: canonical な final 動画をプラットフォームに公開する。

YouTube は Data API resumable upload で完全自動。Instagram / TikTok は
Phase 1 までは半自動 (= caption をクリップボードにコピー + アプリ起動 +
動画ファイルを Finder で reveal)。公開成功後は analytics DB の posts
テーブルにも書き込み、register_post を別途叩かなくて良いようにする。
"""

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import config
import progress_store
import staged_pipeline

from .core import resolve_canonical_video

logger = logging.getLogger(__name__)

_HASHTAG_RE = re.compile(r"#([^\s#]+)")


def publish(ts: str, platform: str, **opts) -> dict:
    """canonical な final を指定 platform に公開し、analytics DB に登録する。

    platform: "youtube" / "instagram" / "tiktok"
    Returns: {"platform": ..., "video_id": ..., "url": ..., "manual": bool}
    """
    if platform not in ("youtube", "instagram", "tiktok"):
        raise ValueError(f"unknown platform: {platform}")

    ts_path = os.path.join(config.TEMP_DIR, ts)
    if not os.path.isdir(ts_path):
        raise FileNotFoundError(f"project not found: temp/{ts}")

    if not progress_store.is_approved(ts_path, "final_import"):
        raise RuntimeError(
            "Stage 8 (final_import) が未承認のため公開できません — "
            "UI または `--canonical` で承認してください",
        )

    video = resolve_canonical_video(ts_path)
    title, description, tags = read_post_caption_for_ts(ts)
    logger.info(
        "[Stage 9] %s 公開準備: video=%s, title=%r, tags=%s",
        platform, video.name, title[:30], tags[:5],
    )

    if platform == "youtube":
        result = _publish_youtube(ts, video, title, description, tags, **opts)
    elif platform == "instagram":
        result = _publish_semi_auto(
            "instagram", ts, video, title, description, tags,
        )
    else:
        result = _publish_semi_auto(
            "tiktok", ts, video, title, description, tags,
        )

    _record_publish(ts_path, result)
    return result


def _publish_youtube(ts: str, video: Path, title: str, description: str,
                     tags: list[str], privacy: str = "private",
                     is_short: bool = True, **_opts) -> dict:
    from platform_clients import youtube
    from analytics import db as analytics_db

    upload = youtube.upload_video(
        file_path=video, title=title, description=description,
        tags=tags, privacy=privacy, is_short=is_short,
    )

    try:
        analytics_db.init_db()
        _ensure_video_in_analytics(ts, video)
        analytics_db.register_post(
            video_id=ts, platform="youtube",
            platform_post_id=upload["video_id"],
            url=upload["url"],
            posted_at=datetime.now().isoformat(timespec="seconds"),
            caption=description,
            hashtags=tags,
        )
    except Exception as e:
        logger.warning("analytics register_post 失敗 (公開自体は成功): %s", e)

    return {
        "platform": "youtube",
        "video_id": upload["video_id"],
        "url": upload["url"],
        "privacy": privacy,
        "manual": False,
    }


def _ensure_video_in_analytics(ts: str, video: Path) -> None:
    """publish 前に screenplay と video を analytics DB に登録する。

    既に登録済みなら upsert で no-op。CapCut で取り込んだ canonical final
    を analytics の output_path として記録する。
    """
    from analytics import db as analytics_db
    ts_path = os.path.join(config.TEMP_DIR, ts)

    with analytics_db.get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM videos WHERE id = ?", (ts,),
        ).fetchone()
    if existing:
        return

    snap_path = os.path.join(ts_path, "screenplay.json")
    if not os.path.exists(snap_path):
        raise RuntimeError(f"screenplay snapshot not found: {snap_path}")
    sp_id = analytics_db.upsert_screenplay(snap_path)

    meta = staged_pipeline.read_metadata(ts_path) or {}
    final_meta = next(
        (v for v in (meta.get("final_versions") or []) if v.get("is_canonical")),
        None,
    )
    duration = float(final_meta["duration_sec"]) if (
        final_meta and final_meta.get("duration_sec")
    ) else None
    score = float(final_meta["audio_match_score"]) if (
        final_meta and final_meta.get("audio_match_score") is not None
    ) else None

    analytics_db.insert_video(
        video_id=ts, screenplay_id=sp_id,
        output_path=str(video), duration_sec=duration,
        final_imported=bool(final_meta),
        final_filename=final_meta["filename"] if final_meta else None,
        final_audio_match_score=score,
    )


def _publish_semi_auto(platform: str, ts: str, video: Path, title: str,
                       description: str, tags: list[str]) -> dict:
    """ファイル + caption をクリップボードに置いてアプリを開く Phase 1 暫定。

    macOS では:
      1. caption をクリップボードへ pbcopy
      2. アプリ (Instagram.app / TikTok.app) を `open -a` で起動 (無ければ Finder reveal)

    成功 URL はユーザに後で `--register-post` で投入してもらう。
    """
    full_caption = description if title in description else f"{title}\n\n{description}".strip()

    if sys.platform == "darwin":
        try:
            subprocess.run(
                ["pbcopy"], input=full_caption.encode("utf-8"), check=True,
            )
        except Exception as e:
            logger.warning("pbcopy 失敗: %s", e)

        app = {"instagram": "Instagram", "tiktok": "TikTok"}.get(platform)
        opened = False
        if app:
            try:
                subprocess.run(
                    ["open", "-a", app, str(video)],
                    check=False, capture_output=True,
                )
                opened = True
            except Exception:
                opened = False
        if not opened:
            subprocess.run(["open", "-R", str(video)], check=False)
    else:
        logger.info("non-darwin: 自動でアプリを開けません — caption を以下にコピーしてください:")
        logger.info("---\n%s\n---", full_caption)

    logger.info(
        "[Stage 9 %s] caption をクリップボードへ + 動画を開きました — "
        "アプリ側でアップロード完了後、URL を register_post で登録してください",
        platform,
    )

    return {
        "platform": platform,
        "video_id": None,
        "url": None,
        "video_path": str(video),
        "caption": full_caption,
        "manual": True,
    }


def _record_publish(ts_path: str, result: dict) -> None:
    """metadata.json の published_posts に追記し、Stage 9 を generated に。"""
    meta = staged_pipeline.read_metadata(ts_path) or {}
    posts = meta.get("published_posts") or []
    posts.append({
        "platform": result["platform"],
        "video_id": result.get("video_id"),
        "url": result.get("url"),
        "manual": bool(result.get("manual")),
        "published_at": datetime.now().isoformat(timespec="seconds"),
    })
    meta["published_posts"] = posts
    p = os.path.join(ts_path, "metadata.json")
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)

    if not progress_store.is_generated(ts_path, "publish"):
        progress_store.mark_generated(ts_path, "publish")


def read_post_caption_for_ts(ts: str) -> tuple[str, str, list[str]]:
    """`post_captions/<title>.md` を解析、無ければ screenplay.caption から組み立てる。

    Returns: (title, description, tags)
    """
    ts_path = os.path.join(config.TEMP_DIR, ts)
    meta = staged_pipeline.read_metadata(ts_path) or {}
    name = meta.get("screenplay_name") or meta.get("screenplay_template_name") or ""
    title_base = os.path.splitext(name)[0]

    if title_base:
        md_path = os.path.join(config.POST_CAPTIONS_DIR, f"{title_base}.md")
        if os.path.exists(md_path):
            with open(md_path, "r", encoding="utf-8") as f:
                return parse_caption_md(f.read())

    try:
        sp = staged_pipeline.load_project_screenplay(ts_path)
    except Exception:
        sp = {}
    caption = (sp.get("caption") or "").strip()
    return parse_caption_md(f"# {title_base}\n\n{caption}\n")


def parse_caption_md(content: str) -> tuple[str, str, list[str]]:
    """post_captions のフォーマットを title / description / tags に分解。

    フォーマット:
        # title 行
        <空行>
        本文 (caption + ハッシュタグを含む)
        <空行>
        ## 動画ファイル   ← ここから先は無視 (system section)
        ...
    """
    title = ""
    body_parts: list[str] = []
    in_body = False
    for line in content.splitlines():
        if not title and line.startswith("# ") and not line.startswith("## "):
            title = line[2:].strip()
            in_body = True
            continue
        if line.startswith("## "):
            break
        if in_body:
            body_parts.append(line)

    description = "\n".join(body_parts).strip()
    tags: list[str] = []
    seen: set[str] = set()
    for tag in _HASHTAG_RE.findall(description):
        clean = tag.strip()
        if clean and clean not in seen:
            tags.append(clean)
            seen.add(clean)
    return title or "untitled", description, tags
