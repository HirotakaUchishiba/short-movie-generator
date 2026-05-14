"""scene_gen の Stage 4 cache 統合 (scan / commit / generate_fresh) の単体テスト。

FAL / ffmpeg を mock して、cache lookup → copy / store → fresh 生成の
パスを検証する。
"""
from pathlib import Path

import pytest

import config
import kling_cache
import scene_gen


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(
        config, "KLING_CACHE_DIR", str(tmp_path / "kling_cache"))
    monkeypatch.setattr(config, "KLING_CACHE_ENABLED", True)
    monkeypatch.setattr(config, "KLING_CACHE_VERSION", "v1")
    monkeypatch.setattr(config, "KLING_CACHE_REQUIRE_APPROVAL", False)
    monkeypatch.setattr(config, "KLING_CACHE_TTL_DAYS", 365)
    monkeypatch.setattr(config, "KLING_CACHE_MISMATCH_THRESHOLD", 0.30)
    monkeypatch.setattr(config, "KLING_CACHE_AUTO_PRUNE", False)
    return tmp_path / "kling_cache"


@pytest.fixture
def stub_pipeline(monkeypatch):
    """trim / slow_mo / FAL を mock。kling cache の挙動だけ純粋検証する。"""
    # ffprobe duration: 単に固定値を返す
    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 5.0)
    # _trim_video: 入力をコピーして trim を模倣
    def _fake_trim(src, dur, dst):
        Path(dst).write_bytes(Path(src).read_bytes())
    monkeypatch.setattr(scene_gen, "_trim_video", _fake_trim)
    # 実 FAL は呼ばない
    fal_calls: list[dict] = []
    def _fake_generate_kling(bg_path, anim, duration, out, idx):
        Path(out).write_bytes(b"fresh-kling-bytes")
        fal_calls.append({
            "bg_path": bg_path, "duration": duration, "scene_idx": idx,
            "anim": anim,
        })
    monkeypatch.setattr(scene_gen, "_generate_kling", _fake_generate_kling)
    return fal_calls


def _scene(duration=4.5, animation_prompt="subject sits at desk",
           camera_distance="medium-close", location_ref="home_office"):
    identity = {
        "character_refs": ["f1__office"],
        "location_ref": location_ref,
        "start_emotion": "中立",
        "camera_distance": camera_distance,
    }
    return {
        "duration": duration,
        "animation_prompt": animation_prompt,
        "background_prompt": "subject in office",
        "identity": identity,
        "lines": [{"text": "やったー", "start": 0.0, "end": 1.0}],
    }


def _make_bg(temp_dir: Path, scene_idx: int = 0,
             content: bytes = b"bg-png-bytes-A") -> Path:
    p = temp_dir / f"bg_{scene_idx:03d}.png"
    p.write_bytes(content)
    return p


# ─── _scene_kling_inputs ─────────────────────────────────


def test_scene_kling_inputs_returns_none_when_bg_missing(
        isolated_cache, tmp_path):
    sp = {"caption": "x", "scenes": [_scene()]}
    inputs = scene_gen._scene_kling_inputs(0, sp["scenes"][0], sp, str(tmp_path))
    assert inputs is None


def test_scene_kling_inputs_computes_cache_key(
        isolated_cache, tmp_path, stub_pipeline):
    _make_bg(tmp_path)
    sp = {"caption": "x", "scenes": [_scene()]}
    inputs = scene_gen._scene_kling_inputs(0, sp["scenes"][0], sp, str(tmp_path))
    assert inputs is not None
    assert inputs["kling_duration"] == 5  # 4.5s → 5s クリップ
    assert len(inputs["cache_key"]) == 16
    assert inputs["bg_image_sha"]
    assert "subject sits at desk" in inputs["augmented_prompt"]


# ─── _kling_for_scene: cache miss → fresh ──


def test_kling_for_scene_cache_miss_then_store(
        isolated_cache, tmp_path, stub_pipeline):
    _make_bg(tmp_path)
    sp = {"caption": "x", "scenes": [_scene()]}
    scene_gen._kling_for_scene(0, sp["scenes"][0], sp, str(tmp_path))

    # FAL は呼ばれた
    assert len(stub_pipeline) == 1
    # raw mp4 が出来た
    raw = tmp_path / "kling_000.mp4"
    assert raw.exists()
    # cache に store された (hit_count=0 だが entry は存在)
    entries = kling_cache.list_entries()
    assert len(entries) == 1
    # scene に hit hint がついた
    assert sp["scenes"][0].get("_kling_cache_hit") is False
    assert sp["scenes"][0].get("_kling_cache_key")


# ─── _kling_for_scene: cache hit → copy ──


