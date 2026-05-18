"""scene_gen.py から PIL 画像操作 helper を切り出した module。

ffmpeg / audio 系ではない純粋な静止画変換 (= リサイズ / 余白合成等) を
ここに集約する。scene_gen 側は private shim を残して既存 callsite を
破壊しない。

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.1.1
"""

from __future__ import annotations

from PIL import Image

import config


def prepare_background(bg_path: str, output_path: str) -> None:
    """背景画像を VIDEO_WIDTH×VIDEO_HEIGHT の PNG に正規化する。

    入力画像のアスペクト比に関わらず LANCZOS で resize する (= source 側で
    9:16 を保証している前提)。Stage 5 (scene 合成) で透過レイヤと merge する
    前段で 1 回だけ呼ばれる。
    """
    bg = Image.open(bg_path).convert("RGB")
    bg = bg.resize((config.VIDEO_WIDTH, config.VIDEO_HEIGHT), Image.LANCZOS)
    bg.save(output_path, "PNG")
