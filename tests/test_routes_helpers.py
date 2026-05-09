"""routes._helpers の単体テスト。"""
import pytest

from routes import _helpers as h


def test_validate_ts_accepts_valid():
    assert h.validate_ts("20260509_120000") == "20260509_120000"
    assert h.validate_ts("abc-123_def") == "abc-123_def"


def test_validate_ts_rejects_path_traversal():
    from werkzeug.exceptions import BadRequest

    with pytest.raises(BadRequest):
        h.validate_ts("../etc")
    with pytest.raises(BadRequest):
        h.validate_ts("a/b")
    with pytest.raises(BadRequest):
        h.validate_ts("a b")


def test_ts_path_uses_provided_temp_dir(tmp_path):
    p = h.ts_path("20260509_120000", temp_dir=str(tmp_path))
    assert p == str(tmp_path / "20260509_120000")


def test_safe_join_blocks_traversal(tmp_path):
    from werkzeug.exceptions import BadRequest

    base = str(tmp_path / "project")
    (tmp_path / "project").mkdir()
    (tmp_path / "secret.txt").write_text("x")

    # 同じ base 配下なら OK
    ok = h.safe_join(base, "subdir", "file.txt")
    assert ok.startswith(str(tmp_path / "project"))

    # base の外に逃げようとすると abort 400
    with pytest.raises(BadRequest):
        h.safe_join(base, "..", "secret.txt")