def test_kling_for_scene_cache_hit_copies_without_fal(
        isolated_cache, tmp_path, stub_pipeline):
    _make_bg(tmp_path)
    sp = {"caption": "x", "scenes": [_scene()]}
    inputs = scene_gen._scene_kling_inputs(0, sp["scenes"][0], sp, str(tmp_path))
    assert inputs is not None
    # 事前に cache に entry を store する (= 別 project 由来を simulating)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"cache-hit-bytes")
    kling_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_kling_cache_meta(sp["scenes"][0], inputs))

    # 実行
    stub_pipeline.clear()
    scene_gen._kling_for_scene(0, sp["scenes"][0], sp, str(tmp_path))

    # FAL は呼ばれていない
    assert stub_pipeline == []
    # raw mp4 = cache 由来
    raw = tmp_path / "kling_000.mp4"
    assert raw.exists()
    assert raw.read_bytes() == b"cache-hit-bytes"
    # hit hint
    assert sp["scenes"][0].get("_kling_cache_hit") is True
    assert sp["scenes"][0].get("_kling_cache_key") == inputs["cache_key"]
    # hit_count++
    entries = kling_cache.list_entries()
    assert entries[0]["hit_count"] == 1


# ─── force_fresh / scene flag で cache をバイパス ──


def test_kling_for_scene_force_fresh_bypasses_cache(
        isolated_cache, tmp_path, stub_pipeline):
    _make_bg(tmp_path)
    sp = {"caption": "x", "scenes": [_scene()]}
    inputs = scene_gen._scene_kling_inputs(0, sp["scenes"][0], sp, str(tmp_path))
    src = tmp_path / "src.mp4"
    src.write_bytes(b"cache-hit-bytes")
    kling_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_kling_cache_meta(sp["scenes"][0], inputs))

    scene_gen._kling_for_scene(
        0, sp["scenes"][0], sp, str(tmp_path), force_fresh=True)

    # FAL が呼ばれた (= cache bypass された)
    assert len(stub_pipeline) == 1
    assert sp["scenes"][0].get("_kling_cache_hit") is False


def test_kling_for_scene_scene_flag_force_fresh(
        isolated_cache, tmp_path, stub_pipeline):
    _make_bg(tmp_path)
    scene = _scene()
    scene["kling_force_fresh"] = True
    sp = {"caption": "x", "scenes": [scene]}
    inputs = scene_gen._scene_kling_inputs(0, scene, sp, str(tmp_path))
    src = tmp_path / "src.mp4"
    src.write_bytes(b"cached")
    kling_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_kling_cache_meta(scene, inputs))

    scene_gen._kling_for_scene(0, scene, sp, str(tmp_path))
    assert len(stub_pipeline) == 1


# ─── kling_scan_cache ─────────────────────────────────────


def test_kling_scan_cache_no_candidate_marks_fresh(
        isolated_cache, tmp_path, stub_pipeline):
    _make_bg(tmp_path)
    sp = {"caption": "x", "scenes": [_scene()]}
    decisions = scene_gen.kling_scan_cache(sp, str(tmp_path))
    assert "0" in decisions
    rec = decisions["0"]
    assert rec["candidates"] == []
    assert rec["decision"] == "fresh"
    assert rec["cache_key"] is not None


def test_kling_scan_cache_finds_existing_entry(
        isolated_cache, tmp_path, stub_pipeline):
    _make_bg(tmp_path)
    sp = {"caption": "x", "scenes": [_scene()]}
    inputs = scene_gen._scene_kling_inputs(0, sp["scenes"][0], sp, str(tmp_path))
    src = tmp_path / "src.mp4"
    src.write_bytes(b"foo")
    kling_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_kling_cache_meta(sp["scenes"][0], inputs))

    decisions = scene_gen.kling_scan_cache(sp, str(tmp_path))
    rec = decisions["0"]
    assert len(rec["candidates"]) == 1
    assert rec["candidates"][0]["key"] == inputs["cache_key"]
    # 候補ありなので auto-fresh 確定にならず pending のまま
    assert rec["decision"] == "pending"


def test_kling_scan_cache_diagnostics_when_bg_missing(
        isolated_cache, tmp_path, stub_pipeline):
    sp = {"caption": "x", "scenes": [_scene()]}
    decisions = scene_gen.kling_scan_cache(sp, str(tmp_path))
    rec = decisions["0"]
    assert rec["candidates"] == []
    assert "bg or TTS not ready" in rec["diagnostics"][0]


# ─── kling_commit_cache: cache 採用フロー ──


