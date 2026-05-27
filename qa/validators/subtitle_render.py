"""Phase 5: overlaid.mp4 の字幕焼き込みを **視覚検証** する validator。

`subtitle_readability` が screenplay 上の文字数で代用するのに対し、本 validator は
実際に焼き込まれたフレームを画像解析して「字幕帯 (下 1/3) にテキスト様の高コントラスト
要素が描画されているか」を実測する。

主経路は opencv の **エッジ密度** (= Canny エッジの画素比率) で、tesseract 不要。
字幕が出たり消えたりするため複数時刻でフレームをサンプルし、最大エッジ密度で判定する
(= 単一固定フレームだと無字幕の瞬間に当たり誤判定する問題への対応)。tesseract が
あれば OCR で文字認識も行い metrics に残す (= 補強、任意)。

依存: ffmpeg + opencv (必須)。tesseract + pytesseract (任意)。重いため既定 blacklist。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess

import config
from qa.validators.base import (
    ValidationResult,
    failed_result,
    passed_result,
    skipped_result,
)

logger = logging.getLogger(__name__)

# 字幕帯を何分割の時刻でサンプルするか (= 字幕の出/消を跨ぐため複数点)。
_SAMPLE_FRACTIONS = (0.2, 0.4, 0.6, 0.8)


def _deps_ok() -> tuple[bool, str]:
    try:
        import cv2  # noqa: F401
    except ImportError as e:
        return False, f"opencv missing: {e}"
    if not shutil.which("ffmpeg"):
        return False, "ffmpeg not found"
    if not shutil.which("ffprobe"):
        return False, "ffprobe not found"
    return True, "ok"


def _video_duration(mp4_path: str) -> float:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", mp4_path],
            capture_output=True, text=True, timeout=30, check=False)
        return float((proc.stdout or "").strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return 0.0


def _extract_frame(mp4_path: str, out_png: str, at_sec: float) -> bool:
    # 前回クラッシュ等で残った stale フレームを成功扱いしないよう先に消す。
    if os.path.exists(out_png):
        os.remove(out_png)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{at_sec}", "-i", mp4_path,
             "-frames:v", "1", out_png],
            capture_output=True, timeout=60, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    # 0 byte / 未生成は失敗扱い (= ffmpeg 失敗時の空ファイルを弾く)。
    return os.path.exists(out_png) and os.path.getsize(out_png) > 0


def _edge_density_bottom(png_path: str) -> float:
    """画像下 1/3 の Canny エッジ画素比率 (= テキスト様要素の量の近似)。"""
    import cv2
    img = cv2.imread(png_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    h, w = img.shape[:2]
    bottom = img[int(h * 2 / 3):, :]
    if bottom.size == 0:  # 極端に小さいフレームで下帯が空になるのを防ぐ
        return 0.0
    edges = cv2.Canny(bottom, 100, 200)
    return float((edges > 0).mean())


def _ocr_bottom(png_path: str) -> str | None:
    """tesseract があれば下帯を OCR (= 補強、任意)。無ければ None。"""
    if not shutil.which("tesseract"):
        return None
    try:
        import pytesseract
        from PIL import Image
        with Image.open(png_path) as im:
            w, h = im.size
            bottom = im.crop((0, int(h * 2 / 3), w, h))
            return pytesseract.image_to_string(bottom, lang="jpn").strip()
    except Exception:  # noqa: BLE001  (OCR は補強なので失敗は無視)
        return None


def check_subtitle_render(
    ts_path: str, *, screenplay: dict | None = None, **_,
) -> list[ValidationResult]:
    mp4 = os.path.join(ts_path, "overlaid.mp4")
    if not os.path.exists(mp4):
        return []
    ok, reason = _deps_ok()
    if not ok:
        return [skipped_result(reason=reason)]
    duration = _video_duration(mp4)
    if duration <= 0:
        return [skipped_result(reason="could not determine video duration")]

    densities: list[float] = []
    ocr_found = False
    for i, frac in enumerate(_SAMPLE_FRACTIONS):
        frame = os.path.join(ts_path, f"_render_probe_{i}.png")
        if not _extract_frame(mp4, frame, duration * frac):
            continue
        try:
            densities.append(_edge_density_bottom(frame))
            if _ocr_bottom(frame):
                ocr_found = True
        finally:
            if os.path.exists(frame):
                os.remove(frame)

    if not densities:
        return [skipped_result(reason="frame extraction failed")]

    max_density = max(densities)
    threshold = config.SUBTITLE_RENDER_EDGE_DENSITY_MIN
    metrics = {
        "max_edge_density": max_density,
        "ocr_text_found": 1.0 if ocr_found else 0.0,
        "frames_sampled": float(len(densities)),
    }
    if max_density < threshold:
        return [failed_result(
            score=max_density / threshold if threshold else 0.0,
            reason=(f"字幕帯のエッジ密度 max={max_density:.4f} < {threshold} "
                    f"(全 {len(densities)} フレームで字幕未描画 / 画面外の疑い)"),
            tag="subtitle_off_screen", metrics=metrics)]
    return [passed_result(score=1.0, metrics=metrics)]
