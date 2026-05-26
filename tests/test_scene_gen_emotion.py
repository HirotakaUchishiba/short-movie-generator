import scene_gen


def test_apply_pronunciation_hints_single() -> None:
    assert scene_gen._apply_pronunciation_hints("IT業界", {"IT": "アイティー"}) == "アイティー業界"


def test_apply_pronunciation_hints_multiple() -> None:
    assert scene_gen._apply_pronunciation_hints(
        "ITやPCの話", {"IT": "アイティー", "PC": "ピーシー"}
    ) == "アイティーやピーシーの話"


def test_apply_pronunciation_hints_none() -> None:
    assert scene_gen._apply_pronunciation_hints("そのまま", None) == "そのまま"


def test_apply_pronunciation_hints_global_dict_only() -> None:
    text = scene_gen._apply_pronunciation_hints(
        "ITとPC", None, global_dict={"IT": "アイティー", "PC": "ピーシー"},
    )
    assert text == "アイティーとピーシー"


def test_apply_pronunciation_hints_line_overrides_global() -> None:
    text = scene_gen._apply_pronunciation_hints(
        "IT業界",
        hints={"IT": "アイティー"},        # line override
        global_dict={"IT": "アイティー"},  # default reading
    )
    assert text == "アイティー業界"


def test_apply_pronunciation_hints_longer_keys_replace_first() -> None:
    text = scene_gen._apply_pronunciation_hints(
        "納期間に",
        hints=None,
        global_dict={"納期": "のうき", "納期間に": "のうきまに"},
    )
    assert text == "のうきまに"


def test_dominant_emotion_simple() -> None:
    scene = {"lines": [
        {"emotion": "驚き"},
        {"emotion": "喜び"},
        {"emotion": "驚き"},
    ]}
    assert scene_gen._dominant_emotion(scene) == "驚き"


def test_dominant_emotion_none_when_empty() -> None:
    assert scene_gen._dominant_emotion({"lines": []}) is None
    assert scene_gen._dominant_emotion({"lines": [{"text": "a"}]}) is None


def test_animation_prompt_appends_emotion_motion(monkeypatch) -> None:
    """line.emotion から EMOTION_VISUAL_CUES の motion / camera が注入される。"""
    monkeypatch.setitem(
        scene_gen.config.EMOTION_VISUAL_CUES, "驚き",
        {"motion": "sudden startled motion", "camera": "snap zoom",
         "facial": "wide eyes", "tone": "startled", "lighting": "bright"},
    )
    scene = {
        "animation_prompt": "subject walks forward",
        "background_prompt": "office",
        "lines": [{"emotion": "驚き", "start": 0}],
    }
    result = scene_gen._get_animation_prompt(scene)
    assert "subject walks forward" in result
    assert "sudden startled motion" in result


def test_animation_prompt_no_emotion() -> None:
    scene = {
        "animation_prompt": "subject walks",
        "background_prompt": "office",
        "lines": [{"start": 0}],
    }
    assert scene_gen._get_animation_prompt(scene) == "subject walks"


def test_build_background_prompt_excludes_wardrobe_text() -> None:
    """新スキーマ: 衣装テキスト ("wearing X") は prompt に書かない。
    衣装は characters/<ref>__<wardrobe>.png reference 画像で identity を保証する。"""
    scene = {
        "background_prompt": "オフィス背景",
        "wardrobe_tag": "office",
        "lines": [{"text": "a", "start": 0, "emotion": "喜び"}],
    }
    prompt = scene_gen._build_background_prompt(scene, {})
    assert "オフィス背景" in prompt
    # 衣装テキストは挿入されない (= reference 画像で保証)
    assert "wearing" not in prompt


def test_build_background_prompt_multi_character_excludes_ids() -> None:
    """多人数: キャラ ID は prompt に直接登場しない (= reference 画像が SSOT)。
    Stage 3 では compose 由来の `the depicted ... people` 表現で抽象化される。"""
    scene = {
        "background_prompt": "medium shot of the two depicted people facing each other in conversation",
        "characters": [
            {"name": "female_engineer"},
            {"name": "male_engineer"},
        ],
    }
    prompt = scene_gen._build_background_prompt(scene)
    assert "female_engineer" not in prompt
    assert "male_engineer" not in prompt
    assert "two depicted people" in prompt


def test_neighbor_line_text_within_scene() -> None:
    sp = {"scenes": [{"lines": [{"text": "A"}, {"text": "B"}, {"text": "C"}]}]}
    assert scene_gen._neighbor_line_text(sp, 0, 1, "prev") == "A"
    assert scene_gen._neighbor_line_text(sp, 0, 1, "next") == "C"


def test_neighbor_line_text_crosses_scene_boundary() -> None:
    sp = {
        "scenes": [
            {"lines": [{"text": "A"}, {"text": "B"}]},
            {"lines": [{"text": "C"}, {"text": "D"}]},
        ]
    }
    assert scene_gen._neighbor_line_text(sp, 1, 0, "prev") == "B"
    assert scene_gen._neighbor_line_text(sp, 0, 1, "next") == "C"


