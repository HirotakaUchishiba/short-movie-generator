"""fal_video_client のタイムアウト統合テスト。
fal_client.subscribe をモックして watchdog の挙動を検証する。"""

import time
from unittest.mock import MagicMock

import pytest

import fal_video_client
from fal_runner import FalJobTimeoutError


# ─────────── _classify_error ───────────


def test_video_classify_treats_timeout_as_retry() -> None:
    exc = FalJobTimeoutError("kling stuck")
    assert fal_video_client._classify_error(exc) == "retry"


def test_video_classify_still_fails_on_4xx() -> None:
    err = Exception("bad request")
    err.status_code = 400
    assert fal_video_client._classify_error(err) == "fail"


def test_video_classify_still_fails_on_exhausted_balance() -> None:
    err = Exception("exhausted balance reached")
    assert fal_video_client._classify_error(err) == "fail"


# ─────────── generate_video の watchdog 動作 ───────────


def test_video_subscribe_timeout_triggers_retry(tmp_path, monkeypatch) -> None:
    """subscribe が timeout すると MAX_RETRIES まで再試行される。"""
    monkeypatch.setattr(fal_video_client.config, "FAL_KLING_TIMEOUT_SEC", 0.05)
    monkeypatch.setattr(fal_video_client.config, "FAL_API_KEY", "k")
    monkeypatch.setattr(fal_video_client, "MAX_RETRIES", 2)
    monkeypatch.setattr(fal_video_client, "BACKOFF_SECONDS", [0])

    fake_fal = MagicMock()
    fake_fal.encode_image = MagicMock(return_value="http://i")
    # subscribe が永久にハングするように
    fake_fal.subscribe.side_effect = lambda *a, **kw: time.sleep(2.0)
    monkeypatch.setattr(fal_video_client, "fal_client", fake_fal)

    image = tmp_path / "i.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    monkeypatch.setattr(fal_video_client, "Image",
                        MagicMock(open=MagicMock(return_value=MagicMock())))

    out = tmp_path / "o.mp4"
    with pytest.raises(fal_video_client.FalClientError) as exc:
        fal_video_client.generate_video(str(image), "p", str(out),
                                          audio_duration=4.0)
    # 最終的にリトライ上限超過で fail
    assert "リトライ上限超過" in str(exc.value)
    # subscribe は MAX_RETRIES 回呼ばれた
    assert fake_fal.subscribe.call_count == 2


def test_video_immediate_success_avoids_timeout(tmp_path, monkeypatch) -> None:
    """subscribe が即返れば timeout は発火しない。"""
    monkeypatch.setattr(fal_video_client.config, "FAL_KLING_TIMEOUT_SEC", 5.0)
    monkeypatch.setattr(fal_video_client.config, "FAL_API_KEY", "k")

    fake_fal = MagicMock()
    fake_fal.encode_image = MagicMock(return_value="http://i")
    fake_fal.subscribe.return_value = {"video": {"url": "http://video"}}
    monkeypatch.setattr(fal_video_client, "fal_client", fake_fal)

    image = tmp_path / "i.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    monkeypatch.setattr(fal_video_client, "Image",
                        MagicMock(open=MagicMock(return_value=MagicMock())))

    fake_resp = MagicMock()
    fake_resp.content = b"VIDEOBYTES"
    fake_resp.raise_for_status = MagicMock()
    monkeypatch.setattr(fal_video_client.requests, "get",
                        MagicMock(return_value=fake_resp))

    out = tmp_path / "o.mp4"
    fal_video_client.generate_video(str(image), "p", str(out),
                                      audio_duration=4.0)
    assert out.read_bytes() == b"VIDEOBYTES"
    fake_fal.subscribe.assert_called_once()


