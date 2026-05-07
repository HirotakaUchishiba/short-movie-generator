import json
import os

import pytest


@pytest.fixture
def isolated_qa(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()

    from qa import recorder
    archive_root = tmp_path / "qa_failures"
    monkeypatch.setattr(
        recorder, "qa_failures_root", lambda: str(archive_root),
    )
    return recorder, _db, str(archive_root)


def _make_artifact(tmp_path, name: str, content: bytes = b"x") -> str:
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def test_record_failure_human_reject(isolated_qa, tmp_path) -> None:
    recorder, db, root = isolated_qa
    art = _make_artifact(tmp_path, "bg_2.png", b"PNGDATA")
    snap = _make_artifact(tmp_path, "screenplay.json", b'{"caption":"x"}')

    fid, archive_dir = recorder.record_failure(
        ts="20260507_120000",
        stage="bg",
        source="human_reject",
        tags=["character_drift"],
        note="顔が崩れた",
        scene_idx=2,
        artifact_paths=[art],
        screenplay_snapshot_path=snap,
    )

    assert fid > 0
    assert os.path.isdir(archive_dir)
    assert archive_dir.startswith(root)
    assert os.path.exists(os.path.join(archive_dir, "bg_2.png"))
    assert os.path.exists(os.path.join(archive_dir, "screenplay.json"))

    meta = json.loads(open(os.path.join(archive_dir, "meta.json")).read())
    assert meta["stage"] == "bg"
    assert meta["tags"] == ["character_drift"]
    assert meta["scene_idx"] == 2

    rows = db.list_qa_failures(ts="20260507_120000")
    assert len(rows) == 1
    assert rows[0]["source"] == "human_reject"
    assert rows[0]["tags"] == ["character_drift"]


def test_record_failure_regenerate_implicit_no_tags(isolated_qa) -> None:
    recorder, db, _ = isolated_qa
    fid, _ = recorder.record_failure(
        ts="20260507_130000",
        stage="kling",
        source="regenerate_implicit",
        tags=None,
    )
    assert fid > 0
    rows = db.list_qa_failures(source="regenerate_implicit")
    assert len(rows) == 1
    assert rows[0]["tags"] == []


def test_record_failure_invalid_source(isolated_qa) -> None:
    recorder, _, _ = isolated_qa
    with pytest.raises(ValueError):
        recorder.record_failure(
            ts="t", stage="tts", source="not_a_source", tags=[],
        )


def test_record_failure_invalid_tag(isolated_qa) -> None:
    recorder, _, _ = isolated_qa
    with pytest.raises(ValueError):
        recorder.record_failure(
            ts="t", stage="tts", source="human_reject",
            tags=["not_a_real_tag"],
        )


def test_record_failure_seq_increments(isolated_qa) -> None:
    recorder, db, _ = isolated_qa
    _, dir1 = recorder.record_failure(
        ts="ts1", stage="bg", source="human_reject", tags=[],
    )
    _, dir2 = recorder.record_failure(
        ts="ts1", stage="bg", source="human_reject", tags=[],
    )
    assert dir1 != dir2
    assert dir1.endswith("_0")
    assert dir2.endswith("_1")
    # 別 stage は独立 seq
    _, dir_tts = recorder.record_failure(
        ts="ts1", stage="tts", source="human_reject", tags=[],
    )
    assert dir_tts.endswith("_0")


def test_record_failure_missing_artifact_skipped(isolated_qa, tmp_path) -> None:
    recorder, db, _ = isolated_qa
    fid, archive_dir = recorder.record_failure(
        ts="t", stage="bg", source="human_reject", tags=[],
        artifact_paths=[str(tmp_path / "no_such_file.png")],
    )
    assert fid > 0
    rows = db.list_qa_failures(ts="t")
    assert rows[0]["artifact_path"] is None


def test_record_failure_validates_tag_in_recorder(isolated_qa, tmp_path) -> None:
    recorder, _, _ = isolated_qa
    art = _make_artifact(tmp_path, "x.png")
    with pytest.raises(ValueError):
        recorder.record_failure(
            ts="t", stage="bg", source="human_reject",
            tags=["character_drift", "non_existent_tag"],
            artifact_paths=[art],
        )
