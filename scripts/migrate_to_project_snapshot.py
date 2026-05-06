"""project snapshot 構造に未移行の temp/<TS>/ を以下の形に揃える。

  metadata.screenplay_path = "screenplay.json" (project 相対)
  temp/<TS>/screenplay.json (immutable snapshot) を作成

処理:
  1. temp/<TS>/ を全部走査
  2. metadata.screenplay_path を drafts → canonical → 絶対パス の順に解決
  3. その内容を temp/<TS>/screenplay.json に snapshot コピー
  4. metadata.json を screenplay_template_name 追加 / screenplay_path = "screenplay.json"
     / screenplay_sha256 を再計算する形で書き換え

冪等。screenplay.json が既にあって sha 一致ならスキップ。dry-run 既定。
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

PROJECT_FILE = "screenplay.json"


def _resolve_template(meta_path: str) -> str | None:
    """metadata.screenplay_path を実ファイルに解決する。
    "screenplays/drafts/foo.json" などの相対 or 絶対パスを順に試す。
    drafts に同名があれば drafts を優先する。
    """
    if not meta_path:
        return None
    cands: list[str] = []
    if os.path.isabs(meta_path):
        cands.append(meta_path)
    else:
        cands.append(os.path.join(config.BASE_DIR, meta_path))
    name = os.path.basename(meta_path)
    drafts = os.path.join(config.SCREENPLAYS_DIR, "drafts", name)
    canonical = os.path.join(config.SCREENPLAYS_DIR, name)
    cands = [drafts, canonical] + cands
    for p in cands:
        if os.path.exists(p):
            return p
    return None


def _migrate_one(ts_dir: Path, apply: bool) -> str:
    """1 project を移行。返り値はステータス文字列。"""
    meta_path = ts_dir / "metadata.json"
    if not meta_path.exists():
        return "no-metadata"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    snap_path = ts_dir / PROJECT_FILE

    # snapshot 存在 + sha 一致なら何もしない
    if (
        meta.get("screenplay_path") == PROJECT_FILE
        and snap_path.exists()
    ):
        actual_sha = hashlib.sha256(snap_path.read_bytes()).hexdigest()
        if actual_sha == meta.get("screenplay_sha256"):
            return "already-migrated"

    src = _resolve_template(meta.get("screenplay_path"))
    if not src:
        return f"template-not-found: {meta.get('screenplay_path')}"

    template_name = (
        meta.get("screenplay_template_name")
        or meta.get("screenplay_name")
        or os.path.basename(src)
    )
    raw = Path(src).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()

    new_meta = dict(meta)
    new_meta["screenplay_template_name"] = template_name
    new_meta["screenplay_name"] = template_name
    new_meta["screenplay_path"] = PROJECT_FILE
    new_meta["screenplay_sha256"] = sha

    if not apply:
        return f"would-migrate (src={src} sha={sha[:12]} scenes={len(json.loads(raw).get('scenes') or [])})"

    snap_path.write_bytes(raw)
    meta_path.write_text(
        json.dumps(new_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return f"migrated (src={src} sha={sha[:12]})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="実際に書き込む (既定は dry-run)")
    args = parser.parse_args()

    temp_dir = Path(config.TEMP_DIR)
    if not temp_dir.is_dir():
        print(f"temp_dir 無し: {temp_dir}", file=sys.stderr)
        return 1

    counts = {"already-migrated": 0, "migrated": 0, "would-migrate": 0,
              "no-metadata": 0, "error": 0}
    for ts_dir in sorted(temp_dir.iterdir()):
        if not ts_dir.is_dir():
            continue
        try:
            result = _migrate_one(ts_dir, args.apply)
        except Exception as e:
            result = f"error: {e}"
        kind = result.split()[0].rstrip(":")
        counts[kind] = counts.get(kind, 0) + 1
        marker = "[apply]" if args.apply else "[dryrun]"
        print(f"{marker} {ts_dir.name}: {result}")

    print()
    print("== summary ==")
    for k, v in counts.items():
        if v:
            print(f"  {k}: {v}")
    if not args.apply:
        print("\n--apply を付けると実書き込み。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