def test_neighbor_line_text_skips_empty_scenes() -> None:
    sp = {
        "scenes": [
            {"lines": [{"text": "A"}]},
            {"lines": []},
            {"lines": [{"text": "C"}]},
        ]
    }
    assert scene_gen._neighbor_line_text(sp, 2, 0, "prev") == "A"
    assert scene_gen._neighbor_line_text(sp, 0, 0, "next") == "C"


def test_neighbor_line_text_returns_none_at_extremes() -> None:
    sp = {"scenes": [{"lines": [{"text": "A"}]}]}
    assert scene_gen._neighbor_line_text(sp, 0, 0, "prev") is None
    assert scene_gen._neighbor_line_text(sp, 0, 0, "next") is None


def test_neighbor_line_text_handles_none_screenplay() -> None:
    assert scene_gen._neighbor_line_text(None, 0, 0, "prev") is None
    assert scene_gen._neighbor_line_text(None, 0, 0, "next") is None


def test_clean_text_normalizes_uncommon_punctuation() -> None:
    assert scene_gen._clean_text("え年収200万アップ⁉") == "え年収200万アップ!?"
    assert scene_gen._clean_text("最高‼") == "最高!!"
    assert scene_gen._clean_text("便利〜") == "便利ー"
    assert scene_gen._clean_text("…そうか") == "そうか"


def test_get_animation_prompt_injects_emotion_visual_cues() -> None:
    """lines[].emotion の dominant に対応する EMOTION_VISUAL_CUES が注入される。"""
    scene = {
        "animation_prompt": "subject walks",
        "lines": [
            {"text": "a", "start": 0, "emotion": "焦り"},
            {"text": "b", "start": 1, "emotion": "焦り"},
        ],
    }
    prompt = scene_gen._get_animation_prompt(scene)
    cue = scene_gen.config.EMOTION_VISUAL_CUES["焦り"]
    assert cue["motion"] in prompt
    assert cue["camera"] in prompt


def test_get_animation_prompt_emotion_arc_uses_english() -> None:
    """emotion arc は EMOTION_EN で英訳されて prompt に入る。"""
    scene = {
        "animation_prompt": "x",
        "lines": [
            {"text": "a", "start": 0, "emotion": "焦り"},
            {"text": "b", "start": 1, "emotion": "焦り"},
            {"text": "c", "start": 2, "emotion": "満足"},
        ],
    }
    prompt = scene_gen._get_animation_prompt(scene)
    # 焦り×2 → 1 つに畳まれ、満足 と arc を成す。英訳された arc が単一登場
    assert "emotion arc:" in prompt
    assert "urgency → satisfaction" in prompt
    assert "焦り" not in prompt  # 完全英文化


def test_get_animation_prompt_appends_audio_dynamics(tmp_path, monkeypatch) -> None:
    """ts_path/s_idx 渡すと audio_dynamics サマリが末尾に追加される。"""
    import audio_dynamics
    monkeypatch.setattr(audio_dynamics, "summarize_scene_dynamics",
                          lambda lines, ts, s: "audio dynamics arc: line0 [strong fast]")
    scene = {
        "animation_prompt": "x",
        "lines": [{"text": "a", "start": 0, "emotion": "焦り"}],
    }
    prompt = scene_gen._get_animation_prompt(scene, ts_path=str(tmp_path), s_idx=0)
    assert "audio dynamics arc: line0 [strong fast]" in prompt


def test_get_animation_prompt_no_emotion_returns_base_only() -> None:
    """SSOT: emotion が無ければ base prompt のみ。廃止された facial_expression / hand_gesture には fallback しない。"""
    scene = {
        "animation_prompt": "subject walks",
        "lines": [{"text": "a", "start": 0}],  # emotion なし
    }
    prompt = scene_gen._get_animation_prompt(scene)
    assert prompt == "subject walks"


def test_get_animation_prompt_injects_visual_intent_motion_hint() -> None:
    """annotation.visual_intent_id の motion_hint が movement directive として注入される。"""
    import part_registry_loader
    scene = {
        "animation_prompt": "subject speaks",
        "annotation": {"visual_intent_id": "gesture_pointing"},
        "lines": [{"text": "a", "start": 0}],
    }
    prompt = scene_gen._get_animation_prompt(scene)
    hint = part_registry_loader.motion_hint_map()["gesture_pointing"]
    assert f"movement: {hint}" in prompt


def test_get_animation_prompt_distinct_intents_distinct_movement() -> None:
    """intent が違えば movement directive も変わる (= 単調さ防止)。"""
    import part_registry_loader
    hints = part_registry_loader.motion_hint_map()

    def _prompt_for(intent_id: str) -> str:
        return scene_gen._get_animation_prompt({
            "animation_prompt": "subject speaks",
            "annotation": {"visual_intent_id": intent_id},
            "lines": [{"text": "a", "start": 0}],
        })

    calm = _prompt_for("talking_head_calm")
    animated = _prompt_for("talking_head_animated")
    assert hints["talking_head_calm"] in calm
    assert hints["talking_head_animated"] in animated
    assert calm != animated


