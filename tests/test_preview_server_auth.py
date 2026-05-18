"""PREVIEW_AUTH_TOKEN による optional bearer token 検証テスト。"""
import pytest


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    """`_AUTH_TOKEN` を直接 monkeypatch して preview_server を再ロードしない。"""
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    import preview_server
    monkeypatch.setattr(preview_server, "_AUTH_TOKEN", "secret123")
    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client(), "secret123"


@pytest.fixture
def noauth_client(tmp_path, monkeypatch):
    """`_AUTH_TOKEN=None` で全部素通り。"""
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    import preview_server
    monkeypatch.setattr(preview_server, "_AUTH_TOKEN", None)
    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


def test_no_token_env_means_no_auth_required(noauth_client) -> None:
    r = noauth_client.get("/api/projects")
    assert r.status_code == 200


def test_token_required_when_env_set(auth_client) -> None:
    client, _ = auth_client
    r = client.get("/api/projects")
    assert r.status_code == 401
    body = r.get_json()
    assert body["message"] == "unauthorized"
    assert body["error_code"] == "UNAUTHORIZED"


def test_correct_token_passes(auth_client) -> None:
    client, token = auth_client
    r = client.get("/api/projects", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_wrong_token_rejected(auth_client) -> None:
    client, _ = auth_client
    r = client.get("/api/projects", headers={"Authorization": "Bearer WRONG"})
    assert r.status_code == 401


def test_asset_path_bypasses_auth(auth_client) -> None:
    """`<video src=/asset/...>` はヘッダ付与できないので auth を bypass。"""
    client, _ = auth_client
    # 存在しない asset path でも 401 ではなく 404 が返ること (= auth check は通過)
    r = client.get("/asset/nonexistent/file.mp4")
    assert r.status_code != 401


def test_request_id_header_emitted(noauth_client) -> None:
    r = noauth_client.get("/api/projects")
    assert "X-Request-ID" in r.headers
    assert r.headers["X-Request-ID"] != "-"


def test_incoming_request_id_preserved(noauth_client) -> None:
    r = noauth_client.get(
        "/api/projects", headers={"X-Request-ID": "abc12345"}
    )
    assert r.headers["X-Request-ID"] == "abc12345"
