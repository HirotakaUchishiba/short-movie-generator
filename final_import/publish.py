"""Stage 8: canonical な final 動画をプラットフォームに公開する。

YouTube は Data API resumable upload で完全自動。Instagram / TikTok は
Phase 1 までは半自動 (= caption をクリップボードにコピー + アプリ起動 +
動画ファイルを Finder で reveal)。公開成功後は analytics DB の posts
テーブルにも書き込み、register_post を別途叩かなくて良いようにする。
"""

import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import config
import io_utils
import preflight
import progress_store
import project_state
import staged_pipeline

from .core import resolve_canonical_video

logger = logging.getLogger(__name__)

_HASHTAG_RE = re.compile(r"#([^\s#]+)")


def _confirm_publish_channel(skip: bool) -> None:
    """publish 直前に投稿先 YouTube チャンネル情報を表示し、ユーザー確認を取る。

    ``skip=True`` (= ``--yes`` 指定 / 非対話呼び出し) なら何もしない。
    stdin が tty じゃない (= cron / launchd / subprocess) のに skip 指定が
    無いとエラーにする (= 確認不能のまま進めない)。
    """
    if skip:
        return

    from platform_clients import youtube as _yt
    info = _yt._resolve_channel_label()

    print("[公開] 投稿先チャンネル:", file=sys.stderr)
    print(f"  profile     : {info.get('profile')}", file=sys.stderr)
    if info.get("title") and info.get("channel_id"):
        print(
            f"  channel     : {info['title']} ({info['channel_id']})",
            file=sys.stderr,
        )
    if info.get("aud"):
        print(f"  client_id   : {info['aud']}", file=sys.stderr)
    if "scopes" in info:
        print(f"  scopes      : {info['scopes']}", file=sys.stderr)
    if info.get("error"):
        print(f"  error       : {info['error']}", file=sys.stderr)
    if not (info.get("title") and info.get("channel_id")):
        print(
            "  ※ チャンネル名取得には refresh_token に "
            "youtube.readonly scope が必要 (= 上の client_id だけは確認可)",
            file=sys.stderr,
        )

    if not sys.stdin.isatty():
        raise RuntimeError(
            "[公開] stdin が tty ではないため確認できません — "
            "自動実行から呼ぶ場合は confirm_channel=False (CLI なら --yes) を指定",
        )

    ans = input("[公開] 続行しますか? [y/N]: ").strip().lower()
    if ans not in ("y", "yes"):
        raise SystemExit("[公開] ユーザーキャンセル")


