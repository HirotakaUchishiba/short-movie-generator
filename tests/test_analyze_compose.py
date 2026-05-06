"""analyze.compose の単体テスト (抽象台本 → 完全 screenplay)。"""
import pytest

from analyze import character_meta as cmeta_mod
from analyze import location as loc_mod
from analyze.compose import compose_screenplay


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    chars = tmp_path / "characters"
    locs = tmp_path / "locations"
    chars.mkdir()
    locs.mkdir()
    monkeypatch.setattr(cmeta_mod, "CHARACTERS_DIR", chars)
    monkeypatch.setattr(loc_mod, "LOCATIONS_DIR", locs)
    return {"chars": chars, "locs": locs}


def _seed(isolated_dirs):
    """1 ロケ + 2 キャラ (base ID 単位) を作る。"""
    loc_mod.save_location(loc_mod.Location(
        id="home_office",
        decor="北欧風オフィス",
        lighting="自然光",
        color_palette="白基調",
        props="MacBook",
        camera_distance="medium-close",
    ))
    cmeta_mod.save_character_meta(cmeta_mod.CharacterMeta(
        id="f1",
        voice_overrides={"voice_id": "voice_p", "stability": 0.4},
    ))
    cmeta_mod.save_character_meta(cmeta_mod.CharacterMeta(
        id="m1",
        voice_overrides={"voice_id": "voice_b"},
    ))


def _abstract_minimal() -> dict:
    return {
        "caption": "test caption",
        "featured_characters": ["f1__office"],
        "scenes": [
            {
                "duration": 5.0,
                "location_ref": "home_office",
                "lines": [
                    {"text": "やばい", "start": 0, "end": 2,
                     "emotion": "焦り", "delivery": "早口"},
                    {"text": "セーフ", "start": 2.5, "end": 4,
                     "emotion": "安堵", "delivery": "ほっと"},
                ],
            },
        ],
    }


def test_compose_basic_round_trip(isolated_dirs):
    _seed(isolated_dirs)
    sp = compose_screenplay(_abstract_minimal())
    assert sp["caption"] == "test caption"
    assert "location_continuity" not in sp
    assert "wardrobe_continuity" not in sp
    assert len(sp["scenes"]) == 1
    scene = sp["scenes"][0]
    assert scene["duration"] == 5.0
    assert scene["character_refs"] == ["f1__office"]
    assert scene["characters"] == [{"name": "f1__office"}]
    assert scene["location_ref"] == "home_office"
    assert scene["lipsync"] is True
    # SSOT 一本化: compose 出力はカメラ距離 + 人物表現のみ。ロケ詳細は
    # scene_gen.`_build_background_prompt` で `locations/<id>.json` から注入される
    assert "medium close-up shot" in scene["background_prompt"]
    assert "the depicted subject" in scene["background_prompt"]
    assert "wearing" not in scene["background_prompt"]
    assert "f1__office" not in scene["background_prompt"]
    # decor は compose 側では入らない (= 二重注入回避)
    assert "Scandinavian" not in scene["background_prompt"]


def test_compose_scene_animation_style_default(isolated_dirs):
    """シーンに animation_style が無ければ standard で合成される。"""
    _seed(isolated_dirs)
    sp = compose_screenplay(_abstract_minimal())
    anim = sp["scenes"][0]["animation_prompt"]
    assert "natural hand gestures" in anim


def test_compose_scene_animation_style_expressive(isolated_dirs):
    _seed(isolated_dirs)
    abstract = _abstract_minimal()
    abstract["scenes"][0]["animation_style"] = "expressive"
    sp = compose_screenplay(abstract)
    assert "energetic" in sp["scenes"][0]["animation_prompt"]


def test_compose_scene_animation_style_subtle(isolated_dirs):
    _seed(isolated_dirs)
    abstract = _abstract_minimal()
    abstract["scenes"][0]["animation_style"] = "subtle"
    sp = compose_screenplay(abstract)
    assert "minimal hand movement" in sp["scenes"][0]["animation_prompt"]


