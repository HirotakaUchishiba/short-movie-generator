"""project snapshot の speaker / characters[].name を ref ベースに変換する。

VideoStyle 経由で name → ref をルックアップして書き換える。マッチしない speaker
は警告のみ。abstract (= screenplays/auto_*.json) は snapshot にコピーされる
ので同様に走査する。characters[].role があれば削除する。

dry-run がデフォルト。--apply を付けると実書き込み。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import config  # noqa: E402
from analyze import style as _style  # noqa: E402


# プロジェクト既知の name → ref 固定マップ。新しい値が必要なら追記する。
NAME_TO_REF: dict[str, str] = {
    "主人公": "female_engineer",
    "上司": "male_engineer",
}


def build_name_to_ref_table() -> dict[str, str]:
    """固定マップ + 全 VideoStyle から {name: ref} 辞書を合成する。"""
    table: dict[str, str] = dict(NAME_TO_REF)
    for sname in _style.list_styles():
        try:
            s = _style.load_style(sname)
        except Exception as e:
            logger.warning("style %s 読み込み失敗: %s", sname, e)
            continue
        for c in s.characters:
            if c.name and c.ref and c.name != c.ref:
                if c.name in table and table[c.name] != c.ref:
                    logger.warning(
                        "name '%s' が複数 ref に紐付き: %s, %s "
                        "(後者を採用)",
                        c.name, table[c.name], c.ref,
                    )
                table[c.name] = c.ref
    return table


def migrate_screenplay_dict(
    sp: dict, name_to_ref: dict[str, str],
) -> tuple[bool, list[str]]:
    """screenplay dict を in-place で書き換える。
    Returns: (変更があったか, 未解決 speaker のログ list)"""
    is_changed = False
    unresolved: list[str] = []

    def map_value(v: str) -> str:
        nonlocal is_changed
        if v in name_to_ref:
            mapped = name_to_ref[v]
            if mapped != v:
                is_changed = True
                return mapped
        return v

    for s_idx, scene in enumerate(sp.get("scenes") or []):
        # scene.characters[].name を ref に置換。role フィールドは削除。
        for c in scene.get("characters") or []:
            old_name = c.get("name")
            if old_name and old_name in name_to_ref:
                c["name"] = name_to_ref[old_name]
                is_changed = True
            if "role" in c:
                del c["role"]
                is_changed = True
        # scene.character_selection の name → ref 置換
        if "character_selection" in scene and isinstance(
            scene["character_selection"], list,
        ):
            new_sel = [map_value(x) for x in scene["character_selection"]]
            if new_sel != scene["character_selection"]:
                scene["character_selection"] = new_sel
                is_changed = True
        # lines[].speaker
        for l_idx, line in enumerate(scene.get("lines") or []):
            sp_val = line.get("speaker")
            if not sp_val:
                continue
            if sp_val in name_to_ref:
                line["speaker"] = name_to_ref[sp_val]
                is_changed = True
            elif sp_val.startswith("speaker_"):
                # 匿名 ID は abstract.speaker_to_ref で解決される想定
                pass
            elif sp_val not in {c.get("name") for c in scene.get("characters") or []}:
                # 既に ref の可能性 (= scene.characters[].name と一致するなら ref)
                # それ以外は未解決
                unresolved.append(
                    f"scene[{s_idx}].lines[{l_idx}].speaker='{sp_val}'",
                )

    return is_changed, unresolved


def migrate_file(
    path: Path, name_to_ref: dict[str, str], apply: bool,
) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error("読込失敗 %s: %s", path, e)
        return False
    is_changed, unresolved = migrate_screenplay_dict(data, name_to_ref)
    if not is_changed:
        logger.info("変更なし: %s", path)
        return False
    for u in unresolved:
        logger.warning("  未解決 %s in %s", u, path)
    if apply:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        tmp.replace(path)
        logger.info("✅ 書き込み: %s", path)
    else:
        logger.info("[dry-run] 変更あり: %s", path)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="実書き込み (省略時は dry-run)")
    ap.add_argument("--temp-dir", default=None,
                    help="project snapshot ディレクトリ (既定: temp/)")
    ap.add_argument("--screenplays-dir", default=None,
                    help="抽象台本ディレクトリ (既定: screenplays/)")
    args = ap.parse_args()

    name_to_ref = build_name_to_ref_table()
    logger.info("name → ref テーブル (%d エントリ): %s",
                len(name_to_ref), name_to_ref)
    if not name_to_ref:
        logger.warning("マッピング対象が無いので何もしません")
        return 0

    temp_dir = Path(args.temp_dir or os.path.join(REPO_ROOT, "temp"))
    sp_dir = Path(args.screenplays_dir or config.SCREENPLAYS_DIR)

    targets: list[Path] = []
    # snapshot
    if temp_dir.is_dir():
        for ts_dir in sorted(temp_dir.iterdir()):
            if not ts_dir.is_dir():
                continue
            sp_path = ts_dir / "screenplay.json"
            if sp_path.exists():
                targets.append(sp_path)
    # abstract
    if sp_dir.is_dir():
        for f in sorted(sp_dir.glob("auto_*.json")):
            targets.append(f)

    logger.info("移行対象 %d ファイル", len(targets))
    n_is_changed = 0
    for p in targets:
        if migrate_file(p, name_to_ref, args.apply):
            n_is_changed += 1
    logger.info(
        "完了 (変更 %d / 全 %d)%s",
        n_is_changed, len(targets), "" if args.apply else " [dry-run]",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