def publish(ts: str, platform: str, **opts) -> dict:
    """canonical な final を指定 platform に公開し、analytics DB に登録する。

    platform: "youtube" / "instagram" / "tiktok"

    YouTube は **idempotent** で、同じプロジェクトに対して既に成功済みの
    YouTube 投稿があれば 2 回目以降は skip して既存エントリを返す
    (= 二重 upload の事故防止)。明示的に再投稿したい場合は
    ``force_republish=True`` を渡す。canonical を切替えると
    ``set_canonical_final`` が publish 承認を wipe するため、別動画には自動で
    再公開可能。

    Instagram / TikTok は半自動 (= アプリ起動 + クリップボード) なので、ボタン
    連打や再試行に意味がある。idempotent ガードは適用しない。

    Returns: {"platform": ..., "video_id": ..., "url": ..., "manual": bool,
              "skipped": bool (再投稿スキップ時のみ True)}
    """
    if platform not in ("youtube", "instagram", "tiktok"):
        raise ValueError(f"unknown platform: {platform}")

    ts_path = os.path.join(config.TEMP_DIR, ts)
    if not os.path.isdir(ts_path):
        raise FileNotFoundError(f"project not found: temp/{ts}")

    if not progress_store.is_approved(ts_path, "final_import"):
        raise RuntimeError(
            "取込 が未承認のため公開できません — "
            "UI または `--canonical` で承認してください",
        )

    force_republish = bool(opts.pop("force_republish", False))
    confirm_channel = bool(opts.pop("confirm_channel", False))
    existing = _existing_successful_publish(ts_path, platform)
    if existing and not force_republish:
        logger.warning(
            "[公開] %s に既に成功済みの投稿があります (video_id=%s, url=%s) — "
            "skip します。再投稿するなら force_republish=True を指定してください",
            platform, existing.get("video_id"), existing.get("url"),
        )
        return {
            "platform": platform,
            "video_id": existing.get("video_id"),
            "url": existing.get("url"),
            "manual": bool(existing.get("manual", False)),
            "skipped": True,
        }

    video = resolve_canonical_video(ts_path)
    title, description, tags = read_post_caption_for_ts(ts)
    logger.info(
        "[公開] %s 準備: video=%s, title=%r, tags=%s",
        platform, video.name, title[:30], tags[:5],
    )

    if platform == "youtube":
        _confirm_publish_channel(skip=not confirm_channel)
        preflight.check_publish_youtube()
        result = _publish_youtube(ts, video, title, description, tags, **opts)
    elif platform == "instagram":
        if _is_api_mode("INSTAGRAM_PUBLISH_MODE"):
            result = _publish_instagram_api(
                ts, video, title, description, tags,
            )
        else:
            preflight.check_publish_instagram()
            result = _publish_semi_auto(
                "instagram", ts, video, title, description, tags,
            )
    else:
        if _is_api_mode("TIKTOK_PUBLISH_MODE"):
            raise NotImplementedError(
                "TIKTOK_PUBLISH_MODE=api は未実装 (= scope 申請後に "
                "platform_clients/tiktok.py:upload_video を有効化)",
            )
        preflight.check_publish_tiktok()
        result = _publish_semi_auto(
            "tiktok", ts, video, title, description, tags,
        )

    # 半自動経路で「app 起動も Finder reveal も失敗」かつ「クリップボードも失敗」
    # = ユーザに何も渡せていない → failed フラグを立てて履歴に残し、例外で job failure
    if result.get("manual"):
        ms = result.get("manual_status") or {}
        if not (ms.get("app_opened") or ms.get("finder_revealed")
                or ms.get("clipboard")):
            reason = (
                f"アプリ起動 / Finder reveal / クリップボード のすべてが失敗 — "
                f"diagnostics: {ms.get('diagnostics')}"
            )
            result["failed"] = True
            result["failure_reason"] = reason
            _record_publish(ts_path, result)
            raise RuntimeError(
                f"公開 {platform}: {reason}。手動で動画 ({video}) を開いてください",
            )

    _record_publish(ts_path, result)
    return result


def _is_api_mode(env_key: str) -> bool:
    """``<PLATFORM>_PUBLISH_MODE=api`` のとき True。既定は ``semi`` (= 半自動)。"""
    return (os.getenv(env_key) or "semi").strip().lower() == "api"


def _publish_instagram_api(ts: str, video: Path, title: str, description: str,
                           tags: list[str]) -> dict:
    """IG Graph API 経由で Reels を公開する (= mode=api)。"""
    from platform_clients import instagram

    caption = description if description else title
    if tags:
        hashtag_block = " ".join(f"#{t}" for t in tags if t)
        caption = f"{caption}\n\n{hashtag_block}".strip()

    upload = instagram.upload_video(file_path=video, caption=caption)

    posted_at = datetime.now().isoformat(timespec="seconds")
    analytics_result = _record_analytics(
        ts=ts, video=video,
        platform_post_id=upload["video_id"],
        url=upload["url"],
        posted_at=posted_at,
        caption=caption,
        hashtags=tags,
        platform="instagram",
    )

    return {
        "platform": "instagram",
        "video_id": upload["video_id"],
        "url": upload["url"],
        "privacy": "public",  # IG は publish 時に privacy を選べない
        "is_short": True,
        "posted_at": posted_at,
        "analytics_persisted": analytics_result["persisted"],
        "analytics_warning": analytics_result.get("error"),
        "raw_response": upload.get("raw_response"),
    }