def test_compose_voice_overrides_injected(isolated_dirs):
    _seed(isolated_dirs)
    sp = compose_screenplay(_abstract_minimal())
    line0 = sp["scenes"][0]["lines"][0]
    assert "voice_overrides" in line0
    assert line0["voice_overrides"]["stability"] == 0.4


def test_compose_per_scene_location(isolated_dirs):
    _seed(isolated_dirs)
    loc_mod.save_location(loc_mod.Location(
        id="park", decor="公園", camera_distance="wide",
    ))
    abstract = _abstract_minimal()
    abstract["scenes"][0]["location_ref"] = "park"
    sp = compose_screenplay(abstract)
    assert sp["scenes"][0]["location_ref"] == "park"
    assert "wide shot" in sp["scenes"][0]["background_prompt"]


def test_compose_character_selection_subsets_speaking_characters(isolated_dirs):
    _seed(isolated_dirs)
    abstract = {
        "caption": "x",
        "featured_characters": ["f1__office", "m1__suit"],
        "scenes": [{
            "duration": 5,
            "character_selection": ["m1__suit"],
            "lines": [
                {"text": "a", "start": 0, "end": 1, "speaker": "m1__suit"},
                {"text": "b", "start": 1, "end": 2, "speaker": "m1__suit"},
            ],
        }],
    }
    sp = compose_screenplay(abstract)
    refs = {c["name"] for c in sp["scenes"][0]["characters"]}
    assert refs == {"m1__suit"}


def test_compose_voice_resolution_per_speaker(isolated_dirs):
    _seed(isolated_dirs)
    abstract = {
        "caption": "",
        "featured_characters": ["f1__office", "m1__suit"],
        "scenes": [{
            "duration": 5,
            "lines": [
                {"text": "a", "start": 0, "end": 1, "speaker": "f1__office"},
                {"text": "b", "start": 1, "end": 2, "speaker": "m1__suit"},
            ],
        }],
    }
    sp = compose_screenplay(abstract)
    lines = sp["scenes"][0]["lines"]
    assert lines[0]["voice_overrides"]["voice_id"] == "voice_p"
    assert lines[1]["voice_overrides"]["voice_id"] == "voice_b"


def test_compose_speaker_to_ref_mapping(isolated_dirs):
    _seed(isolated_dirs)
    abstract = {
        "caption": "",
        "featured_characters": ["f1__office", "m1__suit"],
        "scenes": [{
            "duration": 5,
            "lines": [
                {"text": "a", "start": 0, "end": 1, "speaker": "speaker_1"},
                {"text": "b", "start": 1, "end": 2, "speaker": "speaker_2"},
            ],
        }],
        "speaker_to_ref": {
            "speaker_1": "f1__office",
            "speaker_2": "m1__suit",
        },
    }
    sp = compose_screenplay(abstract)
    lines = sp["scenes"][0]["lines"]
    assert lines[0]["speaker"] == "f1__office"
    assert lines[1]["speaker"] == "m1__suit"
    assert lines[0]["voice_overrides"]["voice_id"] == "voice_p"
    assert lines[1]["voice_overrides"]["voice_id"] == "voice_b"


def test_compose_passes_strict_validator(isolated_dirs):
    _seed(isolated_dirs)
    from screenplay_validator import validate_screenplay
    sp = compose_screenplay(_abstract_minimal())
    validate_screenplay(sp, strict=True)


def test_compose_character_selection_explicit_subset(isolated_dirs):
    _seed(isolated_dirs)
    abstract = _abstract_minimal()
    abstract["featured_characters"] = [
        "f1__office", "m1__suit",
    ]
    abstract["scenes"][0]["character_selection"] = ["f1__office"]
    sp = compose_screenplay(abstract)
    chars = sp["scenes"][0]["characters"]
    refs = sp["scenes"][0]["character_refs"]
    assert [c["name"] for c in chars] == ["f1__office"]
    assert refs == ["f1__office"]


