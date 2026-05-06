"""Instagram / TikTok クライアントの基本テスト (Phase 1 スケルトン)。"""

import pytest


def test_instagram_requires_credentials(monkeypatch):
    monkeypatch.delenv("INSTAGRAM_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("INSTAGRAM_BUSINESS_ID", raising=False)
    from platform_clients import instagram
    with pytest.raises(RuntimeError, match="INSTAGRAM"):
        instagram.fetch_insights("some_id")


def test_instagram_normalizes_response(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("INSTAGRAM_BUSINESS_ID", "biz")

    class _R:
        status_code = 200

        def json(self):
            return {"data": [
                {"name": "plays", "values": [{"value": 1234}]},
                {"name": "likes", "values": [{"value": 50}]},
                {"name": "saved", "values": [{"value": 7}]},
            ]}

        def raise_for_status(self):
            pass

    monkeypatch.setattr("requests.get", lambda *a, **kw: _R())
    from platform_clients import instagram
    out = instagram.fetch_insights("media1")
    assert out["plays"] == 1234
    assert out["views"] == 1234
    assert out["likes"] == 50
    assert out["saves"] == 7


def test_tiktok_requires_credentials(monkeypatch):
    monkeypatch.delenv("TIKTOK_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TIKTOK_OPEN_ID", raising=False)
    from platform_clients import tiktok
    with pytest.raises(RuntimeError, match="TIKTOK"):
        tiktok.fetch_video_stats("vid")


def test_tiktok_csv_parser():
    from platform_clients.tiktok import parse_studio_csv

    csv = (
        "Video link,Views,Likes,Comments,Shares,Saved,Watched full video\n"
        "https://www.tiktok.com/@u/video/9999,1234,56,7,8,9,42%\n"
        "https://www.tiktok.com/@u/video/8888,1,2,3,4,5,12%\n"
    )
    rows = parse_studio_csv(csv)
    assert len(rows) == 2
    assert rows[0]["platform_post_id"] == "9999"
    assert rows[0]["views"] == 1234
    assert rows[0]["completion_rate"] == 0.42
    assert rows[1]["platform_post_id"] == "8888"
    assert rows[1]["completion_rate"] == 0.12


def test_fetch_metrics_dict_includes_new_platforms():
    from scripts.fetch_metrics import PLATFORM_CLIENTS
    assert "youtube" in PLATFORM_CLIENTS
    assert "instagram" in PLATFORM_CLIENTS
    assert "tiktok" in PLATFORM_CLIENTS
