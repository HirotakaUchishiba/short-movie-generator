"""clip_library.py の単体テスト。

設計 doc: docs/plannings/2026-05-10_compositional-architecture.md §3
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import clip_library
from clip_library import (
    ClipAnnotation,
    ClipEntry,
    ClipIdentity,
    ClipLifecycle,
    ClipProvenance,
    _annotation_score,
    _intent_compatible,
    iter_active_entries,
    iter_all_entries,
    load_entry,
    lookup_clip_pool,
    register_clip_entry,
    reset_intent_compat_cache,
    save_entry,
    select_variant,
)


@pytest.fixture
def isolated_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """テストごとに分離した CLIP_LIBRARY_DIR を使う。"""

    root = tmp_path / "clips"
    root.mkdir(parents=True)
    monkeypatch.setattr("config.CLIP_LIBRARY_DIR", str(root))
    monkeypatch.setattr("config.CLIP_POOL_TOP_K", 10)
    monkeypatch.setattr("config.CLIP_POOL_AUTO_APPROVE", False)
    return root


# ───────────── ClipIdentity ─────────────


class TestClipIdentity:
    def test_char_set_is_order_independent(self) -> None:
        a = ClipIdentity(("f1", "m1"), "office", "中立")
        b = ClipIdentity(("m1", "f1"), "office", "中立")
        assert a.char_set() == b.char_set()
        assert a.matches(b)
        assert b.matches(a)

    def test_matches_requires_all_dimensions(self) -> None:
        base = ClipIdentity(("f1",), "office", "中立", "medium-close")
        assert base.matches(
            ClipIdentity(("f1",), "office", "中立", "medium-close")
        )
        # camera_distance 違いは miss
        assert not base.matches(
            ClipIdentity(("f1",), "office", "中立", "wide")
        )
        # start_emotion 違いは miss
        assert not base.matches(ClipIdentity(("f1",), "office", "焦り"))
        # location 違いは miss
        assert not base.matches(ClipIdentity(("f1",), "park", "中立"))
        # character 違いは miss
        assert not base.matches(ClipIdentity(("m1",), "office", "中立"))

    def test_round_trip_dict(self) -> None:
        ident = ClipIdentity(("f1__office",), "home_office", "中立", "wide")
        d = ident.to_dict()
        restored = ClipIdentity.from_dict(d)
        assert restored.matches(ident)
        # camera_distance が無くても medium-close 既定で復元できる
        d2 = {
            "character_refs": ["f1__office"],
            "location_ref": "home_office",
            "start_emotion": "中立",
        }
        ident2 = ClipIdentity.from_dict(d2)
        assert ident2.camera_distance == "medium-close"


# ───────────── _annotation_score ─────────────


def _make_entry(
    intent: str | None,
    duration: int | None = 5,
    motion: str = "low",
    hit_count: int = 0,
) -> ClipEntry:
    return ClipEntry(
        id="x",
        identity=ClipIdentity(("f1",), "office", "中立"),
        annotation=ClipAnnotation(
            visual_intent_id=intent,
            duration_bucket=duration,
            motion_intensity=motion,
        ),
        provenance=ClipProvenance(),
        lifecycle=ClipLifecycle(status="active", hit_count=hit_count),
    )


class TestAnnotationScore:
    def test_exact_intent_match_scores_highest(self) -> None:
        e = _make_entry("talking_head_calm", 5, "low")
        score = _annotation_score(
            e,
            {
                "visual_intent_id": "talking_head_calm",
                "duration_bucket": 5,
                "motion_intensity": "low",
            },
        )
        # 3.0 (intent) + 1.0 (duration) + 0.5 (motion) + 0.3 (fresh)
        assert score == pytest.approx(4.8)

    def test_partial_match_lower_score(self) -> None:
        e = _make_entry("talking_head_calm", 10, "high")
        score = _annotation_score(
            e,
            {
                "visual_intent_id": "talking_head_calm",
                "duration_bucket": 5,
                "motion_intensity": "low",
            },
        )
        # 3.0 (intent) + 0 (duration mismatch) + 0 (motion mismatch) + 0.3
        assert score == pytest.approx(3.3)

    def test_no_intent_no_score(self) -> None:
        e = _make_entry(None, 5, "low")
        score = _annotation_score(
            e,
            {
                "visual_intent_id": "talking_head_calm",
                "duration_bucket": 5,
                "motion_intensity": "low",
            },
        )
        # entry の intent が None なので 0 + 1.0 + 0.5 + 0.3
        assert score == pytest.approx(1.8)

    def test_hit_count_demotes_score(self) -> None:
        fresh = _make_entry("talking_head_calm", 5, "low", hit_count=0)
        old = _make_entry("talking_head_calm", 5, "low", hit_count=100)
        s_fresh = _annotation_score(
            fresh, {"visual_intent_id": "talking_head_calm", "duration_bucket": 5}
        )
        s_old = _annotation_score(
            old, {"visual_intent_id": "talking_head_calm", "duration_bucket": 5}
        )
        assert s_fresh > s_old


# ───────────── _intent_compatible (= yaml 駆動) ─────────────


class TestIntentCompatible:
    def test_real_yaml_compat(self) -> None:
        # 本番 yaml の compatible_with が読み込まれている前提
        reset_intent_compat_cache()
        assert _intent_compatible(
            "talking_head_calm", "talking_head_listening"
        )
        # 双方向で見るので逆も True
        assert _intent_compatible(
            "talking_head_listening", "talking_head_calm"
        )
        # 同じ id は False (= 完全一致は別経路)
        assert not _intent_compatible(
            "talking_head_calm", "talking_head_calm"
        )
        # None / 空文字は False
        assert not _intent_compatible(None, "talking_head_calm")
        assert not _intent_compatible("", "talking_head_calm")
        # 無関係な id は False
        assert not _intent_compatible(
            "talking_head_calm", "reaction_surprise"
        )


# ───────────── persistence (load / save) ─────────────


class TestPersistence:
    def test_save_and_load_round_trip(self, isolated_root: Path) -> None:
        entry = ClipEntry(
            id="abc123",
            identity=ClipIdentity(("f1__office",), "home_office", "中立"),
            annotation=ClipAnnotation(
                visual_intent_id="talking_head_calm",
                duration_bucket=5,
                motion_intensity="low",
                generation_seed=42,
            ),
            provenance=ClipProvenance(
                imagen_prompt="test prompt",
                ref_image_shas={"f1__office": "abc"},
                generated_at="2026-05-10T00:00:00.000+00:00",
            ),
            lifecycle=ClipLifecycle(status="active"),
        )
        save_entry(entry)
        restored = load_entry("abc123")
        assert restored is not None
        assert restored.id == "abc123"
        assert restored.identity.matches(entry.identity)
        assert restored.annotation.visual_intent_id == "talking_head_calm"
        assert restored.lifecycle.status == "active"

    def test_load_nonexistent_returns_none(self, isolated_root: Path) -> None:
        assert load_entry("nope") is None

    def test_load_corrupt_meta_returns_none(self, isolated_root: Path) -> None:
        d = isolated_root / "broken"
        d.mkdir()
        (d / "meta.json").write_text("{ not valid json")
        assert load_entry("broken") is None


# ───────────── register_clip_entry ─────────────


class TestRegister:
    def test_register_creates_entry_and_copies_files(
        self, isolated_root: Path, tmp_path: Path
    ) -> None:
        bg = tmp_path / "src.png"
        bg.write_bytes(b"\x89PNG\r\n\x1a\n")
        kling = tmp_path / "src.mp4"
        kling.write_bytes(b"fake mp4")

        entry = register_clip_entry(
            identity=ClipIdentity(("f1",), "office", "中立"),
            annotation=ClipAnnotation(
                visual_intent_id="talking_head_calm", duration_bucket=5
            ),
            provenance=ClipProvenance(imagen_prompt="x"),
            bg_src=bg,
            kling_src=kling,
        )
        assert entry.lifecycle.status == "pending_review"
        assert entry.bg_path().exists()
        assert entry.kling_path().exists()
        # meta.json も書かれている
        assert (entry.entry_dir() / "meta.json").exists()
        # provenance.generated_at が register 時点で埋まる
        assert entry.provenance.generated_at != ""

    def test_auto_approve_sets_active(
        self, isolated_root: Path, tmp_path: Path
    ) -> None:
        entry = register_clip_entry(
            identity=ClipIdentity(("f1",), "office", "中立"),
            annotation=ClipAnnotation(),
            provenance=ClipProvenance(),
            bg_src=None,
            kling_src=None,
            auto_approve=True,
        )
        assert entry.lifecycle.status == "active"
        assert entry.lifecycle.approved_at is not None


# ───────────── lookup_clip_pool ─────────────


class TestLookup:
    def test_returns_empty_when_no_entries(self, isolated_root: Path) -> None:
        scene = {
            "character_refs": ["f1"],
            "location_ref": "office",
            "start_emotion": "中立",
        }
        assert lookup_clip_pool(scene) == []

    def test_filters_by_identity(
        self, isolated_root: Path, tmp_path: Path
    ) -> None:
        # 2 件 register: identity が違う
        register_clip_entry(
            identity=ClipIdentity(("f1",), "office", "中立"),
            annotation=ClipAnnotation(visual_intent_id="talking_head_calm"),
            provenance=ClipProvenance(),
            bg_src=None,
            kling_src=None,
            auto_approve=True,
        )
        register_clip_entry(
            identity=ClipIdentity(("m1",), "office", "中立"),
            annotation=ClipAnnotation(visual_intent_id="talking_head_calm"),
            provenance=ClipProvenance(),
            bg_src=None,
            kling_src=None,
            auto_approve=True,
        )
        # f1 で問い合わせ → 1 件
        scene = {
            "character_refs": ["f1"],
            "location_ref": "office",
            "start_emotion": "中立",
        }
        result = lookup_clip_pool(scene)
        assert len(result) == 1
        assert result[0].identity.character_refs == ("f1",)

    def test_excludes_pending_review(
        self, isolated_root: Path, tmp_path: Path
    ) -> None:
        register_clip_entry(
            identity=ClipIdentity(("f1",), "office", "中立"),
            annotation=ClipAnnotation(visual_intent_id="talking_head_calm"),
            provenance=ClipProvenance(),
            bg_src=None,
            kling_src=None,
            auto_approve=False,  # pending_review
        )
        scene = {
            "character_refs": ["f1"],
            "location_ref": "office",
            "start_emotion": "中立",
        }
        # active のみ返るので空
        assert lookup_clip_pool(scene) == []
        # iter_all_entries は pending も含む
        assert len(list(iter_all_entries())) == 1
        assert len(list(iter_active_entries())) == 0

    def test_ranks_by_annotation_score(
        self, isolated_root: Path, tmp_path: Path
    ) -> None:
        # 同 identity で intent の異なる 3 件
        for intent in ("reaction_surprise", "talking_head_calm", "talking_head_listening"):
            register_clip_entry(
                identity=ClipIdentity(("f1",), "office", "中立"),
                annotation=ClipAnnotation(
                    visual_intent_id=intent, duration_bucket=5
                ),
                provenance=ClipProvenance(),
                bg_src=None,
                kling_src=None,
                auto_approve=True,
            )

        # talking_head_calm を要求 → 完全一致が 1 位、互換 (listening) が 2 位、
        # 無関係 (reaction_surprise) が最下位
        scene = {
            "character_refs": ["f1"],
            "location_ref": "office",
            "start_emotion": "中立",
            "visual_intent_id": "talking_head_calm",
            "duration_bucket": 5,
        }
        reset_intent_compat_cache()
        result = lookup_clip_pool(scene)
        intents = [e.annotation.visual_intent_id for e in result]
        assert intents[0] == "talking_head_calm"
        assert intents[1] == "talking_head_listening"
        assert intents[2] == "reaction_surprise"

    def test_top_k_limits_results(
        self, isolated_root: Path, tmp_path: Path
    ) -> None:
        for _ in range(15):
            register_clip_entry(
                identity=ClipIdentity(("f1",), "office", "中立"),
                annotation=ClipAnnotation(visual_intent_id="talking_head_calm"),
                provenance=ClipProvenance(),
                bg_src=None,
                kling_src=None,
                auto_approve=True,
            )
        scene = {
            "character_refs": ["f1"],
            "location_ref": "office",
            "start_emotion": "中立",
        }
        assert len(lookup_clip_pool(scene, top_k=5)) == 5
        assert len(lookup_clip_pool(scene, top_k=20)) == 15


# ───────────── select_variant ─────────────


class TestSelectVariant:
    def _make_pool(self, n: int) -> list[ClipEntry]:
        return [
            ClipEntry(
                id=f"id{i:02d}",
                identity=ClipIdentity(("f1",), "office", "中立"),
                annotation=ClipAnnotation(),
                provenance=ClipProvenance(),
                lifecycle=ClipLifecycle(status="active"),
            )
            for i in range(n)
        ]

    def test_deterministic_for_same_ts_scene_idx(self) -> None:
        pool = self._make_pool(10)
        a = select_variant(pool, "20260510_120000", 3)
        b = select_variant(pool, "20260510_120000", 3)
        assert a.id == b.id

    def test_different_scene_idx_gives_different_variant(self) -> None:
        pool = self._make_pool(10)
        ids_per_scene = {
            i: select_variant(pool, "20260510_120000", i).id
            for i in range(10)
        }
        # 10 scene の選択結果は (= 完全等分布ではないが) 少なくとも 5 種以上の id に分散する
        assert len(set(ids_per_scene.values())) >= 5

    def test_different_ts_gives_different_distribution(self) -> None:
        """同 scene_idx でも複数の ts を試すと分散する (= 1 つに張り付かない)。

        個別 ts ペアでの hash 衝突は確率的に起こるため、サンプルを増やして
        「分布が 1 点に張り付かない」ことを確認する。
        """
        pool = self._make_pool(10)
        ts_samples = [
            "20260101_000000",
            "20260201_120000",
            "20260301_233000",
            "20260410_080000",
            "20260510_120000",
            "20260613_154500",
            "20260720_011500",
            "20260801_193000",
        ]
        chosen_ids = {select_variant(pool, ts, 0).id for ts in ts_samples}
        # 8 ts 中 少なくとも 4 種類以上の variant が選ばれることを期待
        # (= 同 ts ペアの個別衝突は許容、全体としての分散性をチェック)
        assert len(chosen_ids) >= 4

    def test_empty_pool_raises(self) -> None:
        with pytest.raises(ValueError):
            select_variant([], "ts", 0)


# ───────────── lifecycle 操作 ─────────────


class TestLifecycle:
    def test_approve_promotes_to_active(self, isolated_root: Path) -> None:
        entry = register_clip_entry(
            identity=ClipIdentity(("f1",), "office", "中立"),
            annotation=ClipAnnotation(),
            provenance=ClipProvenance(),
            bg_src=None,
            kling_src=None,
            auto_approve=False,
        )
        assert entry.lifecycle.status == "pending_review"
        assert clip_library.approve_entry(entry.id)
        restored = load_entry(entry.id)
        assert restored is not None
        assert restored.lifecycle.status == "active"
        assert restored.lifecycle.approved_at is not None

    def test_blacklist_excludes_from_lookup(self, isolated_root: Path) -> None:
        entry = register_clip_entry(
            identity=ClipIdentity(("f1",), "office", "中立"),
            annotation=ClipAnnotation(),
            provenance=ClipProvenance(),
            bg_src=None,
            kling_src=None,
            auto_approve=True,
        )
        scene = {
            "character_refs": ["f1"],
            "location_ref": "office",
            "start_emotion": "中立",
        }
        assert len(lookup_clip_pool(scene)) == 1
        assert clip_library.blacklist_entry(entry.id, "test reason")
        assert lookup_clip_pool(scene) == []

    def test_touch_increments_hit_count(self, isolated_root: Path) -> None:
        entry = register_clip_entry(
            identity=ClipIdentity(("f1",), "office", "中立"),
            annotation=ClipAnnotation(),
            provenance=ClipProvenance(),
            bg_src=None,
            kling_src=None,
            auto_approve=True,
        )
        assert clip_library.touch_entry(entry.id)
        assert clip_library.touch_entry(entry.id)
        restored = load_entry(entry.id)
        assert restored is not None
        assert restored.lifecycle.hit_count == 2
        assert restored.lifecycle.last_used_at is not None


# ───────────── E2E (= Phase 1 的な hit シナリオ) ─────────────


class TestE2EWarmCacheFlow:
    """異なる screenplay でも同 identity なら同じ pool を参照することの確認。"""

    def test_two_screenplays_share_same_pool(
        self, isolated_root: Path, tmp_path: Path
    ) -> None:
        # screenplay A の scene
        scene_a = {
            "character_refs": ["f1__office"],
            "location_ref": "home_office",
            "start_emotion": "中立",
            "camera_distance": "medium-close",
            "visual_intent_id": "talking_head_calm",
            "duration_bucket": 5,
        }
        # screenplay B の scene: line text / annotation の motion_intensity 違い等を想定
        scene_b = {
            "character_refs": ["f1__office"],
            "location_ref": "home_office",
            "start_emotion": "中立",
            "camera_distance": "medium-close",
            "visual_intent_id": "talking_head_calm",
            "duration_bucket": 10,  # ← duration 違い
        }

        # cold path として screenplay A から register
        identity = ClipIdentity(
            character_refs=("f1__office",),
            location_ref="home_office",
            start_emotion="中立",
            camera_distance="medium-close",
        )
        register_clip_entry(
            identity=identity,
            annotation=ClipAnnotation(
                visual_intent_id="talking_head_calm", duration_bucket=5
            ),
            provenance=ClipProvenance(),
            bg_src=None,
            kling_src=None,
            auto_approve=True,
        )

        # 両 screenplay の lookup が同 entry を hit する (= identity 完全一致)
        pool_a = lookup_clip_pool(scene_a)
        pool_b = lookup_clip_pool(scene_b)
        assert len(pool_a) == 1
        assert len(pool_b) == 1
        assert pool_a[0].id == pool_b[0].id

    def test_camera_distance_mismatch_blocks_hit(
        self, isolated_root: Path
    ) -> None:
        register_clip_entry(
            identity=ClipIdentity(
                ("f1",), "office", "中立", camera_distance="medium-close"
            ),
            annotation=ClipAnnotation(),
            provenance=ClipProvenance(),
            bg_src=None,
            kling_src=None,
            auto_approve=True,
        )
        scene = {
            "character_refs": ["f1"],
            "location_ref": "office",
            "start_emotion": "中立",
            "camera_distance": "wide",  # ← mismatch
        }
        assert lookup_clip_pool(scene) == []

    def test_new_schema_with_identity_dict_works(
        self, isolated_root: Path
    ) -> None:
        register_clip_entry(
            identity=ClipIdentity(("f1",), "office", "中立"),
            annotation=ClipAnnotation(visual_intent_id="talking_head_calm"),
            provenance=ClipProvenance(),
            bg_src=None,
            kling_src=None,
            auto_approve=True,
        )
        # 新スキーマ (= identity を入れ子) でも lookup できる
        scene = {
            "identity": {
                "character_refs": ["f1"],
                "location_ref": "office",
                "start_emotion": "中立",
            },
            "annotation": {"visual_intent_id": "talking_head_calm"},
        }
        result = lookup_clip_pool(scene)
        assert len(result) == 1
