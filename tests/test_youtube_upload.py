"""platform_clients.youtube.upload_video の単体テスト (network mock)。"""

import io
from pathlib import Path

import pytest


@pytest.fixture
def fake_video(tmp_path: Path) -> Path:
    p = tmp_path / "v.mp4"
    p.write_bytes(b"x" * 1024 * 100)  # 100 KB
    return p


@pytest.fixture(autouse=True)
def _set_oauth(monkeypatch):
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "ref")


class _MockResp:
    def __init__(self, status_code: int, json_data=None, headers=None,
                 text: str = ""):
        self.status_code = status_code
        self._json = json_data or {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def test_upload_video_resumable_single_chunk(monkeypatch, fake_video):
    from platform_clients import youtube

    posted = {}
    put_calls: list[dict] = []

    def fake_post(url, **kw):
        if "oauth2.googleapis.com/token" in url:
            return _MockResp(200, json_data={"access_token": "token"})
        posted["url"] = url
        posted["json"] = kw.get("json")
        posted["headers"] = kw.get("headers")
        return _MockResp(
            200, headers={"Location": "https://upload.example/abc"},
        )

    def fake_put(url, **kw):
        put_calls.append({
            "url": url, "headers": kw.get("headers"),
            "data_len": len(kw.get("data") or b""),
        })
        return _MockResp(200, json_data={"id": "video123"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    result = youtube.upload_video(
        file_path=fake_video, title="Hello", description="body",
        tags=["a", "b"], privacy="unlisted", is_short=True,
    )

    assert result["video_id"] == "video123"
    assert result["url"] == "https://youtube.com/shorts/video123"
    assert "uploadType=resumable" in posted["url"]
    assert posted["json"]["snippet"]["title"] == "Hello"
    # is_short → description に #Shorts が付く
    assert "#Shorts" in posted["json"]["snippet"]["description"]
    assert posted["json"]["status"]["privacyStatus"] == "unlisted"
    assert len(put_calls) == 1
    assert put_calls[0]["data_len"] == fake_video.stat().st_size


def test_upload_video_resumable_multiple_chunks(monkeypatch, fake_video):
    from platform_clients import youtube

    state = {"offset": 0}
    file_size = fake_video.stat().st_size

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "token"})
        return _MockResp(200, headers={"Location": "https://upload.example/x"})

    def fake_put(url, **kw):
        chunk_len = len(kw.get("data") or b"")
        state["offset"] += chunk_len
        if state["offset"] >= file_size:
            return _MockResp(201, json_data={"id": "vidXYZ"})
        return _MockResp(308, headers={"Range": f"bytes=0-{state['offset'] - 1}"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    result = youtube.upload_video(
        fake_video, "T", "D", chunk_size=1024 * 30,
    )
    assert result["video_id"] == "vidXYZ"
    assert state["offset"] == file_size


def test_upload_video_missing_credentials(monkeypatch, fake_video):
    monkeypatch.delenv("YOUTUBE_OAUTH_CLIENT_ID", raising=False)
    from platform_clients import youtube
    with pytest.raises(RuntimeError, match="YOUTUBE_OAUTH"):
        youtube.upload_video(fake_video, "t", "d")


def test_upload_video_no_location_header(monkeypatch, fake_video):
    from platform_clients import youtube

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "token"})
        return _MockResp(200, headers={})

    monkeypatch.setattr("requests.post", fake_post)
    with pytest.raises(RuntimeError, match="Location header"):
        youtube.upload_video(fake_video, "t", "d")


def test_upload_video_short_url_format(monkeypatch, fake_video):
    from platform_clients import youtube

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "token"})
        return _MockResp(200, headers={"Location": "https://up/"})

    def fake_put(url, **kw):
        return _MockResp(200, json_data={"id": "abc"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    short = youtube.upload_video(fake_video, "t", "d", is_short=True)
    assert short["url"] == "https://youtube.com/shorts/abc"
    long = youtube.upload_video(fake_video, "t", "d", is_short=False)
    assert long["url"] == "https://youtu.be/abc"


def test_parse_caption_md_extracts_title_body_tags():
    from final_import.publish import parse_caption_md
    md = """# 19_未経験からITエンジニアに転職した末路

未経験からITエンジニアに転職した1日のリアル
在宅ワークで自由な働き方が叶った
#IT転職 #未経験エンジニア #在宅ワーク #転職

## 動画ファイル

- `/tmp/x.mp4`
"""
    title, description, tags = parse_caption_md(md)
    assert title == "19_未経験からITエンジニアに転職した末路"
    assert "未経験からITエンジニアに転職した1日のリアル" in description
    assert "/tmp/x.mp4" not in description  # ## 以降は無視
    assert tags == ["IT転職", "未経験エンジニア", "在宅ワーク", "転職"]


def test_parse_caption_md_dedups_tags():
    from final_import.publish import parse_caption_md
    md = "# t\n\n#a #b #a\n"
    _, _, tags = parse_caption_md(md)
    assert tags == ["a", "b"]


def test_parse_caption_md_empty_falls_to_untitled():
    from final_import.publish import parse_caption_md
    title, _, _ = parse_caption_md("")
    assert title == "untitled"
