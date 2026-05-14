"""clip_library を scene_gen / staged_pipeline に wire した結果の単体テスト。

mismatch audit doc 1-1 (= clip_library が production 経路から完全に dead) の
解消を検証する。

実 AI 呼び出しは行わず、satisfy / register 関数の挙動と staged_pipeline
からの flag 経由の有効化を確認する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import clip_library


def _scene_with_identity(extra: dict | None = None) -> dict:
    base = {
        "identity": {
            "character_refs": ["f1__office"],
            "location_ref": "home_office",
            "start_emotion": "中立",
            "camera_distance": "medium-close",
        },
        "background_prompt": "x",
        "lines": [{"text": "x", "start": 0, "end": 1}],
    }
    if extra:
        base.update(extra)
    return base


def _make_dummy_files(entry_dir: Path) -> tuple[Path, Path]:
    bg = entry_dir / "bg.png"
    kl = entry_dir / "kling_clean.mp4"
    bg.write_bytes(b"\x89PNG fake")
    kl.write_bytes(b"\x00fakekling")
    return bg, kl


@pytest.fixture
def isolated_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "clips"
    root.mkdir()
    monkeypatch.setattr("config.CLIP_LIBRARY_DIR", str(root))
    monkeypatch.setattr("config.CLIP_LIBRARY_ENABLED", True)
    monkeypatch.setattr("config.CLIP_POOL_AUTO_APPROVE", True)
    return root


@pytest.fixture
def ts_path(tmp_path: Path) -> Path:
    p = tmp_path / "20260510_120000"
    p.mkdir()
    return p


# ───────────── _scene_has_identity ─────────────


class TestSceneHasIdentity:
    def test_inline_identity_dict(self) -> None:
        scene = {
            "identity": {
                "character_refs": ["f1"],
                "location_ref": "office",
                "start_emotion": "中立",
            }
        }
        assert clip_library._scene_has_identity(scene)

    def test_flat_schema_returns_false(self) -> None:
        # flat schema (= 旧スキーマ) は nested 不在として扱う (= 回帰防止)
        scene = {
            "character_refs": ["f1"],
            "location_ref": "office",
            "start_emotion": "中立",
        }
        assert not clip_library._scene_has_identity(scene)

    def test_missing_identity_returns_false(self) -> None:
        scene = {
            "identity": {
                "character_refs": ["f1"],
                "location_ref": "office",
                # start_emotion missing
            },
        }
        assert not clip_library._scene_has_identity(scene)

    def test_flat_scene_to_identity_raises(self) -> None:
        # flat schema を _scene_to_identity に渡すと ValueError (= 回帰防止)
        scene = {
            "character_refs": ["f1"],
            "location_ref": "office",
            "start_emotion": "中立",
        }
        with pytest.raises(ValueError, match="identity"):
            clip_library._scene_to_identity(scene)


# ───────────── satisfy_scenes_from_library ─────────────


class TestSatisfy:
    def test_disabled_returns_empty(
        self, isolated_root: Path, ts_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("config.CLIP_LIBRARY_ENABLED", False)
        sp = {"scenes": [_scene_with_identity()]}
        assert clip_library.satisfy_scenes_from_library(sp, str(ts_path)) == {}

    def test_no_identity_scene_skipped(
        self, isolated_root: Path, ts_path: Path,
    ) -> None:
        sp = {
            "scenes": [
                {
                    "background_prompt": "x",
                    "lines": [],
                    # identity 系フィールドなし
                },
            ],
        }
        assert clip_library.satisfy_scenes_from_library(sp, str(ts_path)) == {}

    def test_hit_copies_bg_and_kling(
        self, isolated_root: Path, ts_path: Path, tmp_path: Path,
    ) -> None:
        # まず library に entry を register
        entry = clip_library.register_clip_entry(
            identity=clip_library.ClipIdentity(
                ("f1__office",), "home_office", "中立", "medium-close"
            ),
            annotation=clip_library.ClipAnnotation(
                visual_intent_id="talking_head_calm"
            ),
            provenance=clip_library.ClipProvenance(),
            bg_src=None,
            kling_src=None,
            auto_approve=True,
        )
        # entry の bg/kling ファイルを手動で作成 (= cold path 完了相当)
        _make_dummy_files(entry.entry_dir())

        sp = {"scenes": [_scene_with_identity()]}
        satisfied = clip_library.satisfy_scenes_from_library(sp, str(ts_path))
        assert satisfied == {0: entry.id}

        bg_dst = ts_path / "bg_000.png"
        kl_dst = ts_path / "kling_000.mp4"
        assert bg_dst.exists()
        assert kl_dst.exists()
        assert bg_dst.read_bytes() == b"\x89PNG fake"
        assert kl_dst.read_bytes() == b"\x00fakekling"

    def test_miss_returns_empty(
        self, isolated_root: Path, ts_path: Path,
    ) -> None:
        # library 空のまま lookup → miss
        sp = {"scenes": [_scene_with_identity()]}
        assert clip_library.satisfy_scenes_from_library(sp, str(ts_path)) == {}
        # bg / kling は temp に作られない
        assert not (ts_path / "bg_000.png").exists()
        assert not (ts_path / "kling_000.mp4").exists()

    def test_override_skips_lookup(
        self, isolated_root: Path, ts_path: Path,
    ) -> None:
        # library に entry を入れても、override 設定 scene は hit させない
        entry = clip_library.register_clip_entry(
            identity=clip_library.ClipIdentity(
                ("f1__office",), "home_office", "中立"
            ),
            annotation=clip_library.ClipAnnotation(),
            provenance=clip_library.ClipProvenance(),
            bg_src=None,
            kling_src=None,
            auto_approve=True,
        )
        _make_dummy_files(entry.entry_dir())

        scene = _scene_with_identity(
            {"_override_animation_prompt": "subject teleports"}
        )
        sp = {"scenes": [scene]}
        assert clip_library.satisfy_scenes_from_library(sp, str(ts_path)) == {}

    def test_entry_files_missing_skips(
        self, isolated_root: Path, ts_path: Path,
    ) -> None:
        # entry を register したが bg/kling ファイル未作成 → skip
        clip_library.register_clip_entry(
            identity=clip_library.ClipIdentity(
                ("f1__office",), "home_office", "中立"
            ),
            annotation=clip_library.ClipAnnotation(),
            provenance=clip_library.ClipProvenance(),
            bg_src=None,
            kling_src=None,
            auto_approve=True,
        )
        sp = {"scenes": [_scene_with_identity()]}
        assert clip_library.satisfy_scenes_from_library(sp, str(ts_path)) == {}


# ───────────── register_cold_path_clips ─────────────


class TestRegisterColdPath:
    def test_disabled_returns_empty(
        self, isolated_root: Path, ts_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("config.CLIP_LIBRARY_ENABLED", False)
        sp = {"scenes": [_scene_with_identity()]}
        # 偽の bg/kling を temp に置く
        (ts_path / "bg_000.png").write_bytes(b"x")
        (ts_path / "kling_000.mp4").write_bytes(b"y")
        assert clip_library.register_cold_path_clips(sp, str(ts_path)) == {}

    def test_satisfied_scenes_skipped(
        self, isolated_root: Path, ts_path: Path,
    ) -> None:
        sp = {"scenes": [_scene_with_identity()]}
        (ts_path / "bg_000.png").write_bytes(b"x")
        (ts_path / "kling_000.mp4").write_bytes(b"y")
        # satisfied で「すでに hit したよ」マークすると register 対象外
        result = clip_library.register_cold_path_clips(
            sp, str(ts_path), satisfied={0: "existing_entry"}
        )
        assert result == {}

    def test_cold_path_scene_registered(
        self, isolated_root: Path, ts_path: Path,
    ) -> None:
        sp = {"scenes": [_scene_with_identity()]}
        (ts_path / "bg_000.png").write_bytes(b"\x89PNG dummy")
        (ts_path / "kling_000.mp4").write_bytes(b"\x00 dummy kling")
        result = clip_library.register_cold_path_clips(sp, str(ts_path))
        assert len(result) == 1
        new_id = result[0]
        # entry が library に保存されているか
        entry = clip_library.load_entry(new_id)
        assert entry is not None
        assert entry.identity.location_ref == "home_office"
        assert entry.bg_path().exists()
        assert entry.kling_path().exists()

    def test_no_identity_scene_skipped(
        self, isolated_root: Path, ts_path: Path,
    ) -> None:
        sp = {
            "scenes": [
                {"background_prompt": "x", "lines": []}
            ],
        }
        (ts_path / "bg_000.png").write_bytes(b"x")
        (ts_path / "kling_000.mp4").write_bytes(b"y")
        assert clip_library.register_cold_path_clips(sp, str(ts_path)) == {}

    def test_missing_files_skipped(
        self, isolated_root: Path, ts_path: Path,
    ) -> None:
        sp = {"scenes": [_scene_with_identity()]}
        # bg だけ作って kling 無し
        (ts_path / "bg_000.png").write_bytes(b"x")
        result = clip_library.register_cold_path_clips(sp, str(ts_path))
        assert result == {}

    def test_override_scene_skipped(
        self, isolated_root: Path, ts_path: Path,
    ) -> None:
        scene = _scene_with_identity(
            {"_override_background_prompt": "novel intent"}
        )
        sp = {"scenes": [scene]}
        (ts_path / "bg_000.png").write_bytes(b"x")
        (ts_path / "kling_000.mp4").write_bytes(b"y")
        assert clip_library.register_cold_path_clips(sp, str(ts_path)) == {}


# ───────────── e2e: satisfy → cold path → register の循環 ─────────────


class TestE2EWireCycle:
    def test_full_cycle_warm_after_register(
        self, isolated_root: Path, ts_path: Path, tmp_path: Path,
    ) -> None:
        """1 回目: miss → cold path で register → 2 回目 (= 別 ts) で hit する。"""

        sp1 = {"scenes": [_scene_with_identity()]}

        # ─── 1 回目: satisfy 失敗 (= library 空) ───
        first_satisfied = clip_library.satisfy_scenes_from_library(
            sp1, str(ts_path)
        )
        assert first_satisfied == {}

        # cold path 模擬: bg/kling を temp に置く
        (ts_path / "bg_000.png").write_bytes(b"\x89PNG cold")
        (ts_path / "kling_000.mp4").write_bytes(b"\x00cold kling")

        # register
        registered = clip_library.register_cold_path_clips(
            sp1, str(ts_path), satisfied=first_satisfied,
        )
        assert len(registered) == 1

        # ─── 2 回目 (= 別 project) で identity 一致なら hit ───
        ts2 = tmp_path / "20260510_999999"
        ts2.mkdir()
        sp2 = {"scenes": [_scene_with_identity()]}
        second_satisfied = clip_library.satisfy_scenes_from_library(
            sp2, str(ts2)
        )
        assert len(second_satisfied) == 1
        # bg + kling が ts2 にコピーされている
        assert (ts2 / "bg_000.png").exists()
        assert (ts2 / "kling_000.mp4").exists()
        # 元の cold path で書いた中身と一致
        assert (ts2 / "bg_000.png").read_bytes() == b"\x89PNG cold"
        assert (ts2 / "kling_000.mp4").read_bytes() == b"\x00cold kling"