def _publish_youtube(ts: str, video: Path, title: str, description: str,
                     tags: list[str], privacy: str = "private",
                     is_short: bool = True, **_opts) -> dict:
    from platform_clients import youtube
    import config as _cfg

    state_path = Path(_cfg.TEMP_DIR) / ts / "upload_state_youtube.json"
    upload = youtube.upload_video(
        file_path=video, title=title, description=description,
        tags=tags, privacy=privacy, is_short=is_short,
        state_path=state_path,
    )

    posted_at = datetime.now().isoformat(timespec="seconds")
    analytics_result = _record_analytics(
        ts=ts, video=video,
        platform_post_id=upload["video_id"],
        url=upload["url"],
        posted_at=posted_at,
        caption=description,
        hashtags=tags,
    )

    return {
        "platform": "youtube",
        "video_id": upload["video_id"],
        "url": upload["url"],
        "privacy": privacy,
        "manual": False,
        "analytics_persisted": analytics_result["persisted"],
        "analytics_warning": analytics_result.get("error"),
    }


def _record_analytics(*, ts: str, video: Path, platform_post_id: str,
                      url: str, posted_at: str, caption: str,
                      hashtags: list[str],
                      platform: str = "youtube") -> dict[str, str | bool]:
    """analytics DB に register_post を試みる。SQLite の WAL + busy_timeout=5000
    に内蔵 retry を任せ、アプリ層では 1 回試行のみ。成功で
    ``{"persisted": True}``、失敗で ``{"persisted": False, "error": <str>}``。

    publish (= YouTube/IG/TikTok アップロード) は既に成功しているため、ここでの
    DB 登録失敗は publish 自体を fail にしない。caller は
    ``analytics_persisted`` を ``_record_publish`` 経由で metadata に残し、
    Stage 8 は通常通り mark_generated する。失敗時は loud error log で運用者に
    通知し、復旧は ``scripts/register_post.py`` で手動実施する。
    """
    from analytics import db as analytics_db

    try:
        analytics_db.init_db()
        _ensure_video_in_analytics(ts, video)
        analytics_db.register_post(
            video_id=ts, platform=platform,
            platform_post_id=platform_post_id,
            url=url, posted_at=posted_at,
            caption=caption, hashtags=hashtags,
        )
        return {"persisted": True}
    except Exception as e:
        logger.error(
            "[analytics] DB 登録失敗 — publish 自体は成功しています "
            "(platform=%s, video_id=%s, url=%s)。手動復旧: "
            "`python3 scripts/register_post.py %s %s %s` — エラー詳細: %s",
            platform, ts, url, ts, platform, url, e,
            exc_info=True,
        )
        return {"persisted": False, "error": str(e)}


