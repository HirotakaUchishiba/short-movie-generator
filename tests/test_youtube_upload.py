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


# ─── 308 without Range header (status query path) ──────────────


def test_upload_308_without_range_triggers_status_query(monkeypatch, fake_video):
    """308 が Range 無しで返ったら status query で受領 offset を取り直す."""
    from platform_clients import youtube

    file_size = fake_video.stat().st_size
    chunk_size = max(1024, file_size // 4)
    state = {"put_count": 0}

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "tok"})
        return _MockResp(200, headers={"Location": "https://up/"})

    def fake_put(url, **kw):
        state["put_count"] += 1
        body = kw.get("data") or b""
        body_len = len(body)
        if body_len == 0:
            # status query — server は 0 byte 受領済みとして応答
            return _MockResp(308, headers={"Range": "bytes=0-0"})
        # 1 chunk 目: 308 だが Range 無し (= server がまだ確定してない)
        if state["put_count"] == 1:
            return _MockResp(308, headers={})
        # 2 chunk 目以降: 全部受領 → 完了
        return _MockResp(200, json_data={"id": "vid_recovered"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    result = youtube.upload_video(
        fake_video, "T", "D", chunk_size=chunk_size,
    )
    assert result["video_id"] == "vid_recovered"
    # 楽観的に進めなかった (= status query が走った) ことの確認:
    # - 1 回目の chunk PUT: 308 (no Range)
    # - status query (data=b"")
    # - 2 回目以降の chunk PUT
    assert state["put_count"] >= 3


def test_upload_aborts_when_range_is_persistently_missing(monkeypatch, fake_video):
    """308 が Range 無しで返り続けるなら byte gap を避けて RuntimeError."""
    from platform_clients import youtube

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "tok"})
        return _MockResp(200, headers={"Location": "https://up/"})

    def fake_put(url, **kw):
        # chunk PUT も status query も全部 308 (no Range)
        return _MockResp(308, headers={})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    with pytest.raises(RuntimeError, match="byte gap"):
        youtube.upload_video(fake_video, "T", "D")


def test_upload_status_query_returns_completion(monkeypatch, fake_video):
    """status query が 200 で video resource を返したら完了扱い."""
    from platform_clients import youtube

    state = {"put_count": 0}

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "tok"})
        return _MockResp(200, headers={"Location": "https://up/"})

    def fake_put(url, **kw):
        state["put_count"] += 1
        if (kw.get("data") or b"") == b"":
            # status query: 既に全部 server 側にある
            return _MockResp(200, json_data={"id": "vid_already_uploaded"})
        # chunk PUT: 308 no Range
        return _MockResp(308, headers={})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    result = youtube.upload_video(fake_video, "T", "D")
    assert result["video_id"] == "vid_already_uploaded"


def test_parse_range_offset_helper():
    from platform_clients.youtube import _parse_range_offset
    assert _parse_range_offset({"Range": "bytes=0-1023"}) == 1024
    assert _parse_range_offset({"range": "bytes=0-99"}) == 100
    assert _parse_range_offset({}) is None
    assert _parse_range_offset({"Range": "bytes="}) is None
    assert _parse_range_offset({"Range": "weird"}) is None


# ─── OAuth refresh / retry (C3) ───────────────


def test_oauth_token_raises_with_guidance_on_invalid_grant(monkeypatch):
    """refresh_token が無効 (= 401/invalid_grant) → guidance 付き RuntimeError."""
    from platform_clients import youtube

    def fake_post(url, **kw):
        return _MockResp(
            401, json_data={"error": "invalid_grant"},
            text='{"error":"invalid_grant"}',
        )

    monkeypatch.setattr("requests.post", fake_post)
    with pytest.raises(RuntimeError, match="YOUTUBE_REFRESH_TOKEN"):
        youtube._oauth_access_token("id", "sec", "ref")


