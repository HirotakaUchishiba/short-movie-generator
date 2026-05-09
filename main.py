#!/usr/bin/env python3
import argparse
import logging
import os
import sys
from datetime import datetime

import config
import log_setup
import progress_store
import staged_pipeline

log_setup.setup()
logger = logging.getLogger(__name__)


def _is_truthy(value: str | None) -> bool:
    """env の値を寛容に真偽判定する (= "1"/"true"/"True"/"yes" を真)。

    config 層の ``AUTO_LOOP_ALLOW_PUBLIC`` 等と同じ受け入れ集合を使うことで、
    運用者が env を設定するときの食い違いを防ぐ。
    """
    if value is None:
        return False
    return value.strip().lower() in ("1", "true", "yes")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="main.py",
        description="段階的ゲート方式の動画パイプライン CLI",
    )
    p.add_argument("screenplay_name", nargs="?",
                   help="台本ファイル名 (拡張子省略可)")
    p.add_argument("--resume", dest="resume_ts", metavar="TS",
                   help="既存 TS の次 stage を実行")

    g = p.add_argument_group("取込 / 公開")
    g.add_argument("--list-finals", dest="list_finals", action="store_true",
                   help="このプロジェクトの final 取込履歴を表示")
    g.add_argument("--canonical", metavar="FILENAME",
                   help="--list-finals の中から canonical を切替える")
    g.add_argument("--publish", choices=["youtube", "instagram", "tiktok"],
                   help="canonical な final をプラットフォームに公開")
    g.add_argument("--privacy", choices=["private", "unlisted", "public"],
                   default="private",
                   help="--publish youtube の公開範囲 (既定: private)")
    g.add_argument("--force-republish", action="store_true",
                   help="既存の成功済み投稿があっても再投稿する "
                        "(= 二重 upload ガードを bypass)")
    g.add_argument("--channel", metavar="PROFILE",
                   help="--publish youtube の投稿先チャンネル profile (= "
                        "YOUTUBE_PROFILE 環境変数を override する。"
                        ".env で YOUTUBE_OAUTH_CLIENT_ID_<PROFILE> 等の "
                        "suffix 付き env を別途用意する必要あり)")
    g.add_argument("--yes", "-y", dest="yes", action="store_true",
                   help="--publish 実行時の channel guard 確認プロンプトを skip")
    return p


def _print_screenplays() -> None:
    if not os.path.isdir(config.SCREENPLAYS_DIR):
        return
    names = sorted(f for f in os.listdir(config.SCREENPLAYS_DIR) if f.endswith(".json"))
    if names:
        print(f"\n台本ディレクトリ: {config.SCREENPLAYS_DIR}")
        print("利用可能な台本:")
        for n in names:
            print(f"  - {n}")


def main() -> None:
    # フルオート量産経路の kill-switch (Phase 1+ で使う)。
    # cron / auto_loop が main.py を subprocess 起動するので、env を 1 にすると
    # 全自動レーンが即停止する。手動運用 (= 直接実行) では env を立てなければ
    # 無視される (= 退路を必ず残す原則)。
    # env の真偽値解釈は config.AUTO_LOOP_ALLOW_PUBLIC と統一 (= 1/true/True/yes)。
    if _is_truthy(os.environ.get("DISABLE_AUTO_LOOP")):
        logger.error(
            "DISABLE_AUTO_LOOP=%s: auto-loop kill-switch が有効です。"
            "手動運用を再開するには env を unset してください。",
            os.environ.get("DISABLE_AUTO_LOOP"),
        )
        sys.exit(2)

    parser = _build_parser()
    args = parser.parse_args()

    if args.list_finals or args.canonical or args.publish:
        ts = args.resume_ts
        if not ts:
            parser.error("--list-finals / --canonical / --publish には "
                         "--resume <TS> が必要です")
        return _run_stage8_9(args, ts)

    if not args.screenplay_name:
        parser.print_help()
        _print_screenplays()
        sys.exit(1)

    _run_pipeline(args.screenplay_name, args.resume_ts)