def test_kling_commit_cache_copies_and_trims(
        isolated_cache, tmp_path, stub_pipeline):
    _make_bg(tmp_path)
    scene = _scene()
    sp = {"caption": "x", "scenes": [scene]}
    inputs = scene_gen._scene_kling_inputs(0, scene, sp, str(tmp_path))
    src = tmp_path / "src.mp4"
    src.write_bytes(b"committed-bytes")
    kling_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_kling_cache_meta(scene, inputs))

    # 実行
    scene_gen.kling_commit_cache(
        0, scene, sp, str(tmp_path), inputs["cache_key"])

    # raw + trim 両方できている
    raw = tmp_path / "kling_000.mp4"
    trim = tmp_path / "scene_000.trim.mp4"
    assert raw.exists()
    assert trim.exists()
    assert raw.read_bytes() == b"committed-bytes"
    # FAL は呼ばれていない
    assert stub_pipeline == []
    # scene に hit hint
    assert scene.get("_kling_cache_hit") is True
    assert scene.get("_kling_cache_key") == inputs["cache_key"]


# ─── kling_generate_fresh ─────────────────────────────


def test_kling_generate_fresh_only_specified_scenes(
        isolated_cache, tmp_path, stub_pipeline):
    for i in range(3):
        _make_bg(tmp_path, i)
    scenes = [_scene() for _ in range(3)]
    sp = {"caption": "x", "scenes": scenes}

    # シーン 0 と 2 だけ fresh
    scene_gen.kling_generate_fresh(sp, str(tmp_path), [0, 2])

    # FAL が 2 回呼ばれた
    assert len(stub_pipeline) == 2
    assert {c["scene_idx"] for c in stub_pipeline} == {0, 2}
    # シーン 1 は触られていない
    assert not (tmp_path / "kling_001.mp4").exists()
    assert (tmp_path / "kling_000.mp4").exists()
    assert (tmp_path / "kling_002.mp4").exists()


# ─── generate_kling_for_screenplay (= 統合パス) ──


def test_generate_kling_for_screenplay_with_decisions(
        isolated_cache, tmp_path, stub_pipeline):
    # シーン 0 / 1 で別々の bg content (= 別 cache key) を使う
    _make_bg(tmp_path, 0, content=b"bg-zero")
    _make_bg(tmp_path, 1, content=b"bg-one")
    scenes = [
        _scene(animation_prompt="scene zero motion"),
        _scene(animation_prompt="scene one motion"),
    ]
    sp = {"caption": "x", "scenes": scenes}

    # scene 0 用に cache を store
    inputs0 = scene_gen._scene_kling_inputs(0, scenes[0], sp, str(tmp_path))
    src = tmp_path / "src0.mp4"
    src.write_bytes(b"cached0")
    kling_cache.store(
        inputs0["cache_key"], src,
        scene_gen._build_kling_cache_meta(scenes[0], inputs0))

    decisions = {
        "0": {"decision": "cache", "decided_key": inputs0["cache_key"]},
        "1": {"decision": "fresh", "decided_key": None},
    }
    scene_gen.generate_kling_for_screenplay(
        sp, str(tmp_path), scene_decisions=decisions)

    # scene 0 は cache 由来、scene 1 は FAL
    assert (tmp_path / "kling_000.mp4").read_bytes() == b"cached0"
    assert (tmp_path / "kling_001.mp4").exists()
    assert len(stub_pipeline) == 1  # scene 1 だけ FAL
    assert stub_pipeline[0]["scene_idx"] == 1


def test_generate_kling_for_screenplay_no_decisions_legacy(
        isolated_cache, tmp_path, stub_pipeline):
    """scene_decisions=None なら従来通り全シーン自動 cache lookup → miss は fresh。"""
    _make_bg(tmp_path, 0, content=b"bg-zero")
    _make_bg(tmp_path, 1, content=b"bg-one")
    scenes = [
        _scene(animation_prompt="scene zero motion"),
        _scene(animation_prompt="scene one motion"),
    ]
    sp = {"caption": "x", "scenes": scenes}

    scene_gen.generate_kling_for_screenplay(sp, str(tmp_path))
    # 両シーンとも cache miss だったので 2 回 FAL
    assert len(stub_pipeline) == 2


# ─── regen_kling_scene の force_fresh デフォ ──


def test_regen_kling_scene_force_fresh_default(
        isolated_cache, tmp_path, stub_pipeline):
    _make_bg(tmp_path)
    sp = {"caption": "x", "scenes": [_scene()]}
    inputs = scene_gen._scene_kling_inputs(0, sp["scenes"][0], sp, str(tmp_path))
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    kling_cache.store(
        inputs["cache_key"], src,
        scene_gen._build_kling_cache_meta(sp["scenes"][0], inputs))

    # 既に raw が出来ている状態で regen → 削除 → 再生成 (cache bypass)
    (tmp_path / "kling_000.mp4").write_bytes(b"existing")
    scene_gen.regen_kling_scene(0, sp, str(tmp_path))
    # cache hit ではなく fresh 生成 (= force_fresh デフォ True)
    assert len(stub_pipeline) == 1
    assert sp["scenes"][0].get("_kling_cache_hit") is False
