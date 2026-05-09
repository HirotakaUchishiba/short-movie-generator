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


def test_resume_skips_completed_scenes(tmp_path, monkeypatch):
    """既に kling_<i>.mp4 が valid に存在する scene は再生成されない。

    Stage 4 の途中で server crash → resume したケースの回帰テスト。
    `_kling_for_scene` の既存スキップ (artifact_integrity 経由) が機能していること
    を、generate_kling_for_screenplay 全体で確認する。
    """
    sp = {"caption": "x", "scenes": [_scene(f"motion-{i}") for i in range(4)]}
    # 0, 1 は前 run で完了している前提でファイルを置く (= 任意の bytes でも OK
    # なように artifact_integrity チェックを True に固定)
    for i in (0, 1):
        Path(tmp_path, f"kling_{i:03d}.mp4").write_bytes(b"k" * 100)
        Path(tmp_path, f"scene_{i:03d}.trim.mp4").write_bytes(b"t" * 100)

    import artifact_integrity
    monkeypatch.setattr(artifact_integrity, "check_existing",
                        lambda *_a, **_kw: True)

    called: list[int] = []

    def fake_kling(scene_idx, scene, screenplay, temp_dir, force_fresh=False):
        called.append(scene_idx)
        Path(temp_dir, f"kling_{scene_idx:03d}.mp4").write_bytes(b"k" * 100)
        Path(temp_dir, f"scene_{scene_idx:03d}.trim.mp4").write_bytes(b"t")

    # 注: ここでは _kling_for_scene を mock しており、generate_kling_for_screenplay
    # はそれを scene 0..3 すべてに対して呼ぶ。実際の skip-on-exists は
    # _kling_for_scene 内部で起きるので、本テストは "_kling_for_scene 自身が呼ばれる
    # こと" を確認するレベル。実際の skip は別ファイル (test_kling_cache.py 等) で
    # check_existing 経由のテストが既に存在する。
    monkeypatch.setattr(scene_gen, "_kling_for_scene", fake_kling)

    scene_gen.generate_kling_for_screenplay(sp, str(tmp_path))
    # generate_kling_for_screenplay は per-scene 呼び出し。実際の skip は内部依存。
    # ここでは少なくとも 4 シーン全てが呼ばれることを確認 (= 上位 loop は全 scene を回す)
    assert sorted(called) == [0, 1, 2, 3]


def test_kling_for_scene_skips_when_raw_and_trim_valid(tmp_path, monkeypatch):
    """_kling_for_scene 自身のスキップロジック: kling raw + trim が両方 valid なら
    FAL を呼ばずに早期 return することを確認。"""
    import artifact_integrity
    import fal_video_client

    scene = {
        "background_prompt": "bg",
        "animation_prompt": "motion",
        "duration": 5.0,
    }
    sp = {"scenes": [scene]}

    Path(tmp_path, "bg_000.png").write_bytes(b"png" * 10)
    Path(tmp_path, "kling_000.mp4").write_bytes(b"k" * 100)
    Path(tmp_path, "scene_000.trim.mp4").write_bytes(b"t" * 100)

    monkeypatch.setattr(artifact_integrity, "check_existing",
                        lambda *_a, **_kw: True)
    monkeypatch.setattr(scene_gen, "_get_duration", lambda _p: 5.0)
    fal_called: list[int] = []
    monkeypatch.setattr(
        fal_video_client, "generate_video",
        lambda *a, **kw: fal_called.append(1),
    )

    scene_gen._kling_for_scene(0, scene, sp, str(tmp_path), force_fresh=False)
    assert fal_called == []  # FAL は呼ばれない (= skip 成立)


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
