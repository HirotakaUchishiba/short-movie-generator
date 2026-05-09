"""ロケ集 (= 全動画で共有するグローバル素材集)。

locations/<id>.json に保存。1 ロケ = decor + lighting + color_palette + props +
camera_distance のフルセット。シーンの location_ref がここを参照する。
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import config

LOCATIONS_DIR = Path(config.BASE_DIR) / "locations"
ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
ALLOWED_CAMERA_DISTANCES = ("close-up", "medium-close", "medium", "wide")


@dataclass
class Location:
    id: str
    decor: str = ""
    lighting: str = ""
    color_palette: str = ""
    props: str = ""
    camera_distance: str = "medium"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.id:
            errors.append("id is required")
        elif not ID_RE.match(self.id):
            errors.append(f"id must match {ID_RE.pattern}")
        if self.camera_distance not in ALLOWED_CAMERA_DISTANCES:
            errors.append(
                f"camera_distance must be one of {ALLOWED_CAMERA_DISTANCES}",
            )
        return errors

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Location":
        return cls(
            id=d.get("id", ""),
            decor=d.get("decor", ""),
            lighting=d.get("lighting", ""),
            color_palette=d.get("color_palette", ""),
            props=d.get("props", ""),
            camera_distance=d.get("camera_distance", "medium"),
        )


def _path(loc_id: str) -> Path:
    if not ID_RE.match(loc_id or ""):
        raise ValueError(f"invalid location id: {loc_id!r}")
    LOCATIONS_DIR.mkdir(parents=True, exist_ok=True)
    return LOCATIONS_DIR / f"{loc_id}.json"


def preview_path(loc_id: str) -> Path:
    """locations/<id>.preview.png のパス。LocationPicker で表示する。"""
    if not ID_RE.match(loc_id or ""):
        raise ValueError(f"invalid location id: {loc_id!r}")
    return LOCATIONS_DIR / f"{loc_id}.preview.png"


def list_locations() -> list[str]:
    """登録済みロケ ID 一覧 (アルファベット順)。"""
    if not LOCATIONS_DIR.is_dir():
        return []
    return sorted(p.stem for p in LOCATIONS_DIR.glob("*.json"))


def load_location(loc_id: str) -> Location:
    p = _path(loc_id)
    if not p.exists():
        raise FileNotFoundError(f"Location not found: {loc_id}")
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    if "id" not in d:
        d["id"] = loc_id
    return Location.from_dict(d)


def save_location(loc: Location) -> None:
    errors = loc.validate()
    if errors:
        raise ValueError("Location validation failed: " + "; ".join(errors))
    p = _path(loc.id)
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(loc.to_dict(), f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(p)


def delete_location(loc_id: str) -> bool:
    p = _path(loc_id)
    if not p.exists():
        return False
    p.unlink()
    return True
