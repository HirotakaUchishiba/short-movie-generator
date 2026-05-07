"""生成 artifact (PNG / MP4) の整合性チェック。

`os.path.exists` だけで skip 判定すると、過去のクラッシュで残った
truncated PNG / mp4 が再実行時にそのまま採用されて下流が破綻する。
このモジュールはファイルが妥当か (= PIL で開ける / ffprobe で duration が
取れる) を最低限チェックし、破損時は warning ログを残す。

既定の挙動:
    - 整合性チェックは ON (= ARTIFACT_INTEGRITY_CHECK_ENABLED=True)
    - 破損検出時は警告ログのみ。**自動削除はしない**
      (= 意図しない再生成課金を防ぐため)
    - ユーザが意図して再生成したい時は、警告に従って手動で削除 + run-next

明示的に削除させたい場合:
    config.ARTIFACT_INTEGRITY_AUTO_DELETE=True (or env
    ``ARTIFACT_INTEGRITY_AUTO_DELETE=1``) で「破損なら削除して再生成へ進む」
    モードに切替えられる。

整合性チェック自体を切りたい場合 (= 誤検知時の緊急回避):
    config.ARTIFACT_INTEGRITY_CHECK_ENABLED=False (or env
    ``ARTIFACT_INTEGRITY_CHECK_DISABLED=1``)
"""

import json
import logging
import os
import subprocess

import config

logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    if os.environ.get("ARTIFACT_INTEGRITY_CHECK_DISABLED", "").lower() in (
        "1", "true", "yes"
    ):
        return False
    return bool(getattr(config, "ARTIFACT_INTEGRITY_CHECK_ENABLED", True))


def is_auto_delete() -> bool:
    if os.environ.get("ARTIFACT_INTEGRITY_AUTO_DELETE", "").lower() in (
        "1", "true", "yes"
    ):
        return True
    return bool(getattr(config, "ARTIFACT_INTEGRITY_AUTO_DELETE", False))


def is_valid_png(path: str) -> bool:
    try:
        from PIL import Image
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False


def is_valid_mp4(path: str) -> bool:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", path],
            capture_output=True, text=True, check=False,
        )
        if r.returncode != 0:
            return False
        data = json.loads(r.stdout or "{}")
        dur = float((data.get("format") or {}).get("duration", 0) or 0)
        return dur > 0
    except Exception:
        return False


def is_valid_audio(path: str, *, min_duration: float = 0.05) -> bool:
    """mp3 / m4a / wav が ffprobe で正の duration を返すかを確認。

    truncated TTS file を検出するために使う。ffprobe は moov/header が壊れた
    audio に対して非ゼロ exit するか、duration を返さない。
    """
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", path],
            capture_output=True, text=True, check=False, timeout=10,
        )
        if r.returncode != 0:
            return False
        data = json.loads(r.stdout or "{}")
        dur = float((data.get("format") or {}).get("duration", 0) or 0)
        return dur >= min_duration
    except Exception:
        return False


def check_existing(path: str, kind: str, *, label: str = "") -> bool:
    """既存 artifact が妥当か検証する。

    Args:
        path: 対象ファイルパス。存在しなければ True (= caller は通常の生成パスへ)。
        kind: "png" or "mp4"
        label: ログ用ラベル (例: "scene 3 BG")

    Returns:
        True なら caller は **既存ファイルを使ってよい** (= skip OK)
        False なら caller は **再生成してよい** (= AUTO_DELETE=on で破損検出時のみ)

    挙動:
        - 整合性チェック OFF → True (既存挙動)
        - ファイル無し → True (caller は既に exists チェックしている前提だが、安全側)
        - 妥当 → True
        - 破損 + AUTO_DELETE off (既定) → True を返しつつ warning ログのみ
          (= 既存ファイルがそのまま使われる。再生成課金を避ける)
        - 破損 + AUTO_DELETE on → ファイル削除して False を返す
          (= caller が再生成へ進む)
    """
    if not is_enabled():
        return True
    if not os.path.exists(path):
        return True

    if kind == "png":
        checker = is_valid_png
    elif kind == "audio":
        checker = is_valid_audio
    else:
        checker = is_valid_mp4
    if checker(path):
        return True

    suffix = f" ({label})" if label else ""
    logger.warning(
        "[整合性] 破損疑いの artifact を検出%s: %s — "
        "再生成したい場合は手動で削除してから run-next してください "
        "(自動削除を有効にするには ARTIFACT_INTEGRITY_AUTO_DELETE=1)",
        suffix, path,
    )

    if is_auto_delete():
        try:
            os.remove(path)
        except OSError as e:
            logger.warning("[整合性] auto-delete 失敗: %s — %s", path, e)
            return True
        logger.warning("[整合性] AUTO_DELETE=on のため削除: %s", path)
        return False

    return True
