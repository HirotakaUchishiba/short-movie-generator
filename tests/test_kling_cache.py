"""kling_cache のキー算出 / store / lookup / 適合度判定 / 品質ガード /
prune / blacklist の単体テスト。bg_cache テストと同じスタイルで構成。"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import config
import kling_cache


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
    monkeypatch.setattr(config, "ACTION_FRONTLOAD_RATIO", 0.7)
    monkeypatch.setattr(config, "KLING_DURATION_TOLERANCE_RATIO", 1.2)
    return tmp_path / "kling_cache"


def _make_mp4(path: Path, content: bytes = b"fake-mp4-bytes") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _build_meta(
    *,
    kling_duration: int = 5,
    original_audio: float = 4.5,
    camera_distance: str | None = "medium-close",
    location_ref: str | None = "home_office",
    blacklisted: bool = False,
    ffprobe_ok: bool = True,
    approved: bool = True,
    final_render_completed: bool = False,
    created_at: str | None = None,
) -> dict:
    return {
        "augmented_animation_prompt": "test prompt",
        "kling_duration": kling_duration,
        "bg_image_sha": "deadbeefcafebabe",
        "model_id": "fal-ai/kling-video/v3/standard/image-to-video",
        "aspect_ratio": "9:16",
        "cache_version": "v1",
        "frontload_ratio": 0.7,
        "original_audio_duration": original_audio,
        "camera_distance": camera_distance,
        "location_ref": location_ref,
        **({"created_at": created_at} if created_at else {}),
        "quality": {
            "blacklisted": blacklisted,
            "blacklist_reason": None,
            "ffprobe_ok": ffprobe_ok,
            "approved_at_origin": "2026-01-01T00:00:00Z" if approved else None,
            "final_render_completed": final_render_completed,
        },
    }


# ─── build_cache_key ───────────────────────


def test_key_is_deterministic(isolated_cache):
    k1 = kling_cache.build_cache_key(
        "prompt A", 5, "shaA", "model-a", "9:16", "v1")
    k2 = kling_cache.build_cache_key(
        "prompt A", 5, "shaA", "model-a", "9:16", "v1")
    assert k1 == k2
    assert len(k1) == 16


def test_key_changes_with_prompt(isolated_cache):
    k1 = kling_cache.build_cache_key("prompt A", 5, "shaA", "m", "9:16", "v1")
    k2 = kling_cache.build_cache_key("prompt B", 5, "shaA", "m", "9:16", "v1")
    assert k1 != k2


def test_key_changes_with_kling_duration(isolated_cache):
    k1 = kling_cache.build_cache_key("p", 5, "shaA", "m", "9:16", "v1")
    k2 = kling_cache.build_cache_key("p", 10, "shaA", "m", "9:16", "v1")
    assert k1 != k2


def test_key_changes_with_bg_sha(isolated_cache):
    k1 = kling_cache.build_cache_key("p", 5, "shaA", "m", "9:16", "v1")
    k2 = kling_cache.build_cache_key("p", 5, "shaB", "m", "9:16", "v1")
    assert k1 != k2


def test_key_changes_with_model_id(isolated_cache):
    k1 = kling_cache.build_cache_key("p", 5, "shaA", "m1", "9:16", "v1")
    k2 = kling_cache.build_cache_key("p", 5, "shaA", "m2", "9:16", "v1")
    assert k1 != k2


def test_key_changes_with_cache_version(isolated_cache):
    k1 = kling_cache.build_cache_key("p", 5, "shaA", "m", "9:16", "v1")
    k2 = kling_cache.build_cache_key("p", 5, "shaA", "m", "9:16", "v2")
    assert k1 != k2


def test_key_uses_config_default_version(isolated_cache, monkeypatch):
    monkeypatch.setattr(config, "KLING_CACHE_VERSION", "vX")
    k1 = kling_cache.build_cache_key("p", 5, "shaA", "m")
    k2 = kling_cache.build_cache_key("p", 5, "shaA", "m", "9:16", "vX")
    assert k1 == k2


# ─── store / lookup / commit_to_project ───


def test_store_then_lookup_hit(isolated_cache, tmp_path):
    src = tmp_path / "raw.mp4"
    _make_mp4(src, b"hello-mp4")
    kling_cache.store("aabbccddeeff0011", src, _build_meta())
    found = kling_cache.lookup("aabbccddeeff0011")
    assert found is not None
    assert found.read_bytes() == b"hello-mp4"


def test_lookup_miss_returns_none(isolated_cache):
    assert kling_cache.lookup("0000000000000000") is None


def test_store_is_idempotent(isolated_cache, tmp_path):
    src = tmp_path / "raw.mp4"
    _make_mp4(src, b"first")
    kling_cache.store("k1", src, _build_meta())
    src.write_bytes(b"second")
    kling_cache.store("k1", src, _build_meta())  # 既存なら no-op
    found = kling_cache.lookup("k1")
    assert found is not None
    assert found.read_bytes() == b"first"


def test_commit_to_project_copies(isolated_cache, tmp_path):
    src = tmp_path / "raw.mp4"
    _make_mp4(src, b"clip-bytes")
    kling_cache.store("kcopy", src, _build_meta())
    dest_dir = tmp_path / "proj"
    dest_dir.mkdir()
    dest = dest_dir / "kling_002.mp4"
    res = kling_cache.commit_to_project("kcopy", dest)
    assert res == dest
    assert dest.exists()
    assert dest.read_bytes() == b"clip-bytes"
    # touch されたか確認
    import json
    meta = json.loads((isolated_cache / "kcopy.json").read_text())
    assert meta["hit_count"] == 1


def test_commit_to_project_missing_raises(isolated_cache, tmp_path):
    with pytest.raises(FileNotFoundError):
        kling_cache.commit_to_project("nope", tmp_path / "out.mp4")


def test_touch_increments_hit_count(isolated_cache, tmp_path):
    src = tmp_path / "raw.mp4"
    _make_mp4(src)
    kling_cache.store("kt", src, _build_meta())
    kling_cache.touch("kt")
    kling_cache.touch("kt")
    kling_cache.touch("kt")
    import json
    meta = json.loads((isolated_cache / "kt.json").read_text())
    assert meta["hit_count"] == 3


# ─── L2 適合度判定 ─────────────────────────


def test_lookup_all_candidates_hit_basic(isolated_cache, tmp_path):
    src = tmp_path / "raw.mp4"
    _make_mp4(src)
    kling_cache.store(
        "k_basic", src, _build_meta(kling_duration=5, original_audio=4.5))
    cands = kling_cache.lookup_all_candidates(
        "k_basic", new_audio_duration=4.6, scene_camera_distance="medium-close")
    assert len(cands) == 1
    assert cands[0]["key"] == "k_basic"
    assert cands[0]["fitness"] > 0.9


def test_l2_action_completion_rejects(isolated_cache, tmp_path):
    """新 audio が 動作完了点 (= kling_duration × frontload_ratio) より短いと reject。"""
    src = tmp_path / "raw.mp4"
    _make_mp4(src)
    # kling 10s × frontload 0.7 = 動作完了点 7.0s
    kling_cache.store(
        "k_action", src, _build_meta(kling_duration=10, original_audio=8.0))
    # 新 audio 5.0s → 7.0s より短い → reject
    cands = kling_cache.lookup_all_candidates(
        "k_action", new_audio_duration=5.0, scene_camera_distance="medium-close")
    assert cands == []
    diag = kling_cache.diagnose_candidate("k_action", 5.0, "medium-close")
    assert not diag["ok"]
    assert any("動作完了点" in r for r in diag["rejected_reasons"])


def test_l2_mismatch_threshold_rejects(isolated_cache, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "KLING_CACHE_MISMATCH_THRESHOLD", 0.20)
    src = tmp_path / "raw.mp4"
    _make_mp4(src)
    kling_cache.store(
        "k_mis", src, _build_meta(kling_duration=10, original_audio=8.0))
    # 新 audio 11.0s → 乖離 (11-8)/8 = 37.5% > 20% → reject
    # ただし 11s > kling 10s × 1.2 = 12s 以内なので tolerance は OK
    diag = kling_cache.diagnose_candidate("k_mis", 11.0, "medium-close")
    # まず動作完了点は 7s なので OK、tolerance 12s も OK、乖離率で reject
    assert any("乖離率" in r for r in diag["rejected_reasons"])


def test_l2_camera_distance_mismatch_rejects(isolated_cache, tmp_path):
    src = tmp_path / "raw.mp4"
    _make_mp4(src)
    kling_cache.store(
        "k_cam", src,
        _build_meta(kling_duration=5, original_audio=4.5, camera_distance="wide"))
    cands = kling_cache.lookup_all_candidates(
        "k_cam", new_audio_duration=4.5, scene_camera_distance="close-up")
    assert cands == []


def test_l2_warning_for_moderate_diff(isolated_cache, tmp_path, monkeypatch):
    """乖離率が threshold 以下だが threshold/2 超なら warnings が出る。"""
    monkeypatch.setattr(config, "KLING_CACHE_MISMATCH_THRESHOLD", 0.30)
    src = tmp_path / "raw.mp4"
    _make_mp4(src)
    kling_cache.store(
        "k_warn", src,
        _build_meta(kling_duration=5, original_audio=4.0))
    # 4.8s vs 4.0s = 20% (= threshold 30% 内 / threshold/2=15% 超)
    cands = kling_cache.lookup_all_candidates(
        "k_warn", new_audio_duration=4.8, scene_camera_distance="medium-close")
    assert len(cands) == 1
    assert any("乖離率" in w for w in cands[0]["warnings"])


# ─── L3 品質ガード ────────────────────────


def test_l3_blacklist_rejects(isolated_cache, tmp_path):
    src = tmp_path / "raw.mp4"
    _make_mp4(src)
    kling_cache.store("k_bl", src, _build_meta())
    kling_cache.blacklist("k_bl", "キャラ崩壊")
    cands = kling_cache.lookup_all_candidates(
        "k_bl", 4.5, "medium-close")
    assert cands == []
    # 解除すれば戻る
    kling_cache.unblacklist("k_bl")
    cands = kling_cache.lookup_all_candidates(
        "k_bl", 4.5, "medium-close")
    assert len(cands) == 1


def test_l3_ffprobe_failed_rejects(isolated_cache, tmp_path):
    src = tmp_path / "raw.mp4"
    _make_mp4(src)
    kling_cache.store("k_ff", src, _build_meta(ffprobe_ok=False))
    cands = kling_cache.lookup_all_candidates(
        "k_ff", 4.5, "medium-close")
    assert cands == []


def test_l3_require_approval(isolated_cache, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "KLING_CACHE_REQUIRE_APPROVAL", True)
    src = tmp_path / "raw.mp4"
    _make_mp4(src)
    kling_cache.store("k_unapp", src, _build_meta(approved=False))
    cands = kling_cache.lookup_all_candidates(
        "k_unapp", 4.5, "medium-close")
    assert cands == []
    # mark してから再度 → hit
    kling_cache.mark_origin_approved("k_unapp")
    cands = kling_cache.lookup_all_candidates(
        "k_unapp", 4.5, "medium-close")
    assert len(cands) == 1


def test_l3_ttl_expired_rejects(isolated_cache, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "KLING_CACHE_TTL_DAYS", 30)
    src = tmp_path / "raw.mp4"
    _make_mp4(src)
    kling_cache.store("k_old", src, _build_meta())
    # created_at を 100 日前に書き換え
    import json
    p = isolated_cache / "k_old.json"
    meta = json.loads(p.read_text())
    old = datetime.now(timezone.utc) - timedelta(days=100)
    meta["created_at"] = old.isoformat(timespec="milliseconds")
    p.write_text(json.dumps(meta))
    cands = kling_cache.lookup_all_candidates(
        "k_old", 4.5, "medium-close")
    assert cands == []


def test_l3_promote_marks_final_render(isolated_cache, tmp_path):
    src = tmp_path / "raw.mp4"
    _make_mp4(src)
    kling_cache.store("k_prom", src, _build_meta(final_render_completed=False))
    assert kling_cache.promote("k_prom") is True
    import json
    meta = json.loads((isolated_cache / "k_prom.json").read_text())
    assert meta["quality"]["final_render_completed"] is True


# ─── L4 ユーザ override (env / scene flag) ──


def test_disabled_returns_no_candidates(isolated_cache, tmp_path, monkeypatch):
    src = tmp_path / "raw.mp4"
    _make_mp4(src)
    kling_cache.store("k_dis", src, _build_meta())
    monkeypatch.setattr(config, "KLING_CACHE_ENABLED", False)
    cands = kling_cache.lookup_all_candidates(
        "k_dis", 4.5, "medium-close")
    assert cands == []


# ─── prune (LRU) ────────────────────────


def test_prune_under_limit_does_nothing(isolated_cache, tmp_path):
    src = tmp_path / "raw.mp4"
    _make_mp4(src, b"x" * 100)
    kling_cache.store("a", src, _build_meta())
    res = kling_cache.prune(max_total_bytes=1000)
    assert res["deleted"] == []


def test_prune_evicts_lru(isolated_cache, tmp_path):
    """容量超過時、last_used_at が古い順に削除される。"""
    import time
    for label in ["old", "mid", "new"]:
        src = tmp_path / f"{label}.mp4"
        _make_mp4(src, b"x" * 1000)
        kling_cache.store(label, src, _build_meta())
        time.sleep(0.01)
        kling_cache.touch(label)
    res = kling_cache.prune(max_total_bytes=1500)
    deleted_keys = {d["key"] for d in res["deleted"]}
    assert "old" in deleted_keys
    assert "new" not in deleted_keys
    assert kling_cache.lookup("old") is None
    assert kling_cache.lookup("new") is not None


def test_prune_dry_run_does_not_delete(isolated_cache, tmp_path):
    src = tmp_path / "raw.mp4"
    _make_mp4(src, b"x" * 1000)
    kling_cache.store("a", src, _build_meta())
    res = kling_cache.prune(max_total_bytes=500, dry_run=True)
    assert len(res["deleted"]) == 1
    assert kling_cache.lookup("a") is not None


def test_list_entries_returns_metadata(isolated_cache, tmp_path):
    src = tmp_path / "raw.mp4"
    _make_mp4(src, b"x" * 500)
    kling_cache.store(
        "k_list", src,
        _build_meta(kling_duration=10, original_audio=7.2,
                    location_ref="cafe_barista"))
    entries = kling_cache.list_entries()
    assert len(entries) == 1
    e = entries[0]
    assert e["key"] == "k_list"
    assert e["size_bytes"] == 500
    assert e["kling_duration"] == 10
    assert e["original_audio_duration"] == 7.2
    assert e["location_ref"] == "cafe_barista"


# ─── auto prune (= store 時に自動 prune) ──


def test_store_auto_prune_when_enabled(isolated_cache, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "KLING_CACHE_AUTO_PRUNE", True)
    monkeypatch.setattr(config, "KLING_CACHE_MAX_BYTES", 2000)
    import time
    for label in ["aa", "bb", "cc"]:
        src = tmp_path / f"{label}.mp4"
        _make_mp4(src, b"y" * 1000)
        kling_cache.store(label, src, _build_meta())
        time.sleep(0.01)
        kling_cache.touch(label)
    # 3 * 1000 = 3000 bytes、上限 2000 → 1 つ以上 evict されるはず
    entries = kling_cache.list_entries()
    total = sum(e["size_bytes"] for e in entries)
    assert total <= 2000