def _ensure_video_in_analytics(ts: str, video: Path) -> None:
    """publish 前に screenplay と video を analytics DB に登録 / 最新化する。

    既に raw で ingest 済みの行があれば、`output_path` / `duration_sec` /
    `final_imported` / `final_filename` / `final_audio_match_score` を
    canonical final の値で UPDATE する (= screenplay_id / generation_cost_usd
    は保持)。新規なら insert する。
    """
    from analytics import db as analytics_db
    ts_path = os.path.join(config.TEMP_DIR, ts)

    meta = project_state.read_metadata(ts_path) or {}
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

    with analytics_db.get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM videos WHERE id = ?", (ts,),
        ).fetchone()

    if existing:
        analytics_db.update_video_final(
            video_id=ts,
            output_path=str(video),
            duration_sec=duration,
            final_imported=bool(final_meta),
            final_filename=final_meta["filename"] if final_meta else None,
            final_audio_match_score=score,
        )
        return

    snap_path = os.path.join(ts_path, "screenplay.json")
    if not os.path.exists(snap_path):
        raise RuntimeError(f"screenplay snapshot not found: {snap_path}")
    sp_id = analytics_db.upsert_screenplay(snap_path)

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
            "[公開 %s] アプリ起動 / Finder reveal の両方が失敗 — "
            "ユーザが手動で動画ファイルを開く必要があります: %s",
            platform, video,
        )
    else:
        logger.info(
            "[公開 %s] caption=%s, app_opened=%s, finder=%s — "
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
    """metadata.json の published_posts に追記し、Stage 8 を generated に。

    同じ ``(platform, video_id)`` の既存エントリがあれば、その場で update する
    (= 重複防止)。video_id が None (= 半自動) の場合は ``(platform, "manual")``
    を判定キーとし、再試行 / 失敗の上書きが同一スロットになるようにする。

    publish アップロード成功なら Stage 8 を即時 ``mark_generated`` する。
    analytics DB 登録だけ失敗した場合 (= ``analytics_persisted=False``) でも
    動画は世界に出ているため、Stage 8 完了は維持する (= 再 publish で重複動画を
    生まないため)。失敗時の運用復旧は ``scripts/register_post.py`` で行う。
    """
    meta = project_state.read_metadata(ts_path) or {}
    posts = list(meta.get("published_posts") or [])
    failed = bool(result.get("failed"))
    analytics_persisted = result.get("analytics_persisted", True)
    entry = {
        "platform": result["platform"],
        "video_id": result.get("video_id"),
        "url": result.get("url"),
        "manual": bool(result.get("manual")),
        "published_at": datetime.now().isoformat(timespec="seconds"),
        "failed": failed,
        "analytics_persisted": analytics_persisted,
    }
    if not analytics_persisted and result.get("analytics_warning"):
        entry["analytics_warning"] = result["analytics_warning"]
    if failed and result.get("failure_reason"):
        entry["failure_reason"] = result["failure_reason"]

    key = _dedup_key(entry)
    replaced = False
    for i, existing in enumerate(posts):
        if _dedup_key(existing) == key:
            posts[i] = entry
            replaced = True
            break
    if not replaced:
        posts.append(entry)
    meta["published_posts"] = posts
    io_utils.atomic_write_json(os.path.join(ts_path, "metadata.json"), meta)

    if failed:
        return
    if not progress_store.is_generated(ts_path, "publish"):
        progress_store.mark_generated(ts_path, "publish")


def _dedup_key(entry: dict) -> tuple[str, str]:
    vid = entry.get("video_id") or "manual"
    return (entry.get("platform") or "", str(vid))


# Idempotent re-publish guard 対象 platform。半自動 (manual=True) の IG/TikTok は
# ボタン連打 / 再試行に意味があるので除外する。
_IDEMPOTENT_PLATFORMS = frozenset({"youtube"})


def _existing_successful_publish(ts_path: str, platform: str) -> dict | None:
    """metadata.published_posts[] から「同 platform で成功済み」の entry を返す。

    成功 = ``failed`` が False (or 未指定) かつ ``video_id`` が立っている
    (= 半自動 manual: True かつ video_id=None は対象外)。
    """
    if platform not in _IDEMPOTENT_PLATFORMS:
        return None
    meta = project_state.read_metadata(ts_path) or {}
    for entry in meta.get("published_posts") or []:
        if (entry.get("platform") == platform
                and not entry.get("failed")
                and entry.get("video_id")):
            return entry
    return None


def read_post_caption_for_ts(ts: str) -> tuple[str, str, list[str]]:
    """`post_captions/<title>.md` を解析、無ければ screenplay.caption から組み立てる。

    Returns: (title, description, tags)
    """
    ts_path = os.path.join(config.TEMP_DIR, ts)
    meta = project_state.read_metadata(ts_path) or {}
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
