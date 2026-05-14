"""Stage 3 (BG) 並列生成での部分失敗ハンドリングを検証する。

ThreadPoolExecutor 内で 1 シーンが Imagen 例外で落ちても、他の成功シーンの
artifact (= ``tmp/bg_<S>.png``) は保持され、PartialBackgroundFailure として
失敗シーン番号と一緒に raise されることを確認する。
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


def _scene(prompt: str = "subject in office"):
    identity = {
        "character_refs": ["f1__office"],
        "location_ref": "home_office",
        "start_emotion": "中立",
        "camera_distance": "medium-close",
    }
    return {
        "characters": [{"name": "f1__office"}],
        "identity": identity,
        "background_prompt": prompt,
        "lines": [{"text": "ok", "start": 0.0, "end": 1.0}],
    }


@pytest.fixture
def stub_imagen_with_failures(monkeypatch):
    """Imagen を「指定 scene_idx だけ例外、他は成功」でモックする。

    scene_idx は generate_image の path (= ``bg_<S>.png``) から抽出する。
    """
    fail_scenes: set[int] = set()
    calls: list[dict] = []

    def _fake_generate_image(prompt, path, reference_images=None):
        # path 末尾の bg_<NNN>.png から index を取り出す
        name = Path(path).name
        try:
            idx = int(name.removeprefix("bg_").split(".")[0])
        except ValueError:
            idx = -1
        calls.append({"path": path, "scene_idx": idx})
        if idx in fail_scenes:
            raise RuntimeError(f"intentional Imagen failure for scene {idx}")
        Path(path).write_bytes(b"fresh-png-bytes")

    import imagen_client
    monkeypatch.setattr(imagen_client, "generate_image", _fake_generate_image)
    monkeypatch.setattr(scene_gen, "_detect_storyboard_image", lambda p: False)
    return {"fail_scenes": fail_scenes, "calls": calls}


# ─── 1. 5 シーン中 1 シーン失敗 ──────────────────────────


def test_partial_failure_keeps_successful_artifacts(
        isolated_cache, isolated_assets, stub_imagen_with_failures, tmp_path):
    _seed_assets(isolated_assets)
    sp = {"caption": "x", "scenes": [_scene(f"prompt-{i}") for i in range(5)]}
    # scene index 2 だけ失敗させる
    stub_imagen_with_failures["fail_scenes"].add(2)

    with pytest.raises(scene_gen.PartialBackgroundFailure) as excinfo:
        scene_gen.generate_backgrounds(sp, str(tmp_path))

    err = excinfo.value
    assert err.failed_scene_indices == [2]
    assert err.total_scenes == 5
    msg = str(err)
    assert "4/5" in msg
    assert "[2]" in msg
    # 成功シーンの bg ファイルは残っている
    for i in [0, 1, 3, 4]:
        assert (tmp_path / f"bg_{i:03d}.png").exists()
    # 失敗シーンの bg ファイルは存在しない
    assert not (tmp_path / "bg_002.png").exists()


# ─── 2. 失敗ゼロなら通常通り成功 ─────────────────────────


def test_no_failures_returns_paths_normally(
        isolated_cache, isolated_assets, stub_imagen_with_failures, tmp_path):
    _seed_assets(isolated_assets)
    sp = {"caption": "x", "scenes": [_scene(f"prompt-{i}") for i in range(3)]}

    paths = scene_gen.generate_backgrounds(sp, str(tmp_path))
    assert len(paths) == 3
    for i in range(3):
        assert (tmp_path / f"bg_{i:03d}.png").exists()


# ─── 3. 全シーン失敗 ─────────────────────────────────


def test_all_scenes_failure_lists_all(
        isolated_cache, isolated_assets, stub_imagen_with_failures, tmp_path):
    _seed_assets(isolated_assets)
    sp = {"caption": "x", "scenes": [_scene(f"prompt-{i}") for i in range(3)]}
    stub_imagen_with_failures["fail_scenes"].update({0, 1, 2})

    with pytest.raises(scene_gen.PartialBackgroundFailure) as excinfo:
        scene_gen.generate_backgrounds(sp, str(tmp_path))

    err = excinfo.value
    assert err.failed_scene_indices == [0, 1, 2]
    assert err.total_scenes == 3
    msg = str(err)
    assert "0/3" in msg
    assert "[0, 1, 2]" in msg


# ─── 4. 失敗シーンだけ個別再実行で復旧できる ────────────


def test_partial_failure_then_per_scene_regen(
        isolated_cache, isolated_assets, stub_imagen_with_failures, tmp_path):
    _seed_assets(isolated_assets)
    sp = {"caption": "x", "scenes": [_scene(f"prompt-{i}") for i in range(4)]}
    # 最初の試行: scene 1 と scene 3 が失敗
    stub_imagen_with_failures["fail_scenes"].update({1, 3})
    with pytest.raises(scene_gen.PartialBackgroundFailure) as excinfo:
        scene_gen.generate_backgrounds(sp, str(tmp_path))
    assert excinfo.value.failed_scene_indices == [1, 3]
    # 失敗 2 シーンのファイルは無い
    assert not (tmp_path / "bg_001.png").exists()
    assert not (tmp_path / "bg_003.png").exists()
    # 成功 2 シーンは残っている
    assert (tmp_path / "bg_000.png").exists()
    assert (tmp_path / "bg_002.png").exists()

    # 復旧: 失敗集合を空にして個別 fresh で再実行
    stub_imagen_with_failures["fail_scenes"].clear()
    paths = scene_gen.bg_generate_fresh(sp, str(tmp_path), [1, 3])
    assert "bg_001" in paths
    assert "bg_003" in paths
    assert (tmp_path / "bg_001.png").exists()
    assert (tmp_path / "bg_003.png").exists()


# ─── 5. scene_decisions 経路: cache 採用シーンは fresh 失敗時に保持される ──


def test_partial_failure_with_cache_decisions(
        isolated_cache, isolated_assets, stub_imagen_with_failures, tmp_path):
    _seed_assets(isolated_assets)
    scenes = [_scene(f"prompt-{i}") for i in range(3)]
    sp = {"caption": "x", "scenes": scenes}

    # scene 0 用に cache を仕込む (= "cache" 採用想定)
    inputs0 = scene_gen._scene_bg_inputs(0, scenes[0], sp, str(tmp_path))
    src = tmp_path / "src.png"
    src.write_bytes(b"cached-bg-bytes")
    bg_cache.store(
        inputs0["cache_key"], src,
        scene_gen._build_bg_cache_meta(scenes[0], 0, inputs0))

    # scene 2 が fresh 経路で失敗
    stub_imagen_with_failures["fail_scenes"].add(2)
    decisions = {
        "0": {"decision": "cache", "decided_key": inputs0["cache_key"]},
        "1": {"decision": "fresh", "decided_key": None},
        "2": {"decision": "fresh", "decided_key": None},
    }

    with pytest.raises(scene_gen.PartialBackgroundFailure) as excinfo:
        scene_gen.generate_backgrounds(
            sp, str(tmp_path), scene_decisions=decisions)
    err = excinfo.value
    assert err.failed_scene_indices == [2]
    # cache 採用シーンの artifact は確定保持
    assert (tmp_path / "bg_000.png").read_bytes() == b"cached-bg-bytes"
    # fresh で成功した scene 1 も保持
    assert (tmp_path / "bg_001.png").exists()
    # fresh で失敗した scene 2 は無い
    assert not (tmp_path / "bg_002.png").exists()


# ─── 6. bg_force_fresh の cleanup は失敗時にも走る ─────────


def test_bg_force_fresh_flag_cleared_after_partial_failure(
        isolated_cache, isolated_assets, stub_imagen_with_failures, tmp_path):
    _seed_assets(isolated_assets)
    sp = {"caption": "x", "scenes": [_scene(f"prompt-{i}") for i in range(3)]}
    stub_imagen_with_failures["fail_scenes"].add(1)
    with pytest.raises(scene_gen.PartialBackgroundFailure):
        scene_gen.bg_generate_fresh(sp, str(tmp_path), [0, 1, 2])
    # finally で hint が削除されているはず
    for s in sp["scenes"]:
        assert "bg_force_fresh" not in s
