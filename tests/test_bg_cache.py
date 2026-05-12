"""bg_cache のキャッシュキー算出 / store / lookup / prune の単体テスト。"""
from pathlib import Path

import pytest

import bg_cache


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(bg_cache.config, "BG_CACHE_DIR", str(tmp_path / "bg_cache"))
    bg_cache._FILE_SHA_CACHE.clear()
    return tmp_path / "bg_cache"


@pytest.fixture
def isolated_assets(tmp_path, monkeypatch):
    """characters/ と locations/ をテスト用に隔離。"""
    chars = tmp_path / "characters"
    locs = tmp_path / "locations"
    chars.mkdir()
    locs.mkdir()
    from analyze import character_meta as cmeta_mod
    from analyze import location as loc_mod
    monkeypatch.setattr(cmeta_mod, "CHARACTERS_DIR", chars)
    monkeypatch.setattr(loc_mod, "LOCATIONS_DIR", locs)
    return {"chars": chars, "locs": locs}


def _make_image(path: Path, content: bytes = b"fake-png-bytes") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _seed_assets(isolated_assets, *, decor_a: str = "scandi") -> None:
    from analyze import character_meta as cmeta_mod
    from analyze import location as loc_mod
    base = isolated_assets["chars"] / "f1"
    base.mkdir()
    _make_image(base / "office.png", b"img-f1-office")
    _make_image(base / "casual.png", b"img-f1-casual")
    cmeta_mod.save_character_meta(cmeta_mod.CharacterMeta(id="f1"))
    loc_mod.save_location(loc_mod.Location(
        id="home_office", decor=decor_a, camera_distance="medium-close",
    ))


def _scene(refs=None, location_ref="home_office", camera_distance=None) -> dict:
    refs_list = list(refs or ["f1__office"])
    identity = {
        "character_refs": refs_list,
        "location_ref": location_ref,
        "start_emotion": "中立",
        "camera_distance": camera_distance or "medium-close",
    }
    return {
        "characters": [{"name": r} for r in refs_list],
        "identity": identity,
        "background_prompt": "test bg",
        "lines": [],
    }


# ─── compute_bg_cache_key (決定論性) ───────────────────────


def test_key_is_deterministic(isolated_cache, isolated_assets):
    _seed_assets(isolated_assets)
    scene = _scene()
    sp = {"caption": "x", "scenes": [scene]}
    k1 = bg_cache.compute_bg_cache_key(scene, sp)
    k2 = bg_cache.compute_bg_cache_key(scene, sp)
    assert k1 == k2
    assert len(k1) == 16


def test_key_changes_with_location_change(isolated_cache, isolated_assets):
    _seed_assets(isolated_assets, decor_a="modern")
    scene = _scene()
    sp = {"caption": "x", "scenes": [scene]}
    k1 = bg_cache.compute_bg_cache_key(scene, sp)
    # location 内容を変更
    from analyze import location as loc_mod
    loc_mod.save_location(loc_mod.Location(
        id="home_office", decor="cozy", camera_distance="medium-close",
    ))
    bg_cache._FILE_SHA_CACHE.clear()
    k2 = bg_cache.compute_bg_cache_key(scene, sp)
    assert k1 != k2


def test_key_changes_with_character_image_change(isolated_cache, isolated_assets):
    _seed_assets(isolated_assets)
    scene = _scene()
    sp = {"caption": "x", "scenes": [scene]}
    k1 = bg_cache.compute_bg_cache_key(scene, sp)
    # character 画像を差し替え
    img = isolated_assets["chars"] / "f1" / "office.png"
    img.write_bytes(b"img-f1-office-VARIANT-2")
    bg_cache._FILE_SHA_CACHE.clear()
    k2 = bg_cache.compute_bg_cache_key(scene, sp)
    assert k1 != k2


