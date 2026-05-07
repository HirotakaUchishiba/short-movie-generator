"""Screenplay (= 1 動画分の台本) のファクトリ。"""

from typing import Any

from .scene import make_scene


def make_screenplay(
    *,
    caption: str = "テスト用キャプション\n#test",
    scenes: list[dict] | None = None,
    **overrides: Any,
) -> dict:
    sp: dict = {
        "caption": caption,
        "scenes": scenes if scenes is not None else [make_scene()],
    }
    sp.update(overrides)
    return sp
