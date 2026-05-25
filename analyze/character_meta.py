"""キャラエンティティの voice メタデータ + ファイル配置。

ディレクトリ構造 (新):

    characters/
      <base>/                 ← 被写体 ID (顔・体型が同じ人)
        voice.json            ← voice メタ (= base 単位、衣装で変わらない)
        <wardrobe>.png        ← 衣装込みの参照画像 (= 全身 9:16 推奨)
        preview.png           ← 任意のサムネ (= UI で base 単位の代表絵)

screenplay 側で使う「resolved id」は ``<base>__<wardrobe>`` で従来と同じ。
解決規則:
  - resolved="<base>__<wardrobe>" → image=characters/<base>/<wardrobe>.png
  - resolved="<base>"             → image=characters/<base>/base.png
  - voice meta は常に characters/<base>/voice.json

互換: 旧 flat レイアウト ``characters/<id>.png`` / ``<id>.json`` も
fallback として読み込む (= 移行中は両方で動く)。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import config

CHARACTERS_DIR = Path(config.CHARACTERS_DIR)
ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
BASE_WARDROBE_SEP = "__"


@dataclass
class CharacterMeta:
    id: str  # base id (= voice 単位)
    # voice_id: ElevenLabs voice library の id。未設定なら
    # config.ELEVENLABS_VOICE_ID にフォールバックする。Stage 2 TTS が
    # per-character voice で発話するときの主鍵。
    voice_id: str | None = None
    voice_overrides: dict[str, Any] = field(default_factory=dict)
    # appearance: analyze の speaker_profiles とマッチさせる外見ヒント
    # (gender / age_range / description)。すべて optional。無くても casting
    # 提案は動く (= analyze は appearance 不在のキャラも候補にする)。
    appearance: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.id:
            errors.append("id is required")
        elif not ID_RE.match(self.id):
            errors.append(f"id must match {ID_RE.pattern}")
        if BASE_WARDROBE_SEP in self.id:
            errors.append(
                f"id must be the BASE id (no '{BASE_WARDROBE_SEP}' wardrobe suffix)",
            )
        if self.voice_id is not None and not isinstance(self.voice_id, str):
            errors.append("voice_id must be a string when present")
        return errors

    def to_dict(self) -> dict:
        d: dict = {"id": self.id}
        # voice_id は optional。空なら voice.json に書かない (= 旧 file の
        # 互換性を守る)。
        if self.voice_id:
            d["voice_id"] = self.voice_id
        d["voice_overrides"] = dict(self.voice_overrides)
        # appearance は optional。空なら voice.json に書かない (= 既存ファイルを
        # 不要な空 dict で汚さない)。
        if self.appearance:
            d["appearance"] = dict(self.appearance)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CharacterMeta":
        overrides = dict(d.get("voice_overrides") or {})
        # voice_id はトップレベルを正とするが、voice_overrides の中に書かれて
        # いる揺れも昇格して拾う (= 手書き / 旧データのスキーマブレを吸収する)。
        # voice_overrides に残すと build_voice_settings が拾わないとはいえ無駄な
        # key になるため pop して取り除く。
        nested_vid = overrides.pop("voice_id", None)
        raw_vid = d.get("voice_id") or nested_vid
        voice_id = raw_vid if isinstance(raw_vid, str) and raw_vid else None
        return cls(
            id=d.get("id", ""),
            voice_id=voice_id,
            voice_overrides=overrides,
            appearance=dict(d.get("appearance") or {}),
        )


def split_resolved_id(resolved: str) -> tuple[str, str | None]:
    """resolved id を (base, wardrobe) に分解。wardrobe 無しなら (base, None)。"""
    if BASE_WARDROBE_SEP in resolved:
        base, _, wardrobe = resolved.partition(BASE_WARDROBE_SEP)
        return base, wardrobe or None
    return resolved, None


def base_dir(base_id: str) -> Path:
    if not ID_RE.match(base_id or ""):
        raise ValueError(f"invalid character base id: {base_id!r}")
    return CHARACTERS_DIR / base_id


def _voice_path(base_id: str) -> Path:
    return base_dir(base_id) / "voice.json"


def _flat_voice_path(any_id: str) -> Path:
    """旧 flat レイアウト: characters/<any_id>.json"""
    return CHARACTERS_DIR / f"{any_id}.json"


def image_path(resolved_id: str) -> Path | None:
    """resolved id (= ``<base>__<wardrobe>`` or ``<base>``) から PNG パスを返す。
    新ネスト構造を優先し、見つからなければ flat にフォールバック。存在しない
    場合は None。
    """
    base, wardrobe = split_resolved_id(resolved_id)
    if not ID_RE.match(base):
        return None
    if wardrobe is not None and not ID_RE.match(wardrobe):
        return None

    nested = base_dir(base) / (
        f"{wardrobe}.png" if wardrobe else "base.png"
    )
    if nested.exists():
        return nested

    flat = CHARACTERS_DIR / f"{resolved_id}.png"
    if flat.exists():
        return flat
    return None


def list_character_metas() -> list[str]:
    """voice.json を持つ base ID 一覧 (= 「人物」一覧)。"""
    if not CHARACTERS_DIR.is_dir():
        return []
    bases: set[str] = set()
    for child in CHARACTERS_DIR.iterdir():
        if child.is_dir() and (child / "voice.json").exists():
            bases.add(child.name)
    # 旧 flat 互換: characters/<id>.json も拾う (= 移行中)
    for p in CHARACTERS_DIR.glob("*.json"):
        bases.add(p.stem)
    return sorted(bases)


def list_character_images() -> list[str]:
    """利用可能な resolved id 一覧 (= screenplay の character_refs に書ける ID)。

    新構造: characters/<base>/<wardrobe>.png を ``<base>__<wardrobe>`` に展開。
            <base>/base.png は ``<base>`` 単独 ID として返す。
    旧 flat:  characters/<id>.png はそのまま <id> を返す。
    """
    if not CHARACTERS_DIR.is_dir():
        return []
    out: set[str] = set()
    for child in CHARACTERS_DIR.iterdir():
        if child.is_dir():
            base = child.name
            if not ID_RE.match(base):
                continue
            for png in child.glob("*.png"):
                stem = png.stem
                if stem == "base":
                    out.add(base)
                elif stem == "preview":
                    continue
                elif ID_RE.match(stem):
                    out.add(f"{base}{BASE_WARDROBE_SEP}{stem}")
    for p in CHARACTERS_DIR.glob("*.png"):
        out.add(p.stem)
    return sorted(out)


def load_character_meta(char_id: str) -> CharacterMeta:
    """char_id は resolved id でも base id でも受け付ける (= 衣装サフィックスは
    自動で剥がして base 単位の voice.json を読む)。
    """
    base, _ = split_resolved_id(char_id)
    if not ID_RE.match(base):
        raise ValueError(f"invalid character id: {char_id!r}")

    nested = _voice_path(base)
    if nested.exists():
        with open(nested, encoding="utf-8") as f:
            d = json.load(f)
        d["id"] = base
        return CharacterMeta.from_dict(d)

    # 旧 flat: <char_id>.json or <base>.json
    for candidate in (char_id, base):
        flat = _flat_voice_path(candidate)
        if flat.exists():
            with open(flat, encoding="utf-8") as f:
                d = json.load(f)
            d["id"] = base
            return CharacterMeta.from_dict(d)

    return CharacterMeta(id=base)


def save_character_meta(meta: CharacterMeta) -> None:
    """meta.id は base ID。新ネスト構造 (characters/<base>/voice.json) に保存。"""
    errors = meta.validate()
    if errors:
        raise ValueError(
            "CharacterMeta validation failed: " + "; ".join(errors),
        )
    d = base_dir(meta.id)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "voice.json"
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta.to_dict(), f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(p)


def delete_character_meta(char_id: str) -> bool:
    """nested の voice.json か旧 flat の <id>.json を削除。両方無ければ False。"""
    base, _ = split_resolved_id(char_id)
    is_deleted = False
    nested = _voice_path(base)
    if nested.exists():
        nested.unlink()
        is_deleted = True
    flat = _flat_voice_path(char_id)
    if flat.exists():
        flat.unlink()
        is_deleted = True
    return is_deleted


def build_character_catalog() -> list[dict]:
    """利用可能なキャラ全件を analyze prompt 注入用の dict list で返す。

    video_analyzer が Claude に「speaker_profiles をこの集合と突合せて
    featured_characters / speaker_to_ref を提案せよ」と渡す catalog。
    画像を持つ resolved id を base 単位にまとめ、base の appearance を添える。
    壊れた voice.json は appearance 空で続行する (= 1 件の不正で止めない)。

    各 entry:
      ``{"id": <base>, "appearance": {...}, "refs": [<resolved id>, ...]}``
    """
    by_base: dict[str, list[str]] = {}
    for resolved in list_character_images():
        base, _ = split_resolved_id(resolved)
        by_base.setdefault(base, []).append(resolved)

    catalog: list[dict] = []
    for base_id in sorted(by_base):
        try:
            appearance = load_character_meta(base_id).appearance
        except (json.JSONDecodeError, ValueError):
            appearance = {}
        catalog.append({
            "id": base_id,
            "appearance": appearance,
            "refs": sorted(by_base[base_id]),
        })
    return catalog
