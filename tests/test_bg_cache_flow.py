"""scene_gen の Stage 3 cache 統合 (scan / commit / generate_fresh) の単体テスト。

Imagen を mock して、cache lookup → copy / store → fresh 生成のパスを検証する。
kling 側 (test_scene_gen_kling_cache.py) と対称な構造。
"""
from pathlib import Path

import pytest

import bg_cache
import config
import scene_gen


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(
        config, "BG_CACHE_DIR", str(tmp_path / "bg_cache"))
    monkeypatch.setattr(config, "BG_CACHE_ENABLED", True)
    monkeypatch.setattr(config, "BG_CACHE_VERSION", "v1")
    monkeypatch.setattr(config, "BG_CACHE_REQUIRE_APPROVAL", False)
    monkeypatch.setattr(config, "BG_CACHE_TTL_DAYS", 365)
    return tmp_path / "bg_cache"


@pytest.fixture
def isolated_assets(tmp_path, monkeypatch):
    chars = tmp_path / "characters"
    locs = tmp_path / "locations"
    chars.mkdir()
    locs.mkdir()
    from analyze import character_meta as cmeta_mod
    from analyze import location as loc_mod
    monkeypatch.setattr(cmeta_mod, "CHARACTERS_DIR", chars)
    monkeypatch.setattr(loc_mod, "LOCATIONS_DIR", locs)
    return {"chars": chars, "locs": locs}


def _seed_assets(isolated_assets) -> None:
    from analyze import character_meta as cmeta_mod
    from analyze import location as loc_mod
    base = isolated_assets["chars"] / "f1"
    base.mkdir()
    (base / "office.png").write_bytes(b"img-f1-office")
    cmeta_mod.save_character_meta(cmeta_mod.CharacterMeta(id="f1"))
    loc_mod.save_location(loc_mod.Location(
        id="home_office", decor="scandi", camera_distance="medium-close",
    ))


@pytest.fixture
def stub_imagen(monkeypatch):
    """Imagen 実呼び出しを mock。生成を b'fresh-png' で代替。"""
    calls: list[dict] = []
    def _fake_generate_image(prompt, path, reference_images=None):
        Path(path).write_bytes(b"fresh-png-bytes")
        calls.append({
            "prompt": prompt, "path": path,
            "ref_count": len(reference_images or []),
        })
    import imagen_client
    monkeypatch.setattr(imagen_client, "generate_image", _fake_generate_image)
    # storyboard 検出も常に False に固定 (= retry を起こさない)
    monkeypatch.setattr(scene_gen, "_detect_storyboard_image", lambda p: False)
    return calls


def _scene(refs=None, location_ref="home_office",
           background_prompt="subject in office",
           camera_distance="medium-close"):
    return {
        "characters": [{"name": r} for r in (refs or ["f1__office"])],
        "character_refs": list(refs or ["f1__office"]),
        "location_ref": location_ref,
        "camera_distance": camera_distance,
        "background_prompt": background_prompt,
        "lines": [{"text": "ok", "start": 0.0, "end": 1.0}],
    }


# ─── _scene_bg_inputs ─────────────────────────────


def test_scene_bg_inputs_returns_key(isolated_cache, isolated_assets):
    _seed_assets(isolated_assets)
    sp = {"caption": "x", "scenes": [_scene()]}
    inputs = scene_gen._scene_bg_inputs(0, sp["scenes"][0], sp, "/tmp")
    assert inputs is not None
    assert len(inputs["cache_key"]) == 16
    assert inputs["model_id"]
    assert "subject in office" in inputs["background_prompt_resolved"]


# ─── bg_scan_cache ────────────────────────────────


def test_bg_scan_no_candidate_marks_fresh(
        isolated_cache, isolated_assets, stub_imagen):
    _seed_assets(isolated_assets)
    sp = {"caption": "x", "scenes": [_scene()]}
    decisions = scene_gen.bg_scan_cache(sp, "/tmp")
    assert "0" in decisions
    rec = decisions["0"]
    assert rec["candidates"] == []
    assert rec["decision"] == "fresh"
    assert rec["cache_key"] is not None


