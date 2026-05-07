"""lipsync の primary 失敗 → 別 provider に自動フォールバックする挙動。"""

from unittest.mock import MagicMock

import pytest

import lipsync_client


def _enable_keys(monkeypatch, *, syncso=True, fal=True, domoai=True):
    monkeypatch.setattr(
        lipsync_client.config, "SYNCSO_API_KEY",
        "k" if syncso else None,
    )
    monkeypatch.setattr(
        lipsync_client.config, "FAL_API_KEY",
        "k" if fal else None,
    )
    monkeypatch.setattr(
        lipsync_client.config, "DOMOAI_API_KEY",
        "k" if domoai else None,
    )


def test_provider_available_checks_each_key(monkeypatch):
    _enable_keys(monkeypatch, syncso=True, fal=False, domoai=False)
    assert lipsync_client._provider_available("syncso") is True
    assert lipsync_client._provider_available("fal-sync") is False
    assert lipsync_client._provider_available("domoai") is False


def test_build_fallback_chain_has_primary_first(monkeypatch):
    _enable_keys(monkeypatch)
    assert lipsync_client._build_fallback_chain("syncso")[0] == "syncso"
    assert lipsync_client._build_fallback_chain("fal-sync")[0] == "fal-sync"


def test_build_fallback_chain_skips_unavailable(monkeypatch):
    _enable_keys(monkeypatch, syncso=True, fal=True, domoai=False)
    chain = lipsync_client._build_fallback_chain("syncso")
    assert "domoai" not in chain
    assert "fal-sync" in chain


def test_apply_uses_primary_on_success(monkeypatch):
    _enable_keys(monkeypatch)
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_PROVIDER", "syncso")

    syncso_mock = MagicMock()
    fal_mock = MagicMock()
    monkeypatch.setitem(lipsync_client._PROVIDERS, "syncso", syncso_mock)
    monkeypatch.setitem(lipsync_client._PROVIDERS, "fal-sync", fal_mock)

    lipsync_client.apply("/v.mp4", "/a.mp3", "/out.mp4")
    syncso_mock.assert_called_once()
    fal_mock.assert_not_called()


def test_apply_falls_back_on_size_limit(monkeypatch):
    _enable_keys(monkeypatch)
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_PROVIDER", "syncso")

    def syncso_too_big(*_a, **_kw):
        raise lipsync_client.LipsyncClientError(
            "Sync.so multipart 上限 20MB を超過: /v.mp4 (35.0MB)"
        )

    fal_mock = MagicMock()
    monkeypatch.setitem(lipsync_client._PROVIDERS, "syncso", syncso_too_big)
    monkeypatch.setitem(lipsync_client._PROVIDERS, "fal-sync", fal_mock)
    monkeypatch.setitem(
        lipsync_client._PROVIDERS, "domoai", MagicMock())

    lipsync_client.apply("/v.mp4", "/a.mp3", "/out.mp4")
    fal_mock.assert_called_once()


def test_apply_falls_back_on_exhausted_balance(monkeypatch):
    _enable_keys(monkeypatch)
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_PROVIDER", "syncso")

    def syncso_balance(*_a, **_kw):
        raise lipsync_client.LipsyncClientError("exhausted balance")

    fal_mock = MagicMock()
    monkeypatch.setitem(lipsync_client._PROVIDERS, "syncso", syncso_balance)
    monkeypatch.setitem(lipsync_client._PROVIDERS, "fal-sync", fal_mock)
    monkeypatch.setitem(
        lipsync_client._PROVIDERS, "domoai", MagicMock())

    lipsync_client.apply("/v.mp4", "/a.mp3", "/out.mp4")
    fal_mock.assert_called_once()


def test_apply_does_not_fallback_on_unrelated_exception(monkeypatch):
    _enable_keys(monkeypatch)
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_PROVIDER", "syncso")

    def syncso_validation_error(*_a, **_kw):
        # 認証以外の純粋な引数エラーは fallback 対象にしない
        raise ValueError("invalid arg")

    fal_mock = MagicMock()
    monkeypatch.setitem(
        lipsync_client._PROVIDERS, "syncso", syncso_validation_error)
    monkeypatch.setitem(lipsync_client._PROVIDERS, "fal-sync", fal_mock)

    with pytest.raises(ValueError):
        lipsync_client.apply("/v.mp4", "/a.mp3", "/out.mp4")
    fal_mock.assert_not_called()


def test_apply_all_providers_fail_raises(monkeypatch):
    _enable_keys(monkeypatch)
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_PROVIDER", "syncso")

    def fail(*_a, **_kw):
        raise lipsync_client.LipsyncClientError("multipart 上限 20MB 超過")

    monkeypatch.setitem(lipsync_client._PROVIDERS, "syncso", fail)
    monkeypatch.setitem(lipsync_client._PROVIDERS, "fal-sync", fail)
    monkeypatch.setitem(lipsync_client._PROVIDERS, "domoai", fail)

    with pytest.raises(lipsync_client.LipsyncClientError) as exc:
        lipsync_client.apply("/v.mp4", "/a.mp3", "/out.mp4")
    assert "全 provider" in str(exc.value)


def test_apply_skips_fallback_when_disabled(monkeypatch):
    _enable_keys(monkeypatch)
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_PROVIDER", "syncso")
    monkeypatch.setenv("LIPSYNC_FALLBACK_DISABLED", "1")

    def fail(*_a, **_kw):
        raise lipsync_client.LipsyncClientError("multipart 上限")

    fal_mock = MagicMock()
    monkeypatch.setitem(lipsync_client._PROVIDERS, "syncso", fail)
    monkeypatch.setitem(lipsync_client._PROVIDERS, "fal-sync", fal_mock)

    with pytest.raises(lipsync_client.LipsyncClientError):
        lipsync_client.apply("/v.mp4", "/a.mp3", "/out.mp4")
    fal_mock.assert_not_called()


def test_apply_unknown_provider_raises(monkeypatch):
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_PROVIDER", "bogus")
    with pytest.raises(lipsync_client.LipsyncClientError) as exc:
        lipsync_client.apply("/v.mp4", "/a.mp3", "/out.mp4")
    assert "未知" in str(exc.value)


def test_is_recoverable_error_for_domoai_duration_overflow():
    exc = lipsync_client.LipsyncClientError(
        "DomoAI: 音声 65.0s が上限 60s を超過。fallback または分割が必要です。"
    )
    assert lipsync_client._is_recoverable_error("domoai", exc) is True


def test_apply_falls_back_when_domoai_audio_exceeds_limit(monkeypatch):
    """domoai が primary で 60s 超 audio が来たら次の provider に fallback する。"""
    _enable_keys(monkeypatch)
    monkeypatch.setattr(lipsync_client.config, "LIPSYNC_PROVIDER", "domoai")

    def domoai_too_long(*_a, **_kw):
        raise lipsync_client.LipsyncClientError(
            "DomoAI: 音声 75.0s が上限 60s を超過。"
            "fallback または分割が必要です。"
        )

    syncso_mock = MagicMock()
    fal_mock = MagicMock()
    monkeypatch.setitem(lipsync_client._PROVIDERS, "domoai", domoai_too_long)
    monkeypatch.setitem(lipsync_client._PROVIDERS, "syncso", syncso_mock)
    monkeypatch.setitem(lipsync_client._PROVIDERS, "fal-sync", fal_mock)

    lipsync_client.apply("/v.mp4", "/a.mp3", "/out.mp4")
    # chain は [domoai, syncso, fal-sync] なので syncso が次に呼ばれる
    syncso_mock.assert_called_once()
    fal_mock.assert_not_called()
