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

    # 半自動経路で「app 起動も Finder reveal も失敗」かつ「クリップボードも失敗」
    # = ユーザに何も渡せていない → 履歴に残さず例外で job failure
    if result.get("manual"):
        ms = result.get("manual_status") or {}
        if not (ms.get("app_opened") or ms.get("finder_revealed")
                or ms.get("clipboard")):
            raise RuntimeError(
                f"Stage 9 {platform}: アプリ起動 / Finder reveal / クリップボード "
                f"のすべてが失敗しました。手動で動画 ({video}) を開いてください — "
                f"diagnostics: {ms.get('diagnostics')}",
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
      1. caption をクリップボードへ ``pbcopy``
      2. アプリ (Instagram.app / TikTok.app) を ``open -a`` で起動。失敗
         (アプリ未インストール / Gatekeeper 拒否 等) なら ``open -R`` で
         Finder reveal にフォールバック
      3. すべての失敗を caller に返す ``manual_status`` で記録 (= 完全失敗時
         でも job は failure にせず、ユーザが手動で続行できる状態を残す)

    各 subprocess は returncode を必ずチェックする (silent success は禁止)。
    """
    full_caption = (
        description if title in description
        else f"{title}\n\n{description}".strip()
    )

    clipboard_ok = False
    app_opened = False
    finder_revealed = False
    diagnostics: list[str] = []

    if sys.platform == "darwin":
        clipboard_ok, msg = _run_pbcopy(full_caption)
        if not clipboard_ok and msg:
            diagnostics.append(msg)

        app_name = {"instagram": "Instagram", "tiktok": "TikTok"}.get(platform)
        if app_name:
            app_opened, msg = _run_open_app(app_name, video)
            if not app_opened and msg:
                diagnostics.append(msg)

        if not app_opened:
            finder_revealed, msg = _run_finder_reveal(video)
            if not finder_revealed and msg:
                diagnostics.append(msg)
    else:
        logger.info(
            "non-darwin: 自動でアプリを開けません — 以下の caption を手動コピーしてください:",
        )
        logger.info("---\n%s\n---", full_caption)

    if sys.platform == "darwin" and not (app_opened or finder_revealed):
        logger.warning(
            "[Stage 9 %s] アプリ起動 / Finder reveal の両方が失敗 — "
            "ユーザが手動で動画ファイルを開く必要があります: %s",
            platform, video,
        )
    else:
        logger.info(
            "[Stage 9 %s] caption=%s, app_opened=%s, finder=%s — "
            "アプリ側でアップロード完了後、URL を register_post で登録してください",
            platform, "OK" if clipboard_ok else "FAIL",
            app_opened, finder_revealed,
        )

    return {
        "platform": platform,
        "video_id": None,
        "url": None,
        "video_path": str(video),
        "caption": full_caption,
        "manual": True,
        "manual_status": {
            "clipboard": clipboard_ok,
            "app_opened": app_opened,
            "finder_revealed": finder_revealed,
            "diagnostics": diagnostics,
        },
    }


def _run_pbcopy(text: str) -> tuple[bool, str | None]:
    try:
        r = subprocess.run(
            ["pbcopy"], input=text.encode("utf-8"),
            check=False, capture_output=True, timeout=10,
        )
        if r.returncode == 0:
            return True, None
        err = r.stderr.decode("utf-8", errors="replace")[:200]
        msg = f"pbcopy returncode={r.returncode} stderr={err!r}"
        logger.warning(msg)
        return False, msg
    except (subprocess.TimeoutExpired, OSError) as e:
        msg = f"pbcopy 例外: {e}"
        logger.warning(msg)
        return False, msg


def _run_open_app(app_name: str, video: Path) -> tuple[bool, str | None]:
    try:
        r = subprocess.run(
            ["open", "-a", app_name, str(video)],
            check=False, capture_output=True, timeout=15,
        )
        if r.returncode == 0:
            return True, None
        err = r.stderr.decode("utf-8", errors="replace")[:300]
        msg = (f"`open -a {app_name}` returncode={r.returncode} stderr={err!r} — "
               "Finder reveal にフォールバック")
        logger.info(msg)
        return False, msg
    except (subprocess.TimeoutExpired, OSError) as e:
        msg = f"open -a {app_name} 例外: {e} — Finder reveal にフォールバック"
        logger.info(msg)
        return False, msg


def _run_finder_reveal(video: Path) -> tuple[bool, str | None]:
    try:
        r = subprocess.run(
            ["open", "-R", str(video)],
            check=False, capture_output=True, timeout=10,
        )
        if r.returncode == 0:
            return True, None
        err = r.stderr.decode("utf-8", errors="replace")[:200]
        msg = f"`open -R` returncode={r.returncode} stderr={err!r}"
        logger.warning(msg)
        return False, msg
    except (subprocess.TimeoutExpired, OSError) as e:
        msg = f"open -R 例外: {e}"
        logger.warning(msg)
        return False, msg


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
