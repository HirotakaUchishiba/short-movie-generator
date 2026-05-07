"""Scene (= 1 Kling クリップ) のファクトリ。"""

from typing import Any

from .line import make_line


def make_scene(
    *,
    lines: list[dict] | None = None,
    location_ref: str = "home_office",
    background_prompt: str | None = None,
    animation_prompt: str = "subject reacts naturally",
    character_refs: list[str] | None = None,
    lipsync: bool = True,
    **overrides: Any,
) -> dict:
    scene: dict = {
        "lines": lines if lines is not None else [make_line()],
        "location_ref": location_ref,
        "animation_prompt": animation_prompt,
        "character_refs": (
            character_refs if character_refs is not None else ["f1__office"]
        ),
        "lipsync": lipsync,
    }
    if background_prompt is not None:
        scene["background_prompt"] = background_prompt
    scene.update(overrides)
    return scene
