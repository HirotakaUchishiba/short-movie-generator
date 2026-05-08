"""Phase 2: 字幕領域 (= 画面下 1/3) に視覚要素が混んでいる場合に警告する。

本格的には U²-Net で被写体 mask を取って字幕 bbox との IoU を計算するが、
ML 依存を Phase 2 では強制しないため、PIL の標準偏差 (= 輝度分散) で
「下 1/3 の情報量」を近似する。

しきい値は Phase 0/1 の qa_failures から ROC で決め直す前提の暫定値。
"""
from __future__ import annotations

import glob
import logging
import os
import re

from qa.validators.base import (
    ValidationResult,
    failed_result,
    passed_result,
)

logger = logging.getLogger(__name__)

BG_FILE_RE = re.compile(r"bg_(\d+)\.png$")
# 暫定: グレースケール stddev > 60 (255 中) なら視覚要素過多と判定。
SUBTITLE_ZONE_STDDEV_FAIL = 60.0


def _bottom_third_stddev(png_path: str) -> float:
    from PIL import Image, ImageStat
    with Image.open(png_path) as im:
        gray = im.convert("L")
        w, h = gray.size
        bottom = gray.crop((0, int(h * 2 / 3), w, h))
        return float(ImageStat.Stat(bottom).stddev[0])


def check_subtitle_overlap(ts_path: str, **_) -> list[ValidationResult]:
    out: list[ValidationResult] = []
    for png in sorted(glob.glob(os.path.join(ts_path, "bg_*.png"))):
        m = BG_FILE_RE.search(png)
        if not m:
            continue
        scene_idx = int(m.group(1))
        try:
            stddev = _bottom_third_stddev(png)
        except (FileNotFoundError, OSError) as e:
            out.append(failed_result(
                score=0.0, reason=f"image read failed: {e}",
                tag="subtitle_zone_blocked",
                scene_idx=scene_idx,
            ))
            continue
        metrics = {"bottom_third_stddev": stddev}
        if stddev > SUBTITLE_ZONE_STDDEV_FAIL:
            severity = (stddev - SUBTITLE_ZONE_STDDEV_FAIL) / 40.0
            out.append(failed_result(
                score=max(0.0, 1.0 - severity),
                reason=f"bottom_stddev={stddev:.1f} > {SUBTITLE_ZONE_STDDEV_FAIL}",
                tag="subtitle_zone_blocked",
                metrics=metrics, scene_idx=scene_idx,
            ))
        else:
            out.append(passed_result(
                score=1.0 - (stddev / SUBTITLE_ZONE_STDDEV_FAIL),
                metrics=metrics, scene_idx=scene_idx,
            ))
    return out
