"""抽象台本 + VideoStyle → 完全 screenplay の合成 (決定論的)。

抽象台本 (analyze.pipeline が生成) には構成・セリフ・感情・話し方しか入っていない。
ここで VideoStyle (キャラ + ロケ + 衣装) を当てはめて、screenplay_validator
strict が通る完全 screenplay を生成する。

合成は決定論的 (テンプレ + 動作キーワードを文字列連結)。Claude を呼ばないので
コストゼロ・キャッシュ可能・再現性が高い。
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from analyze.style import CharacterDef, VideoStyle

logger = logging.getLogger(__name__)


# camera_distance ID → 英語 shot ラベル
_CAMERA_LABELS = {
    "close-up": "close-up shot",
    "medium-close": "medium close-up shot",
    "medium": "medium shot",
    "wide": "wide shot",
}

# animation_style ID → 動きの英語修飾
_ANIMATION_STYLE_MODIFIERS = {
    "subtle": "with minimal hand movement, mostly facial expression",
    "standard": "with natural hand gestures and body language",
    "expressive": "with energetic gestures and pronounced movement",
}


def compose_screenplay(
    abstract: dict,
    style: VideoStyle,
    overrides: dict[int, dict[str, Any]] | None = None,
) -> dict:
    """抽象台本に VideoStyle を当てて完全 screenplay を生成。

    Args:
        abstract: pipeline.run() が生成した抽象台本 (caption + scenes[].lines[])
        style: 適用する VideoStyle
        overrides: シーン別 override。{scene_idx: {wardrobe?, location_ref?, tags?}}

    Returns:
        screenplay_validator strict を通せる完全 screenplay 辞書
    """
    overrides = overrides or {}
    sp: dict[str, Any] = {
        "caption": abstract.get("caption", ""),
        "wardrobe_continuity": dict(style.wardrobe_continuity),
        "location_continuity": {
            k: asdict(v) for k, v in style.location_continuity.items()
        },
        "scoped_augmentations": list(style.scoped_augmentations),
        "scenes": [],
    }

    voice_by_speaker = {
        c.name: dict(c.voice_overrides) for c in style.characters
    }
    default_voice = (
        dict(style.characters[0].voice_overrides) if style.characters else {}
    )

    for i, src in enumerate(abstract.get("scenes") or []):
        sov = overrides.get(i) or {}
        scene_chars = _resolve_scene_characters(src, style)

        scene: dict[str, Any] = {
            "duration": float(src.get("duration", 0)),
            "characters": [
                {"name": c.name, "role": c.role} for c in scene_chars
            ],
            "character_refs": [c.ref for c in scene_chars],
            "wardrobe": {
                "identifier": sov.get(
                    "wardrobe", style.default_wardrobe or "",
                ),
            },
            "location_ref": sov.get(
                "location_ref", style.default_location or "",
            ),
            "tags": list(sov.get("tags", style.default_tags)),
            "lipsync": True,
            "lines": [],
        }

        scene["background_prompt"] = _compose_background(scene, style)
        scene["animation_prompt"] = _compose_animation(src, style)

        # lines に voice_overrides を speaker から自動注入
        for line in src.get("lines") or []:
            new_line = dict(line)
            speaker = line.get("speaker")
            if speaker and speaker in voice_by_speaker:
                new_line["voice_overrides"] = dict(voice_by_speaker[speaker])
            elif default_voice and not speaker:
                # 単一キャラ動画: speaker 省略 → デフォルト voice
                new_line["voice_overrides"] = dict(default_voice)
            scene["lines"].append(new_line)

        sp["scenes"].append(scene)

    return sp


def _resolve_scene_characters(
    src_scene: dict, style: VideoStyle,
) -> list[CharacterDef]:
    """シーンに登場するキャラを VideoStyle から解決する。

    - narrator モード: 全シーン共通で style.characters 全部 (= 通常は 1 人)
    - dialogue モード: 抽象台本の lines[].speaker に出る名前のキャラだけ subset
                       (出てこない場合は安全側で全キャラ)
    """
    if style.format == "narrator" or not style.characters:
        return list(style.characters)
    speakers = {
        l.get("speaker") for l in src_scene.get("lines") or []
        if l.get("speaker")
    }
    if not speakers:
        return list(style.characters)
    matched = [c for c in style.characters if c.name in speakers]
    return matched or list(style.characters)


def _compose_background(scene: dict, style: VideoStyle) -> str:
    """ロケ + 衣装 + カメラ距離 + キャラから 1 文を生成 (決定論的)。"""
    loc_id = scene.get("location_ref", "")
    wardrobe_id = (scene.get("wardrobe") or {}).get("identifier", "")
    loc = style.location_continuity.get(loc_id)
    wardrobe_text = style.wardrobe_continuity.get(wardrobe_id, "")
    chars_str = "、".join(c["name"] for c in scene.get("characters", []))

    if not loc:
        # ロケ未指定: 最低限の被写体 + キャラ
        body = f"medium shot of {chars_str}"
        if wardrobe_text:
            body += f" wearing {wardrobe_text}"
        return f"{body}, single moment in time"

    distance_label = _CAMERA_LABELS.get(loc.camera_distance, "medium shot")
    body = f"{distance_label} of {chars_str}"
    if wardrobe_text:
        body += f" wearing {wardrobe_text}"

    extras: list[str] = []
    if loc.decor:
        extras.append(loc.decor)
    if loc.props:
        extras.append(loc.props)
    if loc.color_palette:
        extras.append(f"color palette: {loc.color_palette}")
    if loc.lighting:
        extras.append(loc.lighting)

    extras_text = "、".join(extras)
    if extras_text:
        return f"{body}、{extras_text}, single moment in time"
    return f"{body}, single moment in time"


def _compose_animation(src_scene: dict, style: VideoStyle) -> str:
    """emotion arc + animation_style から 1 文を生成 (英語)。"""
    emotions = [
        l.get("emotion") for l in src_scene.get("lines") or []
        if l.get("emotion")
    ]
    # 重複排除しつつ順序維持
    arc_parts: list[str] = []
    seen: set[str] = set()
    for e in emotions:
        if e not in seen:
            arc_parts.append(e)
            seen.add(e)
    arc = " → ".join(arc_parts) if arc_parts else "neutral"

    modifier = _ANIMATION_STYLE_MODIFIERS.get(
        style.animation_style, _ANIMATION_STYLE_MODIFIERS["standard"],
    )
    return (
        f"subject speaks naturally following the emotion arc ({arc}), "
        f"{modifier}"
    )