def _run_pipeline(screenplay_name: str, resume_ts: str | None) -> None:
    ts = resume_ts or datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(config.TEMP_DIR, exist_ok=True)
    ts_path = os.path.join(config.TEMP_DIR, ts)
    os.makedirs(ts_path, exist_ok=True)

    # Stage 1 が既に走っていれば project snapshot を SSOT として読む
    # (= UI 編集や analyze 由来 compose 結果を CLI からも反映)。
    # 未実行なら template から立ち上げる (= 新規 project / Stage 1 起動経路)。
    if progress_store.is_generated(ts_path, "script"):
        screenplay = staged_pipeline.load_project_screenplay(ts_path)
        logger.info("台本: %s (snapshot) | TS: %s", screenplay_name, ts)
    else:
        screenplay = staged_pipeline.load_template(screenplay_name)
        logger.info("台本: %s (template) | TS: %s", screenplay_name, ts)

    nxt = progress_store.next_stage(ts_path)
    cur = progress_store.current_stage(ts_path)

    if nxt is None:
        if cur is None:
            logger.info("全stage完了済み — 何もすることがありません")
            return
        if cur in progress_store.EXTERNAL_ACTION_STAGES:
            logger.info(
                "stage '%s' は manual main.py の対象外です — "
                "Stage 7 (取込) は `scripts/auto_loop.py` 経由で実行されます。"
                "Stage 8 (公開) は `--publish` を使ってください",
                cur,
            )
            return
        logger.info(
            "stage '%s' は生成済みですが未承認です。"
            "プレビューUIで承認してください: %s",
            cur, _ui_url(ts),
        )
        return

    if nxt in progress_store.EXTERNAL_ACTION_STAGES:
        logger.info(
            "次 stage '%s' は manual main.py の対象外です — "
            "Stage 7 (取込) は `scripts/auto_loop.py` 経由で実行されます。"
            "Stage 8 (公開) は `--publish` を使ってください",
            nxt,
        )
        return

    logger.info("実行stage: %s", nxt)
    try:
        executed = staged_pipeline.run_next_stage(screenplay, screenplay_name, ts_path)
    except Exception as e:
        logger.exception("stage実行エラー: %s", e)
        sys.exit(1)

    if executed == "overlay":
        logger.info(
            "字幕焼き込み + pipeline raw 出力完了 (= manual main.py はここまで)。"
            "Stage 7 以降は `scripts/auto_loop.py` 経由でのみ進行します。"
            "プレビューUIで確認: %s",
            _ui_url(ts),
        )
    else:
        logger.info(
            "stage '%s' 生成完了。プレビューUIで確認・承認してください: %s",
            executed, _ui_url(ts),
        )
        logger.info("承認後 `python main.py %s --resume %s` で次stage実行",
                    screenplay_name, ts)


def _run_stage8_9(args: argparse.Namespace, ts: str) -> None:
    import final_import
    ts_path = os.path.join(config.TEMP_DIR, ts)
    if not os.path.isdir(ts_path):
        logger.error("プロジェクトが見つかりません: %s", ts_path)
        sys.exit(1)

    if args.list_finals or args.canonical:
        if args.canonical:
            try:
                v = final_import.set_canonical_final(ts_path, args.canonical)
            except ValueError as e:
                logger.error(str(e))
                sys.exit(1)
            logger.info("canonical 切替: %s", v.filename)
        versions = final_import.list_final_versions(ts_path)
        if not versions:
            logger.info("final バージョンはまだありません")
            return
        for v in versions:
            mark = "★" if v.is_canonical else " "
            score = f"{v.audio_match_score:.2f}" if v.audio_match_score is not None else "-"
            print(
                f"{mark} {v.filename}  imported_at={v.imported_at}  "
                f"size={v.size_bytes}  duration={v.duration_sec or 0:.1f}s  "
                f"score={score}  source={v.source}",
            )
        return

    if args.publish:
        if args.channel:
            os.environ["YOUTUBE_PROFILE"] = args.channel.upper()
        from final_import.publish import publish
        try:
            result = publish(
                ts, args.publish,
                privacy=args.privacy,
                force_republish=args.force_republish,
                confirm_channel=(args.publish == "youtube" and not args.yes),
            )
        except Exception as e:
            logger.exception("公開失敗: %s", e)
            sys.exit(1)
        if result.get("skipped"):
            logger.info(
                "[公開] %s は既に成功済みのため skip しました: %s",
                args.publish, result.get("url") or "",
            )
        else:
            logger.info("[公開] 完了: %s %s", args.publish, result.get("url") or "")


def _ui_url(ts: str) -> str:
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = int(os.environ.get("PREVIEW_PORT", "5555"))
    return f"http://{host}:{port}/project/{ts}"


if __name__ == "__main__":
    main()