def test_get_animation_prompt_no_intent_no_movement() -> None:
    """visual_intent_id が無ければ movement directive は足さない (graceful)。"""
    scene = {
        "animation_prompt": "subject speaks",
        "lines": [{"text": "a", "start": 0}],
    }
    prompt = scene_gen._get_animation_prompt(scene)
    assert "movement:" not in prompt


def test_get_animation_prompt_unknown_intent_no_movement() -> None:
    """未定義 intent_id は motion_hint_map に無いので何も足さない (graceful)。"""
    scene = {
        "animation_prompt": "subject speaks",
        "annotation": {"visual_intent_id": "no_such_intent"},
        "lines": [{"text": "a", "start": 0}],
    }
    prompt = scene_gen._get_animation_prompt(scene)
    assert "movement:" not in prompt


def test_build_background_prompt_injects_emotion_visual_cues() -> None:
    scene = {
        "background_prompt": "オフィス",
        "lines": [{"text": "a", "start": 0, "emotion": "焦り"}],
    }
    prompt = scene_gen._build_background_prompt(scene)
    cue = scene_gen.config.EMOTION_VISUAL_CUES["焦り"]
    assert cue["lighting"] in prompt
    assert cue["tone"] in prompt
    # facial (表情) は reference 画像に任せ、Imagen の顔再解釈による別人化を避けるため
    # bg prompt には注入しない (= STAGE_CUE_CATEGORIES["bg"] から除外)
    assert cue["facial"] not in prompt


def test_build_background_prompt_excludes_audio_dynamics(tmp_path, monkeypatch) -> None:
    """Stage 3 (静止画) には audio_dynamics は混入しない (= 動的情報は Stage 4 専用)。"""
    import audio_dynamics
    called = {"flag": False}

    def fake_dyn(lines, ts, s):
        called["flag"] = True
        return "audio dynamics arc: should not appear"

    monkeypatch.setattr(audio_dynamics, "summarize_scene_dynamics", fake_dyn)
    scene = {
        "background_prompt": "オフィス",
        "lines": [{"text": "a", "start": 0, "emotion": "驚き"}],
    }
    prompt = scene_gen._build_background_prompt(scene, ts_path=str(tmp_path), s_idx=0)
    assert "audio dynamics arc:" not in prompt
    assert called["flag"] is False  # そもそも呼ばれない


def test_emotion_arc_summary_dedupes_consecutive() -> None:
    scene = {
        "lines": [
            {"text": "a", "start": 0, "emotion": "焦り"},
            {"text": "b", "start": 1, "emotion": "焦り"},
            {"text": "c", "start": 2, "emotion": "満足"},
        ],
    }
    out = scene_gen._emotion_arc_summary(scene, "motion")
    assert " → " in out
    assert out.count("→") == 1  # 焦り×2 が畳まれて 焦り→満足


def test_dominant_visual_cues_uses_emotion_default() -> None:
    """override 無しなら emotion 由来の既定 cue。"""
    scene = {"lines": [{"text": "x", "start": 0, "emotion": "焦り"}]}
    cues = scene_gen._dominant_visual_cues(scene)
    assert cues["facial"] == scene_gen.config.EMOTION_VISUAL_CUES["焦り"]["facial"]


def test_regen_background_scene_preserves_audio_m4a(tmp_path, monkeypatch) -> None:
    """BG再生成は TTS 由来の audio_<S>.m4a を削除してはいけない (独立)。"""
    sp = {
        "scenes": [
            {"duration": 3, "background_prompt": "x", "lines": []},
        ],
    }
    # 偽のファイル群を tmp_path に置く
    audio_path = tmp_path / "audio_000.m4a"
    audio_path.write_bytes(b"audio content")
    bg_path = tmp_path / "bg_000.png"
    bg_path.write_bytes(b"bg content")
    kling_path = tmp_path / "kling_000.mp4"
    kling_path.write_bytes(b"kling content")
    scene_trim_path = tmp_path / "scene_000.trim.mp4"
    scene_trim_path.write_bytes(b"trim content")

    # _generate_background_with_retry は実Imagen呼出しなので mock
    monkeypatch.setattr(
        scene_gen, "_generate_background_with_retry",
        lambda s_idx, scene, td, sp: ("bg_000", str(bg_path)),
    )

    scene_gen.regen_background_scene(0, sp, str(tmp_path))

    # audio_*.m4a は残る (TTS由来なのでBG再生成では消さない)
    assert audio_path.exists(), "audio_<S>.m4a が誤って削除されている"
    # 下流ファイルは削除されている
    assert not kling_path.exists()
    assert not scene_trim_path.exists()
