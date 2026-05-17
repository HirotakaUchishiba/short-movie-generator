"""scripts/migrate_intent_suggestions のユニットテスト。

設計 doc: docs/plannings/2026-05-10_intent-suggestion-flow.md §6 Phase 4
"""

from __future__ import annotations

import json
from pathlib import Path

from analyze import suggestion_store
from scripts.migrate_intent_suggestions import run as migrate_run


def _write_legacy(
    sd: Path,
    name: str,
    items: list[dict],
) -> Path:
    p = sd / f"{name}.suggested_intents.json"
    p.write_text(
        json.dumps({"suggested_intents": items}, ensure_ascii=False),
        encoding="utf-8",
    )
    return p


# ───────────── 基本動作 ─────────────


class TestMigrateRun:
    def test_no_files_returns_zeros(self, tmp_path: Path) -> None:
        sd = tmp_path / "screenplays"
        sd.mkdir()
        s = migrate_run(
            screenplays_dir=sd,
            archive_dir=tmp_path / "archive",
        )
        assert s["files_scanned"] == 0
        assert s["files_migrated"] == 0
        assert s["entries_upserted"] == 0
        assert s["entries_failed"] == 0

    def test_single_file_migrates_to_inbox(self, tmp_path: Path) -> None:
        sd = tmp_path / "screenplays"
        sd.mkdir()
        ad = tmp_path / "archive"
        legacy = _write_legacy(
            sd, "auto_x",
            [
                {
                    "proposed_id": "frantic_typing",
                    "description": "subject types",
                    "scene_indices": [1, 2],
                    "rationale": "no good match",
                }
            ],
        )
        summary = migrate_run(screenplays_dir=sd, archive_dir=ad)
        assert summary["files_scanned"] == 1
        assert summary["files_migrated"] == 1
        assert summary["entries_upserted"] == 1
        assert summary["entries_failed"] == 0
        # inbox に入っている
        inbox = suggestion_store.load()
        assert len(inbox) == 1
        assert inbox[0].proposed_id == "frantic_typing"
        # 元 file は archive に移動済み
        assert not legacy.exists()
        archived = list(ad.glob("*.json"))
        assert len(archived) == 1

    def test_dry_run_does_not_modify_anything(self, tmp_path: Path) -> None:
        sd = tmp_path / "screenplays"
        sd.mkdir()
        ad = tmp_path / "archive"
        legacy = _write_legacy(
            sd, "auto_x",
            [{"proposed_id": "x", "description": "d", "scene_indices": [0]}],
        )
        summary = migrate_run(
            screenplays_dir=sd, archive_dir=ad, dry_run=True
        )
        assert summary["files_scanned"] == 1
        assert summary["entries_upserted"] == 1
        # dry-run なので元 file は残っており、inbox は空、archive も無い
        assert legacy.exists()
        assert suggestion_store.load() == []
        assert not ad.exists() or not list(ad.glob("*"))


class TestMigrateMultipleFiles:
    def test_multiple_files_aggregate(self, tmp_path: Path) -> None:
        sd = tmp_path / "screenplays"
        sd.mkdir()
        ad = tmp_path / "archive"
        _write_legacy(sd, "auto_a",
                      [{"proposed_id": "a", "description": "d1",
                        "scene_indices": [0]}])
        _write_legacy(sd, "auto_b",
                      [{"proposed_id": "b", "description": "d2",
                        "scene_indices": [1]}])
        summary = migrate_run(screenplays_dir=sd, archive_dir=ad)
        assert summary["files_migrated"] == 2
        assert summary["entries_upserted"] == 2
        ids = {r.proposed_id for r in suggestion_store.load()}
        assert ids == {"a", "b"}

    def test_existing_inbox_status_preserved(self, tmp_path: Path) -> None:
        """migrate 前に inbox に dismissed entry がある場合、同 id を migrate しても
        status は dismissed のまま (= upsert の挙動 = 再検出で status は変えない)。"""

        sd = tmp_path / "screenplays"
        sd.mkdir()
        ad = tmp_path / "archive"
        # 先に inbox を作成 + status=dismissed
        suggestion_store.upsert(
            [
                suggestion_store.SuggestionInput(
                    proposed_id="x",
                    description="d",
                    rationale="r",
                    scene_indices=(1,),
                    source_screenplay="x",
                )
            ]
        )
        sid = suggestion_store.compute_id("x", "d")
        suggestion_store.update_status(sid, "dismissed", reason="dup")
        # 同 id を含む legacy file を migrate
        _write_legacy(
            sd, "auto_x",
            [{"proposed_id": "x", "description": "d",
              "scene_indices": [5]}],
        )
        migrate_run(screenplays_dir=sd, archive_dir=ad)
        inbox = suggestion_store.load()
        assert len(inbox) == 1
        assert inbox[0].status == "dismissed"
        assert inbox[0].dismissed_reason == "dup"
        assert inbox[0].occurrences == 2


# ───────────── エラー処理 ─────────────


class TestMigrateErrors:
    def test_corrupted_file_recorded_in_errors(self, tmp_path: Path) -> None:
        sd = tmp_path / "screenplays"
        sd.mkdir()
        ad = tmp_path / "archive"
        bad = sd / "bad.suggested_intents.json"
        bad.write_text("{not valid", encoding="utf-8")
        summary = migrate_run(screenplays_dir=sd, archive_dir=ad)
        # parse 失敗時は items=0 / errors に記録
        assert summary["entries_upserted"] == 0
        assert any("file read/parse failed" in e for e in summary["errors"])  # type: ignore[union-attr]

    def test_invalid_top_level_recorded(self, tmp_path: Path) -> None:
        sd = tmp_path / "screenplays"
        sd.mkdir()
        ad = tmp_path / "archive"
        bad = sd / "bad.suggested_intents.json"
        bad.write_text('"oops"', encoding="utf-8")
        summary = migrate_run(screenplays_dir=sd, archive_dir=ad)
        assert any("top-level is not dict" in e for e in summary["errors"])  # type: ignore[union-attr]

    def test_partial_invalid_entries_keep_valid(self, tmp_path: Path) -> None:
        sd = tmp_path / "screenplays"
        sd.mkdir()
        ad = tmp_path / "archive"
        _write_legacy(
            sd, "auto_mixed",
            [
                {"proposed_id": "good", "description": "d",
                 "scene_indices": [1]},
                "string entry",  # invalid
                {"description": "missing proposed_id"},  # invalid
            ],
        )
        summary = migrate_run(screenplays_dir=sd, archive_dir=ad)
        assert summary["entries_upserted"] == 1
        assert summary["entries_failed"] == 2
        ids = {r.proposed_id for r in suggestion_store.load()}
        assert ids == {"good"}

    def test_archive_collision_uses_timestamp_suffix(
        self, tmp_path: Path
    ) -> None:
        sd = tmp_path / "screenplays"
        sd.mkdir()
        ad = tmp_path / "archive"
        ad.mkdir()
        # archive にすでに同名 file が存在する状態
        (ad / "auto_x.suggested_intents.json").write_text("{}", encoding="utf-8")
        _write_legacy(
            sd, "auto_x",
            [{"proposed_id": "x", "description": "d",
              "scene_indices": [0]}],
        )
        summary = migrate_run(screenplays_dir=sd, archive_dir=ad)
        assert summary["files_migrated"] == 1
        # 衝突回避で 2 file が archive に存在する
        archived = sorted(ad.glob("*"))
        assert len(archived) == 2
