#!/usr/bin/env python3
"""screenplays/*.json と screenplays/drafts/*.json から下記フィールドを除去する。

  - root: audio_mode, bgm_path, bgm_volume_db
  - scenes[]: label, emotion_cue_overrides
  - lines[]: silence_after_ms

styles/ や VideoStyle ファイルは対象外 (別 schema)。

使い方:
    python3 scripts/migrate_screenplay_v3.py            # dry-run
    python3 scripts/migrate_screenplay_v3.py --apply    # 上書き保存
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ROOT_DROP = ("audio_mode", "bgm_path", "bgm_volume_db")
SCENE_DROP = ("label", "emotion_cue_overrides")
LINE_DROP = ("silence_after_ms",)


def _strip(screenplay: dict) -> list[str]:
    removed: list[str] = []
    for k in ROOT_DROP:
        if k in screenplay:
            screenplay.pop(k)
            removed.append(k)
    for s_idx, scene in enumerate(screenplay.get("scenes") or []):
        for k in SCENE_DROP:
            if k in scene:
                scene.pop(k)
                removed.append(f"scenes[{s_idx}].{k}")
        for l_idx, line in enumerate(scene.get("lines") or []):
            for k in LINE_DROP:
                if k in line:
                    line.pop(k)
                    removed.append(f"scenes[{s_idx}].lines[{l_idx}].{k}")
    return removed


def _iter_targets() -> list[Path]:
    targets: list[Path] = []
    for d in (ROOT / "screenplays", ROOT / "screenplays" / "drafts"):
        if d.is_dir():
            targets.extend(
                sorted(p for p in d.glob("*.json") if p.is_file()),
            )
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="変更を上書き保存する (指定なければ dry-run)")
    args = parser.parse_args()

    paths = _iter_targets()
    if not paths:
        print("台本ファイルが見つかりません", file=sys.stderr)
        return 1

    total = 0
    changed = 0
    for p in paths:
        try:
            with p.open("r", encoding="utf-8") as f:
                sp = json.load(f)
        except Exception as e:
            print(f"[skip] {p}: {e}", file=sys.stderr)
            continue
        removed = _strip(sp)
        if not removed:
            print(f"[ok]   {p.relative_to(ROOT)} (変更なし)")
            continue
        total += len(removed)
        changed += 1
        print(f"[diff] {p.relative_to(ROOT)} ({len(removed)}件削除)")
        for r in removed:
            print(f"       - {r}")
        if args.apply:
            with p.open("w", encoding="utf-8") as f:
                json.dump(sp, f, ensure_ascii=False, indent=2)
                f.write("\n")
    print()
    print(f"合計 {total} フィールド / {changed} ファイルを削除"
          f"{' (適用済み)' if args.apply else ' (dry-run)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