def test_compose_character_selection_empty_means_no_people(isolated_dirs):
    _seed(isolated_dirs)
    abstract = _abstract_minimal()
    abstract["scenes"][0]["character_selection"] = []
    sp = compose_screenplay(abstract)
    scene = sp["scenes"][0]
    assert scene["characters"] == []
    assert scene["character_refs"] == []
    assert "no people" in scene["background_prompt"]
    assert "scenery only" in scene["background_prompt"]


def test_compose_character_selection_missing_uses_featured(isolated_dirs):
    _seed(isolated_dirs)
    abstract = _abstract_minimal()
    sp = compose_screenplay(abstract)
    assert [c["name"] for c in sp["scenes"][0]["characters"]] == [
        "f1__office",
    ]


def test_compose_speaker_to_ref_drives_scene_characters(isolated_dirs):
    """speaker_to_ref を 1 か所書くだけで各シーンの character_selection が
    自動推論される (= multi-speaker 動画のメイン UX)。
    """
    _seed(isolated_dirs)
    abstract = {
        "caption": "x",
        "featured_characters": ["f1__office", "m1__suit"],
        "speaker_to_ref": {
            "speaker_1": "f1__office",
            "speaker_2": "m1__suit",
        },
        "scenes": [
            # シーン 0: speaker_1 のみ → f1__office だけ
            {
                "duration": 3,
                "lines": [
                    {"text": "a", "start": 0, "end": 1, "speaker": "speaker_1"},
                ],
            },
            # シーン 1: speaker_1 と speaker_2 が両方発言 → 2 人とも
            {
                "duration": 4,
                "lines": [
                    {"text": "b", "start": 0, "end": 1, "speaker": "speaker_1"},
                    {"text": "c", "start": 1, "end": 2, "speaker": "speaker_2"},
                ],
            },
            # シーン 2: speaker_2 のみ → m1__suit だけ
            {
                "duration": 3,
                "lines": [
                    {"text": "d", "start": 0, "end": 1, "speaker": "speaker_2"},
                ],
            },
        ],
    }
    sp = compose_screenplay(abstract)
    assert [c["name"] for c in sp["scenes"][0]["characters"]] == [
        "f1__office",
    ]
    assert sorted(c["name"] for c in sp["scenes"][1]["characters"]) == [
        "f1__office", "m1__suit",
    ]
    assert [c["name"] for c in sp["scenes"][2]["characters"]] == [
        "m1__suit",
    ]


def test_compose_explicit_character_selection_overrides_speakers(isolated_dirs):
    """明示 character_selection は speaker からの推論より優先される。"""
    _seed(isolated_dirs)
    abstract = {
        "caption": "x",
        "featured_characters": ["f1__office", "m1__suit"],
        "speaker_to_ref": {
            "speaker_1": "f1__office",
            "speaker_2": "m1__suit",
        },
        "scenes": [{
            "duration": 3,
            "character_selection": [],  # 0 人 = 背景のみ (= 明示 override)
            "lines": [
                {"text": "a", "start": 0, "end": 1, "speaker": "speaker_1"},
            ],
        }],
    }
    sp = compose_screenplay(abstract)
    assert sp["scenes"][0]["characters"] == []


def test_compose_speaker_directly_as_ref_also_drives_selection(isolated_dirs):
    """line.speaker が直接 ref (= 個別 override 済み) でも自動推論が動く。"""
    _seed(isolated_dirs)
    abstract = {
        "caption": "x",
        "featured_characters": ["f1__office", "m1__suit"],
        "scenes": [{
            "duration": 3,
            "lines": [
                {"text": "a", "start": 0, "end": 1,
                 "speaker": "m1__suit"},
            ],
        }],
    }
    sp = compose_screenplay(abstract)
    assert [c["name"] for c in sp["scenes"][0]["characters"]] == [
        "m1__suit",
    ]


def test_compose_invalid_camera_distance_falls_back_to_medium(isolated_dirs, caplog):
    """未知の camera_distance は warning ログ + medium にフォールバック。"""
    import logging
    _seed(isolated_dirs)
    abstract = _abstract_minimal()
    abstract["scenes"][0]["camera_distance"] = "extreme-zoom-out"
    with caplog.at_level(logging.WARNING, logger="analyze.compose"):
        sp = compose_screenplay(abstract)
    assert "extreme-zoom-out" in caplog.text
    assert "medium shot" in sp["scenes"][0]["background_prompt"]


