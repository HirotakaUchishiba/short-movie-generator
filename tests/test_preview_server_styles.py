"""GET/POST/PUT/DELETE /api/styles の API テスト。"""
import pytest


@pytest.fixture
def isolated_styles_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    from analyze import style as _style
    monkeypatch.setattr(_style, "STYLES_DIR", tmp_path / "styles")
    return _style


@pytest.fixture
def client(isolated_styles_env):
    import preview_server
    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


def _payload(name: str = "x"):
    return {
        "name": name,
        "characters": [
            {"name": "主人公", "role": "narrator", "ref": "female_engineer"},
        ],
    }


def test_list_styles_empty(client):
    r = client.get("/api/styles")
    assert r.status_code == 200
    assert r.get_json() == {"styles": []}


def test_create_style(client):
    r = client.post("/api/styles", json=_payload("alpha"))
    assert r.status_code == 201
    body = r.get_json()
    assert body["name"] == "alpha"
    assert body["characters"][0]["name"] == "主人公"


def test_create_rejects_missing_name(client):
    r = client.post("/api/styles", json={"characters": []})
    assert r.status_code == 400


def test_create_rejects_invalid(client):
    r = client.post("/api/styles", json={"name": "x", "characters": []})
    assert r.status_code == 400
    assert "characters" in r.get_json()["error"]


def test_get_style(client):
    client.post("/api/styles", json=_payload("alpha"))
    r = client.get("/api/styles/alpha")
    assert r.status_code == 200
    assert r.get_json()["name"] == "alpha"


def test_get_style_404(client):
    r = client.get("/api/styles/nope")
    assert r.status_code == 404


def test_get_style_400_invalid_name(client):
    r = client.get("/api/styles/..%2Fbad")
    # path traversal は flask routing で別 url 扱いされ、_path での
    # ValueError 経由で 400 になる
    assert r.status_code in (400, 404)


def test_update_style(client):
    client.post("/api/styles", json=_payload("alpha"))
    upd = _payload("alpha")
    upd["animation_style"] = "expressive"
    r = client.put("/api/styles/alpha", json=upd)
    assert r.status_code == 200
    assert r.get_json()["animation_style"] == "expressive"


def test_update_style_url_name_takes_priority(client):
    client.post("/api/styles", json=_payload("alpha"))
    # body に違う name を入れても URL の名前で保存される
    upd = _payload("hijack")
    r = client.put("/api/styles/alpha", json=upd)
    assert r.status_code == 200
    assert r.get_json()["name"] == "alpha"


def test_delete_style(client):
    client.post("/api/styles", json=_payload("alpha"))
    r = client.delete("/api/styles/alpha")
    assert r.status_code == 200
    assert r.get_json()["deleted"] is True
    assert client.get("/api/styles/alpha").status_code == 404


def test_delete_style_404(client):
    r = client.delete("/api/styles/nope")
    assert r.status_code == 404


def test_list_returns_multiple(client):
    client.post("/api/styles", json=_payload("zeta"))
    client.post("/api/styles", json=_payload("alpha"))
    r = client.get("/api/styles")
    items = r.get_json()["styles"]
    names = sorted(it["name"] for it in items)
    assert names == ["alpha", "zeta"]