def test_key_changes_with_imagen_model(isolated_cache, isolated_assets, monkeypatch):
    _seed_assets(isolated_assets)
    scene = _scene()
    sp = {"caption": "x", "scenes": [scene]}
    import imagen_client
    monkeypatch.setattr(imagen_client, "MODEL", "model-A")
    k1 = bg_cache.compute_bg_cache_key(scene, sp)
    monkeypatch.setattr(imagen_client, "MODEL", "model-B")
    k2 = bg_cache.compute_bg_cache_key(scene, sp)
    assert k1 != k2


def test_key_unchanged_for_different_ts_or_scene_idx(isolated_cache, isolated_assets):
    """ts / scene_idx は cache キーに入らない (= 別動画でも同じ入力なら hit)。"""
    _seed_assets(isolated_assets)
    scene1 = _scene()
    scene2 = _scene()  # 完全に同じ内容
    sp1 = {"caption": "video-1", "scenes": [scene1, scene1]}
    sp2 = {"caption": "video-2 different caption", "scenes": [scene2]}
    k1 = bg_cache.compute_bg_cache_key(scene1, sp1)
    k2 = bg_cache.compute_bg_cache_key(scene2, sp2)
    assert k1 == k2


# ─── store / lookup / touch ────────────────────────────────


def test_store_then_lookup_hit(isolated_cache, isolated_assets, tmp_path):
    _seed_assets(isolated_assets)
    img = tmp_path / "src.png"
    _make_image(img, b"hello-img")
    bg_cache.store("abc123", img, {"scene_idx": 0})
    found = bg_cache.lookup("abc123")
    assert found is not None
    assert found.read_bytes() == b"hello-img"


def test_lookup_miss_returns_none(isolated_cache, isolated_assets):
    _seed_assets(isolated_assets)
    assert bg_cache.lookup("does-not-exist") is None


def test_store_is_idempotent(isolated_cache, tmp_path):
    img = tmp_path / "src.png"
    _make_image(img, b"first")
    bg_cache.store("k1", img, {})
    img.write_bytes(b"second")
    bg_cache.store("k1", img, {})  # 既存なら no-op
    found = bg_cache.lookup("k1")
    assert found is not None
    assert found.read_bytes() == b"first"  # 上書きされない


def test_touch_increments_hit_count(isolated_cache, tmp_path):
    img = tmp_path / "src.png"
    _make_image(img)
    bg_cache.store("k1", img, {})
    bg_cache.touch("k1")
    bg_cache.touch("k1")
    bg_cache.touch("k1")
    import json
    meta = json.loads((isolated_cache / "k1.json").read_text())
    assert meta["hit_count"] == 3


# ─── prune (LRU) ────────────────────────────────────────


def test_prune_under_limit_does_nothing(isolated_cache, tmp_path):
    img = tmp_path / "src.png"
    _make_image(img, b"x" * 100)
    bg_cache.store("a", img, {})
    res = bg_cache.prune(max_total_bytes=1000)
    assert res["deleted"] == []


def test_prune_evicts_lru(isolated_cache, tmp_path, monkeypatch):
    """容量超過時、last_used_at が古いエントリから順に削除される。"""
    import time
    for i, label in enumerate(["old", "mid", "new"]):
        img = tmp_path / f"{label}.png"
        _make_image(img, b"x" * 1000)
        bg_cache.store(label, img, {})
        time.sleep(0.01)
        # last_used_at の差を確実につけるため touch
        bg_cache.touch(label)
    # 全 3000 bytes を 1500 bytes に絞る → 古い方 1 つ以上削除
    res = bg_cache.prune(max_total_bytes=1500)
    deleted_keys = {d["key"] for d in res["deleted"]}
    assert "old" in deleted_keys
    assert "new" not in deleted_keys
    assert bg_cache.lookup("old") is None
    assert bg_cache.lookup("new") is not None


def test_prune_dry_run_does_not_delete(isolated_cache, tmp_path):
    img = tmp_path / "src.png"
    _make_image(img, b"x" * 1000)
    bg_cache.store("a", img, {})
    res = bg_cache.prune(max_total_bytes=500, dry_run=True)
    assert len(res["deleted"]) == 1
    assert bg_cache.lookup("a") is not None  # 実際には残っている