# ─── diagnose_abstract (UI 警告用の不整合検出) ───────────────────────


def test_diagnose_unmapped_speakers(isolated_dirs):
    _seed(isolated_dirs)
    from analyze.compose import diagnose_abstract
    abstract = {
        "caption": "x",
        "featured_characters": ["f1"],
        "speaker_to_ref": {"speaker_1": "f1"},
        "scenes": [{
            "duration": 3,
            "lines": [
                {"text": "a", "start": 0, "end": 1, "speaker": "speaker_1"},
                {"text": "b", "start": 1, "end": 2, "speaker": "speaker_2"},
                {"text": "c", "start": 2, "end": 3, "speaker": "speaker_3"},
            ],
        }],
    }
    d = diagnose_abstract(abstract)
    assert d["unmapped_speakers"] == ["speaker_2", "speaker_3"]


def test_diagnose_scenes_without_location(isolated_dirs):
    _seed(isolated_dirs)
    from analyze.compose import diagnose_abstract
    abstract = {
        "caption": "x",
        "featured_characters": ["f1"],
        "scenes": [
            {"duration": 3, "location_ref": "home_office", "lines": []},
            {"duration": 3, "lines": []},   # location 未設定
            {"duration": 3, "location_ref": "", "lines": []},  # 空文字も未設定扱い
        ],
    }
    d = diagnose_abstract(abstract)
    assert d["scenes_without_location"] == [1, 2]


def test_diagnose_scenes_without_characters_explicit_empty(isolated_dirs):
    _seed(isolated_dirs)
    from analyze.compose import diagnose_abstract
    abstract = {
        "caption": "x",
        "featured_characters": ["f1"],
        "scenes": [
            {"duration": 3, "character_selection": [], "lines": []},
            {"duration": 3, "character_selection": ["f1"], "lines": []},
        ],
    }
    d = diagnose_abstract(abstract)
    assert d["scenes_without_characters"] == [0]


def test_diagnose_invalid_camera_distance(isolated_dirs):
    _seed(isolated_dirs)
    from analyze.compose import diagnose_abstract
    abstract = {
        "caption": "x",
        "featured_characters": ["f1"],
        "scenes": [
            {"duration": 3, "camera_distance": "wide", "lines": []},
            {"duration": 3, "camera_distance": "ultra-wide", "lines": []},
        ],
    }
    d = diagnose_abstract(abstract)
    assert d["invalid_camera_distance"] == [
        {"scene_idx": 1, "value": "ultra-wide"},
    ]


def test_diagnose_clean_when_all_set(isolated_dirs):
    _seed(isolated_dirs)
    from analyze.compose import diagnose_abstract
    abstract = {
        "caption": "x",
        "featured_characters": ["f1"],
        "speaker_to_ref": {"speaker_1": "f1"},
        "scenes": [{
            "duration": 3,
            "location_ref": "home_office",
            "camera_distance": "medium",
            "lines": [
                {"text": "a", "start": 0, "end": 1, "speaker": "speaker_1"},
            ],
        }],
    }
    d = diagnose_abstract(abstract)
    assert d["unmapped_speakers"] == []
    assert d["scenes_without_location"] == []
    assert d["scenes_without_characters"] == []
    assert d["invalid_camera_distance"] == []
    assert d["unknown_character_refs"] == {
        "featured": [],
        "speaker_to_ref": [],
        "character_selection": [],
        "speaker": [],
    }


def test_diagnose_unknown_featured(isolated_dirs, monkeypatch):
    _seed(isolated_dirs)
    from analyze.compose import diagnose_abstract
    from analyze import character_meta as cmeta_mod
    monkeypatch.setattr(cmeta_mod, "list_character_images", lambda: ["f1"])
    abstract = {
        "caption": "x",
        "featured_characters": ["f1", "ghost1", "ghost2"],
        "scenes": [{"duration": 3, "lines": []}],
    }
    d = diagnose_abstract(abstract)
    assert sorted(d["unknown_character_refs"]["featured"]) == [
        "ghost1", "ghost2",
    ]


