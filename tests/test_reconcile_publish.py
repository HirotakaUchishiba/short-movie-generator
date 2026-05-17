"""scripts/reconcile_publish.py の単体テスト。

`analytics_persisted=false` な published_posts を scan + 再登録 +
metadata 更新までの一連の流れを検証する。

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.9
"""

import json
from pathlib import Path

import pytest


def _write_metadata(temp_dir: Path, ts: str, posts: list[dict]) -> Path:
    """temp/<ts>/metadata.json を作成して返す。"""
    proj = temp_dir / ts
    proj.mkdir(parents=True, exist_ok=True)
    meta_path = proj / "metadata.json"
    meta_path.write_text(json.dumps({
        "published_posts": posts,
    }, ensure_ascii=False), encoding="utf-8")
    return meta_path


def test_scan_finds_only_unpersisted_posts(tmp_path):
    """analytics_persisted=false の post のみ拾う。true / 未指定はスキップ。"""
    from scripts import reconcile_publish

    _write_metadata(tmp_path, "20260501_120000", [
        {"platform": "youtube", "video_id": "abc",
         "analytics_persisted": True},  # 拾わない
        {"platform": "instagram", "video_id": "xyz",
         "analytics_persisted": False,
         "analytics_warning": "disk full"},  # 拾う
        {"platform": "tiktok", "video_id": "qqq"},  # 未指定は拾わない
    ])

    found = reconcile_publish._scan_unpersisted_posts(tmp_path)
    assert len(found) == 1
    meta_path, post, idx = found[0]
    assert meta_path.name == "metadata.json"
    assert post["platform"] == "instagram"
    assert post["video_id"] == "xyz"
    assert idx == 1


def test_scan_ignores_projects_without_metadata(tmp_path):
    """metadata.json が無い project ディレクトリは無視する。"""
    from scripts import reconcile_publish

    (tmp_path / "20260501_120000").mkdir()  # metadata 無し
    _write_metadata(tmp_path, "20260502_120000", [
        {"platform": "youtube", "analytics_persisted": False},
    ])

    found = reconcile_publish._scan_unpersisted_posts(tmp_path)
    assert len(found) == 1
    assert found[0][0].parent.name == "20260502_120000"


def test_scan_skips_malformed_metadata(tmp_path):
    """metadata.json が壊れていても crash せず warning を残して次に進む。"""
    from scripts import reconcile_publish

    proj = tmp_path / "20260501_120000"
    proj.mkdir()
    (proj / "metadata.json").write_text("{not json", encoding="utf-8")

    found = reconcile_publish._scan_unpersisted_posts(tmp_path)
    assert found == []


def test_update_metadata_persisted_flips_flag_and_drops_warning(tmp_path):
    """成功時 metadata の persisted=true 化 + warning フィールド削除。"""
    from scripts import reconcile_publish

    meta_path = _write_metadata(tmp_path, "20260501_120000", [
        {"platform": "youtube", "video_id": "abc",
         "analytics_persisted": False,
         "analytics_warning": "transient error"},
    ])

    reconcile_publish._update_metadata_persisted(meta_path, 0)

    meta = json.loads(meta_path.read_text())
    assert meta["published_posts"][0]["analytics_persisted"] is True
    assert "analytics_warning" not in meta["published_posts"][0]


def test_update_metadata_out_of_range_is_noop(tmp_path):
    """post_index が範囲外なら no-op (= crash しない)。"""
    from scripts import reconcile_publish

    meta_path = _write_metadata(tmp_path, "20260501_120000", [
        {"platform": "youtube", "analytics_persisted": False},
    ])
    reconcile_publish._update_metadata_persisted(meta_path, 99)
    # 元 metadata は変更されない
    meta = json.loads(meta_path.read_text())
    assert meta["published_posts"][0]["analytics_persisted"] is False


def test_retry_persist_returns_false_when_video_path_unresolvable(
    tmp_path, monkeypatch,
):
    """canonical video が見つからない場合は (False, error) を返す。"""
    from scripts import reconcile_publish
    import config

    monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path))
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))

    ok, err = reconcile_publish._retry_persist(
        "20260501_120000",
        {"platform": "youtube", "video_id": "abc", "url": "https://x"},
    )
    assert ok is False
    assert err is not None
    assert "動画パス" in err or "見つかりません" in err or "not found" in err.lower()


def test_main_dry_run_lists_without_db_writes(
    tmp_path, monkeypatch, capsys,
):
    """--dry-run は DB 書き込みせず一覧表示のみ。"""
    from scripts import reconcile_publish
    import config

    monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path))
    _write_metadata(tmp_path, "20260501_120000", [
        {"platform": "youtube", "url": "https://x",
         "analytics_persisted": False},
    ])

    monkeypatch.setattr("sys.argv", ["reconcile_publish", "--dry-run"])
    rc = reconcile_publish.main()
    assert rc == 0


def test_main_zero_unpersisted_returns_zero(tmp_path, monkeypatch):
    """対象 0 件なら exit code 0 で early return。"""
    from scripts import reconcile_publish
    import config

    monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["reconcile_publish"])
    rc = reconcile_publish.main()
    assert rc == 0
