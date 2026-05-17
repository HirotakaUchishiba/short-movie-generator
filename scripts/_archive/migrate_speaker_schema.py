"""旧 speaker schema (= speaker_to_ref + speaker_profiles + raw speaker_N) を
撤廃し、line.speaker に resolved id を直書きする新 schema へ変換する。

設計 doc: docs/plannings/2026-05-17_drop-speaker-mapping-schema.md

実行例:
  # dry-run (= 変換結果を表示するだけ、書き込まない)
  python3 scripts/migrate_speaker_schema.py --dry-run

  # 全 project + 全 template に対して書き込み
  python3 scripts/migrate_speaker_schema.py

  # 個別 file
  python3 scripts/migrate_speaker_schema.py path/to/screenplay.json

idempotency: 既に新 schema (= raw 形式無し + speaker_to_ref / speaker_profiles
不在) なら何もしない。複数回実行しても安全。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

RAW_SPEAKER_RE = re.compile(r"^speaker_\d+$", re.IGNORECASE)


def _is_raw_speaker(value: object) -> bool:
    return isinstance(value, str) and bool(RAW_SPEAKER_RE.match(value))


def migrate_one(sp: dict) -> tuple[dict, dict]:
    """1 screenplay dict を新 schema に変換 (= in-place 風に新 dict を返す)。

    Returns:
        (new_sp, stats)
        stats = {
          "speaker_to_ref_dropped": bool,
          "speaker_profiles_dropped": bool,
          "lines_resolved_from_mapping": int,
          "lines_stripped_unmappable": int,
          "lines_already_resolved": int,
        }
    """

    stats = {
        "speaker_to_ref_dropped": False,
        "speaker_profiles_dropped": False,
        "lines_resolved_from_mapping": 0,
        "lines_stripped_unmappable": 0,
        "lines_already_resolved": 0,
    }

    out = dict(sp)
    speaker_to_ref = out.pop("speaker_to_ref", None)
    speaker_profiles = out.pop("speaker_profiles", None)
    if speaker_to_ref is not None:
        stats["speaker_to_ref_dropped"] = True
    if speaker_profiles is not None:
        stats["speaker_profiles_dropped"] = True

    mapping: dict[str, str] = {}
    if isinstance(speaker_to_ref, dict):
        for k, v in speaker_to_ref.items():
            if isinstance(k, str) and isinstance(v, str) and v:
                mapping[k] = v

    new_scenes: list[dict] = []
    for scene in out.get("scenes") or []:
        if not isinstance(scene, dict):
            new_scenes.append(scene)
            continue
        new_scene = dict(scene)
        new_lines: list[dict] = []
        for line in scene.get("lines") or []:
            if not isinstance(line, dict):
                new_lines.append(line)
                continue
            new_line = dict(line)
            sp_val = line.get("speaker")
            if sp_val is None or sp_val == "":
                pass  # 未設定はそのまま
            elif _is_raw_speaker(sp_val):
                resolved = mapping.get(sp_val)
                if resolved:
                    new_line["speaker"] = resolved
                    stats["lines_resolved_from_mapping"] += 1
                else:
                    new_line["speaker"] = None
                    stats["lines_stripped_unmappable"] += 1
            else:
                stats["lines_already_resolved"] += 1
            new_lines.append(new_line)
        new_scene["lines"] = new_lines
        new_scenes.append(new_scene)
    out["scenes"] = new_scenes
    return out, stats


def _needs_migration(sp: dict) -> bool:
    """この screenplay は移行対象か (= 何かしら旧 schema の残骸を持つか)。"""
    if "speaker_to_ref" in sp:
        return True
    if "speaker_profiles" in sp:
        return True
    for scene in sp.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for line in scene.get("lines") or []:
            if not isinstance(line, dict):
                continue
            if _is_raw_speaker(line.get("speaker")):
                return True
    return False


def migrate_file(path: Path, *, dry_run: bool) -> dict:
    """1 ファイルを migration。stats + skipped/migrated flag を返す。"""
    try:
        with path.open(encoding="utf-8") as f:
            sp = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {"path": str(path), "status": "error", "error": str(e)}
    if not isinstance(sp, dict):
        return {"path": str(path), "status": "error", "error": "not a dict"}
    if not _needs_migration(sp):
        return {"path": str(path), "status": "skipped",
                "reason": "already new schema"}
    new_sp, stats = migrate_one(sp)
    result = {
        "path": str(path),
        "status": "migrated" if not dry_run else "dry_run",
        "stats": stats,
    }
    if not dry_run:
        with path.open("w", encoding="utf-8") as f:
            json.dump(new_sp, f, ensure_ascii=False, indent=2)
    return result


def _candidate_files() -> list[Path]:
    """REPO_ROOT 配下の対象ファイル一覧 (= temp/*/screenplay.json + screenplays/*.json)。"""
    out: list[Path] = []
    for tdir in (REPO_ROOT / "temp").glob("*"):
        if tdir.is_dir():
            sp = tdir / "screenplay.json"
            if sp.exists():
                out.append(sp)
    for sp in (REPO_ROOT / "screenplays").glob("*.json"):
        if sp.is_file():
            out.append(sp)
    return sorted(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="*",
                    help="個別 file path (= 省略時は temp/ + screenplays/ を一括処理)")
    ap.add_argument("--dry-run", action="store_true",
                    help="変換結果のみ表示、書き込みしない")
    ap.add_argument("--quiet", action="store_true",
                    help="skipped のログを抑制")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if args.paths:
        targets = [Path(p).resolve() for p in args.paths]
    else:
        targets = _candidate_files()

    if not targets:
        logger.info("対象ファイル無し")
        return 0

    summary = {"migrated": 0, "dry_run": 0, "skipped": 0, "error": 0}
    for path in targets:
        result = migrate_file(path, dry_run=args.dry_run)
        status = result["status"]
        summary[status] = summary.get(status, 0) + 1
        if status in ("migrated", "dry_run"):
            stats = result["stats"]
            logger.info(
                "[%s] %s: speaker_to_ref_dropped=%s "
                "speaker_profiles_dropped=%s "
                "lines_resolved=%d stripped=%d already_resolved=%d",
                status, os.path.relpath(path, REPO_ROOT),
                stats["speaker_to_ref_dropped"],
                stats["speaker_profiles_dropped"],
                stats["lines_resolved_from_mapping"],
                stats["lines_stripped_unmappable"],
                stats["lines_already_resolved"],
            )
        elif status == "skipped" and not args.quiet:
            logger.info("[skipped] %s: %s",
                        os.path.relpath(path, REPO_ROOT),
                        result.get("reason", ""))
        elif status == "error":
            logger.error("[error] %s: %s",
                         os.path.relpath(path, REPO_ROOT),
                         result.get("error", ""))

    logger.info(
        "完了: migrated=%d dry_run=%d skipped=%d error=%d",
        summary.get("migrated", 0),
        summary.get("dry_run", 0),
        summary.get("skipped", 0),
        summary.get("error", 0),
    )
    return 0 if summary.get("error", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
