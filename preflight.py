"""各 stage を実行する前に必要な env / 依存ファイルが揃っているかを検査する。

外部 API 呼び出しを試みてから「key 未設定」で落ちると、API 通信が始まる
までの数秒〜数十秒は無駄なログが流れる。preflight でいったん検査して
不備があれば即座に明確なエラーで止める。
"""

import os
import logging

import config

logger = logging.getLogger(__name__)


class PreflightError(RuntimeError):
    """前提条件が満たされていないため stage を起動できない。"""


def _missing(*envs: str) -> list[str]:
    return [e for e in envs if not os.environ.get(e)]


def check_tts() -> None:
    if not config.ELEVENLABS_API_KEY:
        raise PreflightError(
            "ELEVENLABS_API_KEY 未設定 — Stage 2 (TTS) を実行できません。"
            ".env に ELEVENLABS_API_KEY=<key> を追加してください。"
        )


def check_bg() -> None:
    if not config.GOOGLE_API_KEY:
        raise PreflightError(
            "GOOGLE_API_KEY 未設定 — Stage 3 (背景画像) を実行できません。"
            ".env に GOOGLE_API_KEY=<key> を追加してください。"
        )


def check_kling() -> None:
    if not config.FAL_API_KEY:
        raise PreflightError(
            "FAL_KEY 未設定 — Stage 4 (Kling) を実行できません。"
            ".env に FAL_KEY=<key> を追加してください。"
        )


def check_scene() -> None:
    """Stage 5+6: lipsync provider に応じた key を検査。"""
    if not getattr(config, "LIPSYNC_ENABLED", True):
        return
    provider = getattr(config, "LIPSYNC_PROVIDER", "syncso")
    if provider == "syncso":
        if not config.SYNCSO_API_KEY:
            raise PreflightError(
                "SYNC_API_KEY 未設定 — Sync.so lipsync を実行できません。"
                ".env に SYNC_API_KEY=<key> を追加するか、"
                "LIPSYNC_PROVIDER を fal-sync / domoai に切替えてください。"
            )
    elif provider == "fal-sync":
        if not config.FAL_API_KEY:
            raise PreflightError(
                "FAL_KEY 未設定 — fal-sync lipsync を実行できません。"
            )
    elif provider == "domoai":
        if not config.DOMOAI_API_KEY:
            raise PreflightError(
                "DOMOAI_API_KEY 未設定 — DomoAI lipsync を実行できません。"
            )
    else:
        raise PreflightError(
            f"未知の LIPSYNC_PROVIDER: {provider} "
            f"(対応: syncso / fal-sync / domoai)"
        )


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


_STAGE_CHECKS = {
    "tts": check_tts,
    "bg": check_bg,
    "kling": check_kling,
    "scene": check_scene,
}


def check_stage(stage: str) -> None:
    """指定 stage の前提条件を検査。問題があれば PreflightError を raise。"""
    fn = _STAGE_CHECKS.get(stage)
    if fn is None:
        return
    fn()
