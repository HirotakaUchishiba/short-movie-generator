#!/usr/bin/env python3
"""screenplays/*.suggested_intents.json を data/intent_suggestions.json に吸い上げる。

旧 single-file write 経路 (= analyze/pipeline.py が screenplay 出力ディレクトリに
書いていた個別 JSON) を inbox に統合するための one-shot migration。

使い方:
    python3 scripts/migrate_intent_suggestions.py            # 実行
    python3 scripts/migrate_intent_suggestions.py --dry-run  # 検出のみ

挙動:
  1. ``screenplays/*.suggested_intents.json`` を全 scan
  2. 各 entry を ``IntentSuggestionRecord`` に変換 → ``upsert`` (= 既存 inbox の
     status は保持される)
  3. 元ファイルを ``data/intent_suggestions_archive/<timestamp>/`` に move
  4. 失敗 entry は ``data/intent_suggestions.errors.log`` に記録 (= best-effort)

設計 doc: docs/plannings/2026-05-10_intent-suggestion-flow.md §6 Phase 4
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import config
from analyze import suggestion_store
from analyze.suggestion_store import SuggestionInput

logger = logging.getLogger(__name__)


def _iter_legacy_files(screenplays_dir: Path) -> list[Path]:
    """``screenplays/*.suggested_intents.json`` を全 scan して返す。"""

    if not screenplays_dir.exists():
        return []
    return sorted(screenplays_dir.glob("*.suggested_intents.json"))


def _load_legacy_file(p: Path) -> tuple[list[SuggestionInput], list[str]]:
    """1 file を読み込んで SuggestionInput 列に変換。

    第 2 戻り値はエラーメッセージ列 (= 各 entry が parse 失敗した場合の理由)。
    """

    inputs: list[SuggestionInput] = []
    errors: list[str] = []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        errors.append(f"{p}: file read/parse failed: {e}")
        return [], errors
    if not isinstance(raw, dict):
        errors.append(f"{p}: top-level is not dict")
        return [], errors
    items = raw.get("suggested_intents") or []
    if not isinstance(items, list):
        errors.append(f"{p}: suggested_intents is not list")
        return [], errors
    # 元 screenplay path は file 名から逆算 (= `auto_xyz.suggested_intents.json`
    # → `screenplays/auto_xyz.json`)
    src = str(p.with_suffix("").with_suffix(".json"))
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"{p}#{idx}: not a dict")
            continue
        try:
            inputs.append(
                SuggestionInput(
                    proposed_id=str(item["proposed_id"]),
                    description=str(item.get("description") or ""),
                    rationale=str(item.get("rationale") or ""),
                    scene_indices=tuple(
                        int(i) for i in item.get("scene_indices") or []
                    ),
                    source_screenplay=src,
                    source_analyze_job_id=None,
                )
            )
        except (KeyError, ValueError, TypeError) as e:
            errors.append(f"{p}#{idx}: invalid entry: {e}")
    return inputs, errors


def _archive_file(p: Path, archive_dir: Path) -> Path:
    """元 file を archive dir に move して新 path を返す。

    archive dir が無ければ作成。同名 file が既存なら timestamp suffix で衝突回避。
    """

    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / p.name
    if target.exists():
        stem = p.stem  # = e.g. "auto_xyz.suggested_intents"
        suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target = archive_dir / f"{stem}.{suffix}.json"
    shutil.move(str(p), str(target))
    return target


def _append_error_log(errors: list[str]) -> None:
    """失敗 entry を errors.log に追記 (= best-effort、書き込み失敗は warning だけ)。"""

    if not errors:
        return
    log_path = Path(config.INTENT_SUGGESTIONS_PATH).with_name(
        "intent_suggestions.errors.log"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with log_path.open("a", encoding="utf-8") as f:
            for line in errors:
                f.write(f"{ts}\t{line}\n")
    except OSError as e:
        logger.warning("[migrate] errors.log write failed: %s", e)


def run(
    *,
    screenplays_dir: Path | str = "screenplays",
    archive_dir: Path | str | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    """migration を実行し、結果サマリ dict を返す。

    返り値:
      {
        "files_scanned": int,
        "files_migrated": int,
        "entries_upserted": int,
        "entries_failed": int,
        "errors": [str, ...],
        "archived": [str, ...],   # 移動先 path のリスト
        "dry_run": bool,
      }
    """

    sd = Path(screenplays_dir)
    ad = Path(archive_dir) if archive_dir else Path(
        config.INTENT_SUGGESTIONS_ARCHIVE_DIR
    )
    legacy = _iter_legacy_files(sd)
    summary: dict[str, object] = {
        "files_scanned": len(legacy),
        "files_migrated": 0,
        "entries_upserted": 0,
        "entries_failed": 0,
        "errors": [],
        "archived": [],
        "dry_run": dry_run,
    }
    if not legacy:
        return summary

    all_errors: list[str] = []
    for p in legacy:
        inputs, file_errors = _load_legacy_file(p)
        all_errors.extend(file_errors)
        summary["entries_failed"] = int(summary["entries_failed"]) + len(file_errors)
        if dry_run:
            summary["entries_upserted"] = (
                int(summary["entries_upserted"]) + len(inputs)
            )
            continue
        if inputs:
            try:
                suggestion_store.upsert(inputs)
                summary["entries_upserted"] = (
                    int(summary["entries_upserted"]) + len(inputs)
                )
            except (OSError, ValueError, TypeError) as e:
                all_errors.append(f"{p}: upsert failed: {e}")
                summary["entries_failed"] = (
                    int(summary["entries_failed"]) + len(inputs)
                )
                continue
        # 元 file を archive に移動 (= 再実行で重複 upsert を避ける)
        try:
            archived = _archive_file(p, ad)
            summary["files_migrated"] = int(summary["files_migrated"]) + 1
            summary["archived"].append(str(archived))  # type: ignore[union-attr]
        except OSError as e:
            all_errors.append(f"{p}: archive failed: {e}")

    if not dry_run:
        _append_error_log(all_errors)
    summary["errors"] = all_errors
    return summary


def _format_summary(s: dict[str, object]) -> str:
    return (
        f"[migrate_intent_suggestions]"
        f" scanned={s['files_scanned']}"
        f" migrated={s['files_migrated']}"
        f" upserted={s['entries_upserted']}"
        f" failed={s['entries_failed']}"
        f" dry_run={s['dry_run']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="検出のみ。inbox は更新しない / archive 移動もしない",
    )
    parser.add_argument(
        "--screenplays-dir",
        default="screenplays",
        help="scan 対象ディレクトリ (default: screenplays)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    summary = run(
        screenplays_dir=args.screenplays_dir,
        dry_run=bool(args.dry_run),
    )
    print(_format_summary(summary))
    if summary["errors"]:
        print("[migrate] errors (= 詳細は data/intent_suggestions.errors.log):")
        for e in summary["errors"]:  # type: ignore[union-attr]
            print(f"  - {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