def test_bg_scan_finds_existing_entry(
        isolated_cache, isolated_assets, stub_imagen, tmp_path):
    _seed_assets(isolated_assets)
    sp = {"caption": "x", "scenes": [_scene()]}
    inputs = scene_gen._scene_bg_inputs(0, sp["scenes"][0], sp, "/tmp")
    assert inputs is not None
    src = tmp_path / "src.png"
    src.write_bytes(b"seeded-bg")
    bg_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_bg_cache_meta(sp["scenes"][0], 0, inputs))

    decisions = scene_gen.bg_scan_cache(sp, "/tmp")
    rec = decisions["0"]
    assert len(rec["candidates"]) == 1
    assert rec["candidates"][0]["key"] == inputs["cache_key"]
    assert rec["decision"] == "pending"


# ─── _generate_single_background: cache miss → fresh ──


def test_generate_background_with_retry_miss_then_store(
        isolated_cache, isolated_assets, stub_imagen, tmp_path):
    """_generate_background_with_retry が cache miss → 生成 → store する一連を検証。
    store は retry helper 内で行われる (= storyboard 通過後 1 度だけ)。"""
    _seed_assets(isolated_assets)
    sp = {"caption": "x", "scenes": [_scene()]}
    bg_key, path = scene_gen._generate_background_with_retry(
        0, sp["scenes"][0], str(tmp_path), sp)
    assert bg_key == "bg_000"
    assert Path(path).exists()
    assert Path(path).read_bytes() == b"fresh-png-bytes"
    assert len(stub_imagen) == 1
    # cache に store された
    entries = bg_cache.list_entries()
    assert len(entries) == 1


# ─── _generate_single_background: cache hit → copy ──


def test_generate_single_background_cache_hit(
        isolated_cache, isolated_assets, stub_imagen, tmp_path):
    _seed_assets(isolated_assets)
    sp = {"caption": "x", "scenes": [_scene()]}
    inputs = scene_gen._scene_bg_inputs(0, sp["scenes"][0], sp, str(tmp_path))
    src = tmp_path / "src.png"
    src.write_bytes(b"hit-png-bytes")
    bg_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_bg_cache_meta(sp["scenes"][0], 0, inputs))

    bg_key, path = scene_gen._generate_single_background(
        0, sp["scenes"][0], str(tmp_path), sp)
    assert Path(path).read_bytes() == b"hit-png-bytes"
    # Imagen は呼ばれていない
    assert stub_imagen == []
    assert sp["scenes"][0].get("_bg_cache_hit") is True


# ─── force_fresh で cache をバイパス ──


def test_generate_single_background_force_fresh(
        isolated_cache, isolated_assets, stub_imagen, tmp_path):
    _seed_assets(isolated_assets)
    sp = {"caption": "x", "scenes": [_scene()]}
    inputs = scene_gen._scene_bg_inputs(0, sp["scenes"][0], sp, str(tmp_path))
    src = tmp_path / "src.png"
    src.write_bytes(b"x")
    bg_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_bg_cache_meta(sp["scenes"][0], 0, inputs))

    bg_key, path = scene_gen._generate_single_background(
        0, sp["scenes"][0], str(tmp_path), sp, force_fresh=True)
    # cache 無視で Imagen 呼出
    assert len(stub_imagen) == 1
    assert Path(path).read_bytes() == b"fresh-png-bytes"


def test_scene_flag_bg_force_fresh(
        isolated_cache, isolated_assets, stub_imagen, tmp_path):
    _seed_assets(isolated_assets)
    scene = _scene()
    scene["bg_force_fresh"] = True
    sp = {"caption": "x", "scenes": [scene]}
    inputs = scene_gen._scene_bg_inputs(0, scene, sp, str(tmp_path))
    src = tmp_path / "src.png"
    src.write_bytes(b"y")
    bg_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_bg_cache_meta(scene, 0, inputs))

    scene_gen._generate_single_background(0, scene, str(tmp_path), sp)
    # force_fresh フラグで cache bypass
    assert len(stub_imagen) == 1


# ─── bg_commit_cache (= 1 scene の cache 採用) ──


