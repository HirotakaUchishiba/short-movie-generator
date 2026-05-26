"""Phase 2: overlaid.mp4 の字幕焼き込みを OCR で実測する validator。

`subtitle_readability` が screenplay 上の文字数で代用するのに対し、本 validator は
実際に焼き込まれたフレームを OCR して「字幕が描画され画面内に収まっているか」を実測する。

第一版は overlaid.mp4 の代表フレームを ffmpeg で 1 枚抽出し、下部字幕帯 (下 1/3) に
文字を検出できるかを確認する (= 字幕未描画 / 画面外を検出)。

tesseract / pytesseract / ffmpeg のいずれかが無ければ skipped_result。重い処理なので
既定 blacklist (OFF)。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess

from qa.validators.base import (
    ValidationResult,
    failed_result,
    passed_result,
    skipped_result,
)

logger = logging.getLogger(__name__)


def _check_deps() -> tuple[bool, str]:
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as e:
        return False, f"OCR deps missing: {e}"
    if not shutil.which("tesseract"):
        return False, "tesseract binary not found"
    if not shutil.which("ffmpeg"):
        return False, "ffmpeg not found"
    return True, "ok"


def _extract_frame(mp4_path: str, out_png: str, at_sec: float) -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{at_sec}", "-i", mp4_path,
             "-frames:v", "1", out_png],
            capture_output=True, timeout=60, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return os.path.exists(out_png)


def check_subtitle_render(
    ts_path: str, *, screenplay: dict | None = None, **_,
) -> list[ValidationResult]:
    mp4 = os.path.join(ts_path, "overlaid.mp4")
    if not os.path.exists(mp4):
        return []
    ok, reason = _check_deps()
    if not ok:
        return [skipped_result(reason=reason)]

    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:  # _check_deps をすり抜けた壊れた環境への防御
        return [skipped_result(reason=f"OCR deps missing: {e}")]

    frame = os.path.join(ts_path, "_subtitle_render_probe.png")
    if not _extract_frame(mp4, frame, at_sec=1.0):
        return [skipped_result(reason="frame extraction failed")]
    try:
        with Image.open(frame) as im:
            w, h = im.size
            bottom = im.crop((0, int(h * 2 / 3), w, h))
            text = pytesseract.image_to_string(bottom, lang="jpn").strip()
    except Exception as e:  # noqa: BLE001
        return [skipped_result(reason=f"OCR failed: {e}")]
    finally:
        if os.path.exists(frame):
            os.remove(frame)

    metrics = {"ocr_chars": float(len(text))}
    if not text:
        return [failed_result(
            score=0.0,
            reason="字幕帯 (下 1/3) に OCR で文字を検出できず (= 未描画 / 画面外の疑い)",
            tag="subtitle_off_screen", metrics=metrics)]
    return [passed_result(score=1.0, metrics=metrics)]
