"""Stage 4 (Kling) の部分失敗ハンドリングを検証する。

`generate_kling_for_screenplay` は 1 シーンの FAL 失敗で stage 全体を
止めず、最後にまとめて :class:`PartialKlingFailure` を raise する。成功
シーンの ``kling_<S>.mp4`` / ``scene_<S>.trim.mp4`` は disk に残るので、
UI から失敗シーンのみ個別に regen して復旧できる。
"""
from pathlib import Path

import pytest

import scene_gen


def _scene(prompt: str = "motion") -> dict:
    return {
        "background_prompt": "bg",
        "animation_prompt": prompt,
        "lines": [{"text": "ok", "start": 0.0, "end": 1.0}],
    }


def test_partial_kling_failure_keeps_successful_artifacts(
    tmp_path, monkeypatch,
):
    """5 シーン中 2 シーン失敗 → PartialKlingFailure raise、成功ファイルは残る。"""
    sp = {"caption": "x", "scenes": [_scene(f"motion-{i}") for i in range(5)]}
    fail = {2, 4}

    def fake_kling(scene_idx, scene, screenplay, temp_dir, force_fresh=False):
        if scene_idx in fail:
            raise RuntimeError(f"FAL failure for scene {scene_idx}")
        # 成功シーンは kling / trim ファイルを書く
        Path(temp_dir, f"kling_{scene_idx:03d}.mp4").write_bytes(b"k")
        Path(temp_dir, f"scene_{scene_idx:03d}.trim.mp4").write_bytes(b"t")

    monkeypatch.setattr(scene_gen, "_kling_for_scene", fake_kling)

    with pytest.raises(scene_gen.PartialKlingFailure) as exc_info:
        scene_gen.generate_kling_for_screenplay(sp, str(tmp_path))

    err = exc_info.value
    assert err.failed_scene_indices == [2, 4]
    assert err.total_scenes == 5
    msg = str(err)
    assert "3/5" in msg
    assert "[2, 4]" in msg

    # 成功シーンの kling / trim は残っている
    for i in (0, 1, 3):
        assert (tmp_path / f"kling_{i:03d}.mp4").exists()
        assert (tmp_path / f"scene_{i:03d}.trim.mp4").exists()
    # 失敗シーンには何も残っていない
    for i in (2, 4):
        assert not (tmp_path / f"kling_{i:03d}.mp4").exists()
        assert not (tmp_path / f"scene_{i:03d}.trim.mp4").exists()


def test_no_failures_returns_normally(tmp_path, monkeypatch):
    """全シーン成功なら例外は raise されない。"""
    sp = {"caption": "x", "scenes": [_scene() for _ in range(3)]}
    calls: list[int] = []

    def fake_kling(scene_idx, *_a, **_kw):
        calls.append(scene_idx)
        Path(tmp_path, f"kling_{scene_idx:03d}.mp4").write_bytes(b"k")

    monkeypatch.setattr(scene_gen, "_kling_for_scene", fake_kling)

    scene_gen.generate_kling_for_screenplay(sp, str(tmp_path))
    assert sorted(calls) == [0, 1, 2]


def test_partial_kling_collects_all_failures(tmp_path, monkeypatch):
    """すべて失敗しても例外は 1 つにまとまる (= 各 index が errors に揃う)。"""
    sp = {"caption": "x", "scenes": [_scene() for _ in range(3)]}

    def always_fail(scene_idx, *_a, **_kw):
        raise RuntimeError(f"boom-{scene_idx}")

    monkeypatch.setattr(scene_gen, "_kling_for_scene", always_fail)

    with pytest.raises(scene_gen.PartialKlingFailure) as exc_info:
        scene_gen.generate_kling_for_screenplay(sp, str(tmp_path))

    err = exc_info.value
    assert err.failed_scene_indices == [0, 1, 2]
    assert "boom-0" in err.errors[0]
    assert "boom-1" in err.errors[1]
    assert "boom-2" in err.errors[2]


def test_partial_kling_with_cache_decisions(tmp_path, monkeypatch):
    """scene_decisions が cache 採用のシーンは kling_commit_cache を経由する。"""
    sp = {"caption": "x", "scenes": [_scene() for _ in range(3)]}
    decisions = {
        "0": {"decision": "cache", "decided_key": "abc"},
        "1": {"decision": "fresh"},
        "2": {"decision": "cache", "decided_key": "def"},
    }

    cache_calls: list[int] = []
    fresh_calls: list[int] = []

    def fake_commit(scene_idx, scene, sp_, temp_dir, key):
        cache_calls.append(scene_idx)
        Path(temp_dir, f"kling_{scene_idx:03d}.mp4").write_bytes(b"k")

    def fake_kling(scene_idx, *_a, **_kw):
        fresh_calls.append(scene_idx)
        Path(tmp_path, f"kling_{scene_idx:03d}.mp4").write_bytes(b"k")

    monkeypatch.setattr(scene_gen, "kling_commit_cache", fake_commit)
    monkeypatch.setattr(scene_gen, "_kling_for_scene", fake_kling)

    scene_gen.generate_kling_for_screenplay(sp, str(tmp_path),
                                             scene_decisions=decisions)
    assert cache_calls == [0, 2]
    assert fresh_calls == [1]
