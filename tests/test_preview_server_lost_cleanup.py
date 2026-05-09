"""_recover_lost_jobs が lost flip 時に partial artifact を掃除することを検証。

サーバが mid-stage で落ちると stage runner が atomic write 用に書きかけた
``.tmp`` 系ファイルが残る。次の resume が同じ stage を再実行する前に
``_cleanup_partial_artifacts`` で破棄しておく。
"""
from pathlib import Path

import pytest

import preview_server


@pytest.fixture(autouse=True)
def _isolate_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(preview_server.config, "TEMP_DIR",
                          str(tmp_path / "temp"))
    monkeypatch.setattr(preview_server, "TEMP_DIR", str(tmp_path / "temp"))
    yield


def test_cleanup_partial_artifacts_removes_tmp_files(tmp_path):
    ts = "20260507_120000"
    ts_path = Path(preview_server._ts_path(ts))
    ts_path.mkdir(parents=True)

    # `.tmp` 系の partial artifact
    (ts_path / "tts_full.tmp.mp3").write_bytes(b"x")
    (ts_path / "tts_full.tmp.json").write_text("[]")
    (ts_path / "scene_001.tmp.mp4").write_bytes(b"x")
    (ts_path / "scene_002.tmp").write_bytes(b"x")

    # 通常の artifact (= 残るべき)
    (ts_path / "tts_full.mp3").write_bytes(b"keep")
    (ts_path / "kling_000.mp4").write_bytes(b"keep")
    (ts_path / "bg_000.png").write_bytes(b"keep")

    removed = preview_server._cleanup_partial_artifacts(ts)

    assert "tts_full.tmp.mp3" in removed
    assert "tts_full.tmp.json" in removed
    assert "scene_001.tmp.mp4" in removed
    assert "scene_002.tmp" in removed

    # 通常 artifact は残る
    assert (ts_path / "tts_full.mp3").exists()
    assert (ts_path / "kling_000.mp4").exists()
    assert (ts_path / "bg_000.png").exists()


def test_cleanup_partial_artifacts_no_temp_dir():
    """ts ディレクトリが無ければ no-op (= 例外なし)。"""
    removed = preview_server._cleanup_partial_artifacts("99990101_000000")
    assert removed == []


def test_cleanup_partial_artifacts_empty_ts():
    """空 ts は no-op。"""
    assert preview_server._cleanup_partial_artifacts("") == []


def test_recover_lost_jobs_cleans_up_each_lost_ts(monkeypatch):
    """lost に flip された各 ts について _cleanup_partial_artifacts が呼ばれる。"""
    import job_store

    # クリーンスレートで開始
    monkeypatch.setattr(job_store, "_load", lambda: {"jobs": {}})

    fake_lost = [
        {"id": "j1", "ts": "20260101_010101", "kind": "run-next",
         "status": "lost"},
        {"id": "j2", "ts": "20260202_020202", "kind": "regen-bg",
         "status": "lost"},
        {"id": "j3", "ts": "20260101_010101", "kind": "run-next",
         "status": "lost"},  # 同 ts の重複
    ]
    monkeypatch.setattr(job_store, "recover_lost", lambda: fake_lost)

    cleaned: list[str] = []
    monkeypatch.setattr(
        preview_server, "_cleanup_partial_artifacts",
        lambda ts: cleaned.append(ts) or [],
    )

    preview_server._recover_lost_jobs()
    # 同 ts は 1 回しか cleanup されない (= dedup)
    assert sorted(cleaned) == ["20260101_010101", "20260202_020202"]


def test_recover_lost_jobs_handles_cleanup_exception(monkeypatch, caplog):
    """1 ts の cleanup が落ちても、他の ts の cleanup は継続される。"""
    import job_store
    fake_lost = [
        {"id": "j1", "ts": "20260101_010101"},
        {"id": "j2", "ts": "20260202_020202"},
    ]
    monkeypatch.setattr(job_store, "recover_lost", lambda: fake_lost)

    cleaned: list[str] = []

    def cleanup(ts):
        if ts == "20260101_010101":
            raise RuntimeError("disk full")
        cleaned.append(ts)
        return []

    monkeypatch.setattr(preview_server, "_cleanup_partial_artifacts", cleanup)
    with caplog.at_level("WARNING"):
        preview_server._recover_lost_jobs()
    assert cleaned == ["20260202_020202"]
    assert any("cleanup(20260101_010101)" in r.message for r in caplog.records)
