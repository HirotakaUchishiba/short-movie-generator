"""characters/ ディレクトリを新ネスト構造 + 抽象 ID に移行する。

旧:
  characters/female_engineer.png
  characters/female_engineer__office_outfit.json   ← voice メタが衣装ごとに重複
  characters/male_engineer.png

新:
  characters/f1/
    voice.json                ← voice メタは base 単位で 1 つ
    base.png                  ← (= 旧 female_engineer.png)
    office_outfit.png         ← 衣装バリアント (※ 旧 layout には PNG 無し)
  characters/m1/
    voice.json
    base.png

旧 voice JSON が複数衣装で異なる stability を持っていた場合は **最初に見つけた
ものを採用** する (= base 単位で 1 つしか持てないため)。差分は警告ログに残す。

実行:
  python3 scripts/migrate_characters_layout.py            # dry-run
  python3 scripts/migrate_characters_layout.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config

CHARACTERS_DIR = Path(config.CHARACTERS_DIR)

# 旧名 → 新 base ID の対応表 (= ユーザが明示的に決めた抽象 ID)
RENAME_MAP: dict[str, str] = {
    "female_engineer": "f1",
    "male_engineer": "m1",
}


def _resolve_new_base(old_id: str) -> str:
    """旧 ID (resolved or base) から新 base ID を決定。"""
    base = old_id.split("__", 1)[0]
    return RENAME_MAP.get(base, base)


def _resolve_wardrobe(old_id: str) -> str | None:
    if "__" in old_id:
        _, wardrobe = old_id.split("__", 1)
        return wardrobe or None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="実際にファイル移動を実行する (= 既定は dry-run)")
    args = ap.parse_args()

    if not CHARACTERS_DIR.is_dir():
        print(f"characters/ が見つかりません: {CHARACTERS_DIR}")
        return 1

    pngs = sorted(p for p in CHARACTERS_DIR.glob("*.png") if p.is_file())
    jsons = sorted(p for p in CHARACTERS_DIR.glob("*.json") if p.is_file())

    moves: list[tuple[Path, Path]] = []
    voice_by_base: dict[str, dict] = {}

    print("== 旧構造から検出 ==")
    for p in pngs:
        old_id = p.stem
        new_base = _resolve_new_base(old_id)
        wardrobe = _resolve_wardrobe(old_id)
        new_name = (
            f"{wardrobe}.png" if wardrobe else "base.png"
        )
        dst = CHARACTERS_DIR / new_base / new_name
        moves.append((p, dst))
        print(f"  PNG  {p.name}  →  {new_base}/{new_name}")

    print()
    print("== 旧 voice JSON を base 単位に集約 ==")
    for p in jsons:
        old_id = p.stem
        new_base = _resolve_new_base(old_id)
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        voice = dict(d.get("voice_overrides") or {})
        if new_base in voice_by_base:
            existing = voice_by_base[new_base]
            if existing != voice:
                print(
                    f"  ⚠ {p.name} の voice_overrides が "
                    f"{new_base}/voice.json の既存値と差異。最初の値を採用 "
                    f"(差: existing={existing}, dropped={voice})"
                )
            continue
        voice_by_base[new_base] = voice
        print(f"  JSON {p.name}  →  {new_base}/voice.json  ({voice})")

    print()
    print("== サマリ ==")
    print(f"  移動する PNG      : {len(moves)}")
    print(f"  voice.json 出力数 : {len(voice_by_base)}")
    print(f"  旧 JSON 削除数    : {len(jsons)}")

    if not args.apply:
        print()
        print("--apply で実行")
        return 0

    print()
    print("== 実行 ==")
    for src, dst in moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            print(f"  skip (既存): {dst.relative_to(ROOT)}")
            continue
        shutil.move(str(src), str(dst))
        print(f"  ✓ moved {src.relative_to(ROOT)} → {dst.relative_to(ROOT)}")

    for base, voice in voice_by_base.items():
        d = CHARACTERS_DIR / base
        d.mkdir(parents=True, exist_ok=True)
        out = d / "voice.json"
        if out.exists():
            print(f"  skip (既存): {out.relative_to(ROOT)}")
            continue
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"id": base, "voice_overrides": voice}, f,
                      ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"  ✓ wrote {out.relative_to(ROOT)}")

    for p in jsons:
        if p.exists():
            os.remove(p)
            print(f"  ✓ removed {p.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