def test_diagnose_unknown_speaker_to_ref(isolated_dirs, monkeypatch):
    _seed(isolated_dirs)
    from analyze.compose import diagnose_abstract
    from analyze import character_meta as cmeta_mod
    monkeypatch.setattr(cmeta_mod, "list_character_images", lambda: ["f1"])
    abstract = {
        "caption": "x",
        "featured_characters": ["f1"],
        "speaker_to_ref": {"speaker_1": "f1", "speaker_2": "ghost"},
        "scenes": [{"duration": 3, "lines": []}],
    }
    d = diagnose_abstract(abstract)
    assert d["unknown_character_refs"]["speaker_to_ref"] == [
        {"speaker": "speaker_2", "ref": "ghost"},
    ]


def test_diagnose_unknown_character_selection(isolated_dirs, monkeypatch):
    _seed(isolated_dirs)
    from analyze.compose import diagnose_abstract
    from analyze import character_meta as cmeta_mod
    monkeypatch.setattr(cmeta_mod, "list_character_images", lambda: ["f1"])
    abstract = {
        "caption": "x",
        "featured_characters": ["f1"],
        "scenes": [
            {"duration": 3, "character_selection": ["ghost"], "lines": []},
            {"duration": 3, "character_selection": ["f1"], "lines": []},
        ],
    }
    d = diagnose_abstract(abstract)
    assert d["unknown_character_refs"]["character_selection"] == [
        {"scene_idx": 0, "ref": "ghost"},
    ]


def test_diagnose_unknown_speaker_in_line(isolated_dirs, monkeypatch):
    _seed(isolated_dirs)
    from analyze.compose import diagnose_abstract
    from analyze import character_meta as cmeta_mod
    monkeypatch.setattr(cmeta_mod, "list_character_images", lambda: ["f1"])
    abstract = {
        "caption": "x",
        "featured_characters": ["f1"],
        "scenes": [{
            "duration": 3,
            "lines": [
                {"text": "a", "start": 0, "end": 1, "speaker": "f1"},
                {"text": "b", "start": 1, "end": 2, "speaker": "ghost"},
                # speaker_N raw ID は別系統で diagnose されるのでここでは出ない
                {"text": "c", "start": 2, "end": 3, "speaker": "speaker_99"},
            ],
        }],
    }
    d = diagnose_abstract(abstract)
    assert d["unknown_character_refs"]["speaker"] == [
        {"scene_idx": 0, "line_idx": 1, "ref": "ghost"},
    ]


def test_diagnose_unknown_refs_skipped_when_dir_empty(isolated_dirs):
    """characters/ が空ならテスト環境扱いで検証スキップ。"""
    _seed(isolated_dirs)
    from analyze.compose import diagnose_abstract
    abstract = {
        "caption": "x",
        "featured_characters": ["literally_anything"],
        "scenes": [{"duration": 3, "lines": []}],
    }
    d = diagnose_abstract(abstract)
    assert d["unknown_character_refs"]["featured"] == []


# ─── compose の line.voice_overrides 優先順位 ───────────────────


def test_compose_preserves_line_voice_overrides(isolated_dirs):
    """line に既存の voice_overrides があれば、キャラの base voice より優先。"""
    _seed(isolated_dirs)
    abstract = _abstract_minimal()
    abstract["scenes"][0]["lines"][0]["voice_overrides"] = {
        "stability": 0.9,  # base (0.4) を上書き
    }
    sp = compose_screenplay(abstract)
    line0 = sp["scenes"][0]["lines"][0]
    # base.voice_id (= voice_p) は残しつつ、stability は line 個別優先
    assert line0["voice_overrides"]["voice_id"] == "voice_p"
    assert line0["voice_overrides"]["stability"] == 0.9
