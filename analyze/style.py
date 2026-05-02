"""VideoStyle: 動画スタイルテンプレ (キャラ + ロケ + 衣装 + voice + animation)。

screenplays/styles/<name>.json に保存。抽象台本に当てはめてビジュアルを決定する
合成フェーズ (analyze.compose) の入力となる。

設計の詳細は docs/abstract-screenplay-design.md セクション 5。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)


STYLES_DIR = Path(config.SCREENPLAYS_DIR) / "styles"
NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")

ALLOWED_FORMATS = ("narrator", "dialogue")
ALLOWED_ANIMATION_STYLES = ("subtle", "standard", "expressive")
ALLOWED_CAMERA_DISTANCES = ("close-up", "medium-close", "medium", "wide")


@dataclass
class CharacterDef:
    name: str
    role: str
    ref: str  # characters/<ref>.png のキー
    voice_overrides: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "CharacterDef":
        return cls(
            name=d["name"],
            role=d.get("role", ""),
            ref=d["ref"],
            voice_overrides=dict(d.get("voice_overrides") or {}),
        )


@dataclass
class LocationDef:
    decor: str = ""
    lighting: str = ""
    color_palette: str = ""
    props: str = ""
    camera_distance: str = "medium"

    @classmethod
    def from_dict(cls, d: dict) -> "LocationDef":
        return cls(
            decor=d.get("decor", ""),
            lighting=d.get("lighting", ""),
            color_palette=d.get("color_palette", ""),
            props=d.get("props", ""),
            camera_distance=d.get("camera_distance", "medium"),
        )


@dataclass
class VideoStyle:
    name: str
    format: str = "narrator"  # narrator | dialogue
    characters: list[CharacterDef] = field(default_factory=list)
    wardrobe_continuity: dict[str, str] = field(default_factory=dict)
    default_wardrobe: str | None = None
    location_continuity: dict[str, LocationDef] = field(default_factory=dict)
    default_location: str | None = None
    default_tags: list[str] = field(default_factory=list)
    scoped_augmentations: list[dict] = field(default_factory=list)
    animation_style: str = "standard"  # subtle | standard | expressive

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.name:
            errors.append("name is required")
        elif not NAME_RE.match(self.name):
            errors.append(f"name must match {NAME_RE.pattern}")
        if self.format not in ALLOWED_FORMATS:
            errors.append(f"format must be one of {ALLOWED_FORMATS}")
        if self.animation_style not in ALLOWED_ANIMATION_STYLES:
            errors.append(
                f"animation_style must be one of {ALLOWED_ANIMATION_STYLES}",
            )
        if not self.characters:
            errors.append("characters[] requires at least 1 entry")
        names = set()
        for c in self.characters:
            if not c.name or not c.ref:
                errors.append(f"character requires name and ref: {c}")
                continue
            if c.name in names:
                errors.append(f"duplicate character name: {c.name}")
            names.add(c.name)
        if self.default_wardrobe and self.default_wardrobe not in self.wardrobe_continuity:
            errors.append(
                f"default_wardrobe '{self.default_wardrobe}' is not in "
                "wardrobe_continuity",
            )
        if self.default_location and self.default_location not in self.location_continuity:
            errors.append(
                f"default_location '{self.default_location}' is not in "
                "location_continuity",
            )
        for loc_id, loc in self.location_continuity.items():
            if loc.camera_distance not in ALLOWED_CAMERA_DISTANCES:
                errors.append(
                    f"location[{loc_id}].camera_distance "
                    f"must be one of {ALLOWED_CAMERA_DISTANCES}",
                )
        return errors

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "format": self.format,
            "characters": [asdict(c) for c in self.characters],
            "wardrobe_continuity": self.wardrobe_continuity,
            "default_wardrobe": self.default_wardrobe,
            "location_continuity": {
                k: asdict(v) for k, v in self.location_continuity.items()
            },
            "default_location": self.default_location,
            "default_tags": self.default_tags,
            "scoped_augmentations": self.scoped_augmentations,
            "animation_style": self.animation_style,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VideoStyle":
        return cls(
            name=d.get("name", ""),
            format=d.get("format", "narrator"),
            characters=[
                CharacterDef.from_dict(c) for c in d.get("characters") or []
            ],
            wardrobe_continuity=dict(d.get("wardrobe_continuity") or {}),
            default_wardrobe=d.get("default_wardrobe"),
            location_continuity={
                k: LocationDef.from_dict(v)
                for k, v in (d.get("location_continuity") or {}).items()
            },
            default_location=d.get("default_location"),
            default_tags=list(d.get("default_tags") or []),
            scoped_augmentations=list(d.get("scoped_augmentations") or []),
            animation_style=d.get("animation_style", "standard"),
        )


# ─── CRUD ───────────────────────────────────────────────────────


def _path(name: str) -> Path:
    if not NAME_RE.match(name or ""):
        raise ValueError(f"invalid style name: {name!r}")
    STYLES_DIR.mkdir(parents=True, exist_ok=True)
    return STYLES_DIR / f"{name}.json"


def list_styles() -> list[str]:
    """登録済み VideoStyle 名一覧 (アルファベット順)。"""
    if not STYLES_DIR.is_dir():
        return []
    return sorted(p.stem for p in STYLES_DIR.glob("*.json"))


def load_style(name: str) -> VideoStyle:
    """指定名の VideoStyle を読み込む。存在しなければ FileNotFoundError。"""
    p = _path(name)
    if not p.exists():
        raise FileNotFoundError(f"VideoStyle not found: {name}")
    with open(p, encoding="utf-8") as f:
        return VideoStyle.from_dict(json.load(f))


def save_style(style: VideoStyle) -> None:
    """validate を通った VideoStyle を保存する。失敗時 ValueError。"""
    errors = style.validate()
    if errors:
        raise ValueError("VideoStyle validation failed: " + "; ".join(errors))
    p = _path(style.name)
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(style.to_dict(), f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(p)


def delete_style(name: str) -> bool:
    """style を削除する。存在しなければ False。"""
    p = _path(name)
    if not p.exists():
        return False
    p.unlink()
    return True
