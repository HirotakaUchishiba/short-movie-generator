"""dashboard.py が空 DB でも起動して全タブ render される smoke test.

Phase A で追加したタブ (= 戦略軸 / 実験 / 品質) が module load 時にエラーを出さない
ことを保証する。深い表示内容はユーザの目視で確認する前提。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture
def isolated_db_for_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    return _db


def test_dashboard_runs_on_empty_db(isolated_db_for_dashboard):
    pytest.importorskip("streamlit.testing.v1")
    from streamlit.testing.v1 import AppTest

    dashboard_path = _ROOT / "scripts" / "dashboard.py"
    at = AppTest.from_file(str(dashboard_path), default_timeout=20)
    at.run()
    assert not at.exception, f"AppTest exception: {at.exception}"


def test_dashboard_tab_labels(isolated_db_for_dashboard):
    pytest.importorskip("streamlit.testing.v1")
    from streamlit.testing.v1 import AppTest

    dashboard_path = _ROOT / "scripts" / "dashboard.py"
    at = AppTest.from_file(str(dashboard_path), default_timeout=20)
    at.run()
    assert not at.exception, f"AppTest exception: {at.exception}"
    if not at.tabs:
        pytest.skip("AppTest API didn't expose tabs in this streamlit version")
    labels = [t.label for t in at.tabs]
    for required in ("概要", "Transformation", "戦略軸", "フック別", "感情別",
                     "実験", "品質", "Halo", "台本詳細", "分析ジョブ"):
        assert required in labels, f"タブ {required!r} が見当たらない: {labels}"
