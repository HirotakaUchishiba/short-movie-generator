"""project snapshot から下記フィールドを除去する。

  root:
    - wardrobe_continuity
    - location_continuity
  scenes[]:
    - wardrobe / wardrobe_top / wardrobe_bottom / wardrobe_hair /
      wardrobe_accessories / wardrobe_tag
    - location_custom / decor / lighting / color_palette / props
    - characters[].role

scenes[].wardrobe.identifier の値があれば、character_refs を
<base>__<wardrobe.identifier> 形式に書き換える (該当ファイルが characters/ に
存在することは別途確認が必要)。

Usage:
    python3 scripts/strip_wardrobe_fields.py             # dry-run
    python3 scripts/strip_wardrobe_fields.py --apply     # 実際に書き換え
    python3 scripts/strip_wardrobe_fields.py --ts 20260502_124844
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from glob import glob

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(THIS_DIR)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

logger = logging.getLogger("strip_wardrobe_fields")

ROOT_KEYS_TO_REMOVE = (
    "wardrobe_continuity",
    "location_continuity",
)
SCENE_KEYS_TO_REMOVE = (
    "wardrobe",
    "wardrobe_top",
    "wardrobe_bottom",
    "wardrobe_hair",
    "wardrobe_accessories",
    "wardrobe_tag",
    "location_custom",
    "decor",
    "lighting",
    "color_palette",
    "props",
)


def _normalize_base_ref(ref: str) -> str:
    """character_refs に入りうる "characters/foo.png" / "foo.png" / "foo__bar"
    を base ref キーに正規化する。
    """
    base = os.path.basename(ref)
    if base.endswith(".png"):
        base = base[:-4]
    if "__" in base:
        base = base.split("__", 1)[0]
    return base


def _migrate_one(sp: dict, rewrite_refs: bool) -> tuple[dict, list[str]]:
    """snapshot から削除対象フィールドを除去し、scene.wardrobe.identifier から
    character_refs に <base>__<wardrobe> 形式を焼き込む。"""
    changes: list[str] = []
    new_sp = dict(sp)

    for k in ROOT_KEYS_TO_REMOVE:
        if k in new_sp:
            del new_sp[k]
            changes.append(f"root: {k} を削除")

    new_scenes = []
    for i, scene in enumerate(new_sp.get("scenes") or []):
        s = dict(scene)
        wardrobe_id: str | None = None
        wardrobe_obj = s.get("wardrobe")
        if isinstance(wardrobe_obj, dict):
            wardrobe_id = wardrobe_obj.get("identifier") or None
        # wardrobe_tag フィールドからも吸い上げる (新スキーマ移行中の中間形式)
        if not wardrobe_id and isinstance(s.get("wardrobe_tag"), str):
            wardrobe_id = s["wardrobe_tag"]

        for k in SCENE_KEYS_TO_REMOVE:
            if k in s:
                del s[k]
                changes.append(f"scenes[{i}]: {k} を削除")

        if rewrite_refs and wardrobe_id:
            refs = list(s.get("character_refs") or [])
            new_refs: list[str] = []
            for r in refs:
                base = _normalize_base_ref(r)
                new_ref = f"{base}__{wardrobe_id}"
                if new_ref != r:
                    changes.append(
                        f"scenes[{i}]: character_refs {r!r} → {new_ref!r}",
                    )
                new_refs.append(new_ref)
            if new_refs:
                s["character_refs"] = new_refs
            chars = list(s.get("characters") or [])
            if chars and len(chars) == len(new_refs):
                fixed = []
                for c, nr in zip(chars, new_refs):
                    cc = dict(c)
                    cc["name"] = nr
                    fixed.append(cc)
                s["characters"] = fixed

        chars_for_role = list(s.get("characters") or [])
        if chars_for_role:
            cleaned = []
            for c in chars_for_role:
                if "role" in c:
                    cc = dict(c)
                    del cc["role"]
                    cleaned.append(cc)
                    changes.append(f"scenes[{i}]: characters[].role を削除")
                else:
                    cleaned.append(c)
            s["characters"] = cleaned

        new_scenes.append(s)
    new_sp["scenes"] = new_scenes
    return new_sp, changes


def _atomic_write(path: str, sp: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sp, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true", help="実際に書き換え (default: dry-run)")
    p.add_argument(
        "--rewrite-refs", action="store_true",
        help="character_refs / characters[].name を <base>__<wardrobe>.png 形式に書き換え",
    )
    p.add_argument("--ts", help="特定 TS のみ対象")
    p.add_argument("-v", "--verbose", action="store_true", help="DEBUG ログ")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    pattern = (
        f"temp/{args.ts}/screenplay.json"
        if args.ts
        else "temp/*/screenplay.json"
    )
    paths = sorted(glob(os.path.join(ROOT, pattern)))
    if not paths:
        logger.error("対象なし (pattern=%s)", pattern)
        return 1

    total_changes = 0
    touched = 0
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                sp = json.load(f)
        except Exception as e:
            logger.error("読み込み失敗 %s: %s", path, e)
            continue
        new_sp, changes = _migrate_one(sp, rewrite_refs=args.rewrite_refs)
        rel = os.path.relpath(path, ROOT)
        if not changes:
            logger.debug("変更なし: %s", rel)
            continue
        touched += 1
        total_changes += len(changes)
        print(f"\n=== {rel} ===")
        for c in changes:
            print(f"  - {c}")
        if args.apply:
            _atomic_write(path, new_sp)
            print(f"  ✓ 書き戻し完了")

    print(
        f"\n対象 snapshot: {len(paths)} 件 / 変更あり: {touched} 件 / "
        f"合計変更数: {total_changes}",
    )
    if not args.apply:
        print("(dry-run。実際に書き換えるには --apply を付与)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