def test_oauth_token_retries_on_5xx(monkeypatch):
    """oauth endpoint 5xx → exponential backoff で 2 回 retry → 成功."""
    from platform_clients import youtube

    state = {"calls": 0}

    def fake_post(url, **kw):
        state["calls"] += 1
        if state["calls"] < 3:
            return _MockResp(503, text="oauth temporarily unavailable")
        return _MockResp(200, json_data={"access_token": "tok"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    token = youtube._oauth_access_token("id", "sec", "ref")
    assert token == "tok"
    assert state["calls"] == 3


def test_oauth_token_retries_on_connection_error(monkeypatch):
    """ConnectionError → backoff retry → 成功."""
    import requests
    from platform_clients import youtube

    state = {"calls": 0}

    def fake_post(url, **kw):
        state["calls"] += 1
        if state["calls"] == 1:
            raise requests.ConnectionError("boom")
        return _MockResp(200, json_data={"access_token": "tok"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    assert youtube._oauth_access_token("id", "sec", "ref") == "tok"
    assert state["calls"] == 2


def test_upload_video_refreshes_token_on_401(monkeypatch, fake_video):
    """init が 401 → access_token を取り直して 1 回だけ retry → upload 成功."""
    from platform_clients import youtube

    state = {"oauth": 0, "init": 0}

    def fake_post(url, **kw):
        if "oauth2.googleapis.com/token" in url:
            state["oauth"] += 1
            return _MockResp(200, json_data={
                "access_token": f"tok_{state['oauth']}",
            })
        state["init"] += 1
        if state["init"] == 1:
            return _MockResp(401, text="token expired")
        return _MockResp(200, headers={"Location": "https://up/"})

    def fake_put(url, **kw):
        return _MockResp(200, json_data={"id": "vid_recovered"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    result = youtube.upload_video(fake_video, "T", "D")
    assert result["video_id"] == "vid_recovered"
    # initial token + 1 refresh = 2 calls, init = 2 calls (401 → retry)
    assert state["oauth"] == 2
    assert state["init"] == 2


def test_upload_video_retries_on_5xx_init(monkeypatch, fake_video):
    """init が 5xx → backoff retry."""
    from platform_clients import youtube

    state = {"init": 0}

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "tok"})
        state["init"] += 1
        if state["init"] < 3:
            return _MockResp(502, text="bad gateway")
        return _MockResp(200, headers={"Location": "https://up/"})

    def fake_put(url, **kw):
        return _MockResp(200, json_data={"id": "vid_after_5xx"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    result = youtube.upload_video(fake_video, "T", "D")
    assert result["video_id"] == "vid_after_5xx"
    assert state["init"] == 3


# ─── resume token 永続化 ──────────────


def test_upload_persists_state_and_clears_on_success(monkeypatch, fake_video, tmp_path):
    """state_path 指定で upload 中に state が書かれ、成功後に消える。"""
    from platform_clients import youtube

    state_path = tmp_path / "upload_state.json"
    file_size = fake_video.stat().st_size
    state = {"offset": 0}

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "tok"})
        return _MockResp(200, headers={"Location": "https://up/abc"})

    def fake_put(url, **kw):
        chunk_len = len(kw.get("data") or b"")
        state["offset"] += chunk_len
        if state["offset"] >= file_size:
            return _MockResp(200, json_data={"id": "vid"})
        return _MockResp(308, headers={"Range": f"bytes=0-{state['offset'] - 1}"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    youtube.upload_video(
        fake_video, "T", "D", chunk_size=file_size // 4,
        state_path=state_path,
    )
    assert not state_path.exists()  # 成功で消える


def test_upload_resumes_from_persisted_state(monkeypatch, fake_video, tmp_path):
    """既存 state があれば server に offset 問い合わせて resume する。"""
    import json
    from datetime import datetime, timezone
    from platform_clients import youtube

    state_path = tmp_path / "upload_state.json"
    file_size = fake_video.stat().st_size
    half = file_size // 2

    state_path.write_text(json.dumps({
        "upload_url": "https://up/resume",
        "file_size": file_size,
        "bytes_uploaded": half,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_path": str(fake_video),
    }))

    init_calls: list[str] = []
    put_offsets: list[int] = []

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "tok"})
        init_calls.append(url)
        return _MockResp(200, headers={"Location": "https://up/SHOULD_NOT_BE_USED"})

    def fake_put(url, **kw):
        body = kw.get("data") or b""
        if len(body) == 0:
            # status query (= resume の最初の呼出し): server は half まで受領済みと応答
            return _MockResp(308, headers={"Range": f"bytes=0-{half - 1}"})
        # 通常 chunk
        cr = (kw.get("headers") or {}).get("Content-Range", "")
        if cr.startswith("bytes "):
            offset = int(cr.split(" ", 1)[1].split("-", 1)[0])
            put_offsets.append(offset)
        return _MockResp(200, json_data={"id": "resumed_vid"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    result = youtube.upload_video(
        fake_video, "T", "D", chunk_size=file_size,
        state_path=state_path,
    )
    assert result["video_id"] == "resumed_vid"
    # init は呼ばれない (= resume だから)
    assert init_calls == []
    # 中断時の offset (half) から再開している
    assert put_offsets and put_offsets[0] >= half
    assert not state_path.exists()  # 成功で消える


def test_upload_state_discarded_when_too_old(monkeypatch, fake_video, tmp_path):
    """24h 以上古い state は破棄して新規 upload。"""
    import json
    from datetime import datetime, timezone, timedelta
    from platform_clients import youtube

    state_path = tmp_path / "upload_state.json"
    file_size = fake_video.stat().st_size
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(timespec="seconds")
    state_path.write_text(json.dumps({
        "upload_url": "https://up/STALE",
        "file_size": file_size,
        "bytes_uploaded": 0,
        "started_at": old,
        "file_path": str(fake_video),
    }))

    init_calls: list[str] = []

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "tok"})
        init_calls.append(url)
        return _MockResp(200, headers={"Location": "https://up/fresh"})

    def fake_put(url, **kw):
        return _MockResp(200, json_data={"id": "fresh"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    result = youtube.upload_video(
        fake_video, "T", "D", state_path=state_path,
    )
    assert result["video_id"] == "fresh"
    # init が呼ばれている (= stale state は破棄された)
    assert len(init_calls) == 1


def test_upload_state_discarded_when_size_mismatch(monkeypatch, fake_video, tmp_path):
    """file_size 不一致の state は破棄。"""
    import json
    from datetime import datetime, timezone
    from platform_clients import youtube

    state_path = tmp_path / "upload_state.json"
    state_path.write_text(json.dumps({
        "upload_url": "https://up/STALE",
        "file_size": 999999,  # 違うサイズ
        "bytes_uploaded": 0,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_path": str(fake_video),
    }))

    init_calls: list[str] = []

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "tok"})
        init_calls.append(url)
        return _MockResp(200, headers={"Location": "https://up/fresh"})

    def fake_put(url, **kw):
        return _MockResp(200, json_data={"id": "fresh"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    youtube.upload_video(fake_video, "T", "D", state_path=state_path)
    assert len(init_calls) == 1
