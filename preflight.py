"""各 stage を実行する前に必要な env / 依存ファイルが揃っているかを検査する。

外部 API 呼び出しを試みてから「key 未設定」で落ちると、API 通信が始まる
までの数秒〜数十秒は無駄なログが流れる。preflight でいったん検査して
不備があれば即座に明確なエラーで止める。
"""

import os
import logging
import shutil

import config

logger = logging.getLogger(__name__)

# 各 stage で必要となる空き容量の下限 (= 1 シーン分の生成物 + 安全マージン)。
# bg / kling / scene / overlay は分量が大きいので 1GB を、tts / 取込は軽いので
# 256MB を下限とする。env ``PREFLIGHT_MIN_FREE_BYTES`` で上書き可能。
_DEFAULT_MIN_FREE_BYTES_BIG = 1 * 1024 * 1024 * 1024     # 1 GB
_DEFAULT_MIN_FREE_BYTES_SMALL = 256 * 1024 * 1024        # 256 MB


class PreflightError(RuntimeError):
    """前提条件が満たされていないため stage を起動できない。"""


def _missing(*envs: str) -> list[str]:
    return [e for e in envs if not os.environ.get(e)]


def _min_free_bytes(default: int) -> int:
    raw = os.environ.get("PREFLIGHT_MIN_FREE_BYTES")
    if raw:
        try:
            v = int(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    return default


def check_disk_space(min_free_bytes: int) -> None:
    """``config.TEMP_DIR`` 配下に最低限の空き容量があることを確認。

    API 課金が発生する stage の直前で空きを確認することで、
    ENOSPC で書き込みに失敗して課金が無駄になるのを避ける。
    """
    target = config.TEMP_DIR
    parent = os.path.dirname(os.path.abspath(target)) or "/"
    probe = target if os.path.isdir(target) else parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError as e:
        logger.warning("[preflight] disk_usage 取得失敗 — skip: %s", e)
        return
    if usage.free < min_free_bytes:
        free_mb = usage.free / (1024 * 1024)
        need_mb = min_free_bytes / (1024 * 1024)
        raise PreflightError(
            f"{probe} の空き容量が不足: {free_mb:.0f}MB "
            f"(必要 {need_mb:.0f}MB 以上)。temp/ 配下を整理してから再実行してください。"
        )


def check_tts() -> None:
    if not config.ELEVENLABS_API_KEY:
        raise PreflightError(
            "ELEVENLABS_API_KEY 未設定 — Stage 2 (TTS) を実行できません。"
            ".env に ELEVENLABS_API_KEY=<key> を追加してください。"
        )
    check_disk_space(_min_free_bytes(_DEFAULT_MIN_FREE_BYTES_SMALL))


def check_bg() -> None:
    if not config.GOOGLE_API_KEY:
        raise PreflightError(
            "GOOGLE_API_KEY 未設定 — Stage 3 (背景画像) を実行できません。"
            ".env に GOOGLE_API_KEY=<key> を追加してください。"
        )
    check_disk_space(_min_free_bytes(_DEFAULT_MIN_FREE_BYTES_BIG))


def check_kling() -> None:
    if not config.FAL_API_KEY:
        raise PreflightError(
            "FAL_KEY 未設定 — Stage 4 (Kling) を実行できません。"
            ".env に FAL_KEY=<key> を追加してください。"
        )
    check_disk_space(_min_free_bytes(_DEFAULT_MIN_FREE_BYTES_BIG))


def check_scene() -> None:
    """Stage 5: Sync.so lipsync の key を検査。"""
    if not getattr(config, "LIPSYNC_ENABLED", True):
        check_disk_space(_min_free_bytes(_DEFAULT_MIN_FREE_BYTES_BIG))
        return
    if not config.SYNCSO_API_KEY:
        raise PreflightError(
            "SYNC_API_KEY 未設定 — Sync.so lipsync を実行できません。"
            ".env に SYNC_API_KEY=<key> を追加してください。"
        )
    check_disk_space(_min_free_bytes(_DEFAULT_MIN_FREE_BYTES_BIG))


def check_publish_youtube() -> None:
    miss = _missing(
        "YOUTUBE_OAUTH_CLIENT_ID",
        "YOUTUBE_OAUTH_CLIENT_SECRET",
        "YOUTUBE_REFRESH_TOKEN",
    )
    if miss:
        raise PreflightError(
            f"YouTube 公開に必要な環境変数が不足: {', '.join(miss)}。"
            "youtube.upload スコープ同意済みの token を取得してください。"
        )


def check_final_import() -> None:
    """Stage 7: ffmpeg / ffprobe が PATH 上に居ないと取り込めない。"""
    missing = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    if missing:
        raise PreflightError(
            f"Stage 7 (取込) に必要なバイナリが PATH に見つかりません: "
            f"{', '.join(missing)}。"
            "macOS なら `brew install ffmpeg` でインストールしてください。"
        )
    check_disk_space(_min_free_bytes(_DEFAULT_MIN_FREE_BYTES_SMALL))


def check_publish_instagram() -> None:
    if os.environ.get("INSTAGRAM_ACCESS_TOKEN") and os.environ.get(
        "INSTAGRAM_BUSINESS_ID",
    ):
        return


def check_publish_tiktok() -> None:
    if os.environ.get("TIKTOK_ACCESS_TOKEN") and os.environ.get(
        "TIKTOK_OPEN_ID",
    ):
        return


_STAGE_CHECKS = {
    "tts": check_tts,
    "bg": check_bg,
    "kling": check_kling,
    "scene": check_scene,
    "final_import": check_final_import,
}


def check_stage(stage: str) -> None:
    """指定 stage の前提条件を検査。問題があれば PreflightError を raise。"""
    fn = _STAGE_CHECKS.get(stage)
    if fn is None:
        return
    fn()