def test_bg_commit_cache_copies_and_clears_downstream(
        isolated_cache, isolated_assets, stub_imagen, tmp_path):
    _seed_assets(isolated_assets)
    sp = {"caption": "x", "scenes": [_scene()]}
    inputs = scene_gen._scene_bg_inputs(0, sp["scenes"][0], sp, str(tmp_path))
    src = tmp_path / "src.png"
    src.write_bytes(b"cached-bg")
    bg_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_bg_cache_meta(sp["scenes"][0], 0, inputs))
    # 既存の下流 mp4 を作って削除されることを確認
    (tmp_path / "kling_000.mp4").write_bytes(b"old-kling")
    (tmp_path / "scene_000.trim.mp4").write_bytes(b"old-trim")

    scene_gen.bg_commit_cache(0, sp["scenes"][0], sp, str(tmp_path),
                                inputs["cache_key"])

    bg_path = tmp_path / "bg_000.png"
    assert bg_path.exists()
    assert bg_path.read_bytes() == b"cached-bg"
    # 下流が消されている
    assert not (tmp_path / "kling_000.mp4").exists()
    assert not (tmp_path / "scene_000.trim.mp4").exists()
    assert sp["scenes"][0].get("_bg_cache_hit") is True


# ─── bg_generate_fresh ────────────────────────────


def test_bg_generate_fresh_only_specified_scenes(
        isolated_cache, isolated_assets, stub_imagen, tmp_path):
    _seed_assets(isolated_assets)
    scenes = [
        _scene(background_prompt="zero"),
        _scene(background_prompt="one"),
        _scene(background_prompt="two"),
    ]
    sp = {"caption": "x", "scenes": scenes}

    paths = scene_gen.bg_generate_fresh(sp, str(tmp_path), [0, 2])
    assert len(stub_imagen) == 2
    assert "bg_000" in paths
    assert "bg_002" in paths
    assert "bg_001" not in paths
    assert (tmp_path / "bg_000.png").exists()
    assert not (tmp_path / "bg_001.png").exists()
    assert (tmp_path / "bg_002.png").exists()


# ─── generate_backgrounds 統合 ────────────────────


def test_generate_backgrounds_with_decisions(
        isolated_cache, isolated_assets, stub_imagen, tmp_path):
    _seed_assets(isolated_assets)
    scenes = [
        _scene(background_prompt="zero"),
        _scene(background_prompt="one"),
    ]
    sp = {"caption": "x", "scenes": scenes}

    # scene 0 用に cache 仕込み
    inputs0 = scene_gen._scene_bg_inputs(0, scenes[0], sp, str(tmp_path))
    src = tmp_path / "src.png"
    src.write_bytes(b"cached0")
    bg_cache.store(
        inputs0["cache_key"], src,
        scene_gen._build_bg_cache_meta(scenes[0], 0, inputs0))

    decisions = {
        "0": {"decision": "cache", "decided_key": inputs0["cache_key"]},
        "1": {"decision": "fresh", "decided_key": None},
    }
    paths = scene_gen.generate_backgrounds(
        sp, str(tmp_path), scene_decisions=decisions)
    assert (tmp_path / "bg_000.png").read_bytes() == b"cached0"
    assert (tmp_path / "bg_001.png").exists()
    # scene 1 だけ Imagen
    assert len(stub_imagen) == 1


def test_generate_backgrounds_no_decisions_legacy(
        isolated_cache, isolated_assets, stub_imagen, tmp_path):
    """scene_decisions=None なら従来通り全シーン自動 cache lookup → miss は fresh。"""
    _seed_assets(isolated_assets)
    scenes = [
        _scene(background_prompt="zero"),
        _scene(background_prompt="one"),
    ]
    sp = {"caption": "x", "scenes": scenes}

    scene_gen.generate_backgrounds(sp, str(tmp_path))
    # 両シーン miss → 2 回 Imagen
    assert len(stub_imagen) == 2


# ─── regen_background_scene の force_fresh ──


def test_regen_background_force_fresh(
        isolated_cache, isolated_assets, stub_imagen, tmp_path):
    _seed_assets(isolated_assets)
    sp = {"caption": "x", "scenes": [_scene()]}
    inputs = scene_gen._scene_bg_inputs(0, sp["scenes"][0], sp, str(tmp_path))
    src = tmp_path / "src.png"
    src.write_bytes(b"x")
    bg_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_bg_cache_meta(sp["scenes"][0], 0, inputs))
    # 既存の bg_000.png
    (tmp_path / "bg_000.png").write_bytes(b"existing")

    scene_gen.regen_background_scene(
        0, sp, str(tmp_path), force_fresh=True)
    # cache 無視で Imagen 呼出
    assert len(stub_imagen) == 1
