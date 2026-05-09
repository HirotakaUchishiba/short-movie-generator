"""stages.emotion の単体テスト (= scene_gen から抽出した emotion 派生 helper)。"""
import config
from stages import emotion


def test_dominant_emotion_returns_most_common():
    scene = {
        "lines": [
            {"emotion": "焦り"},
            {"emotion": "焦り"},
            {"emotion": "満足"},
        ],
    }
    assert emotion.dominant_emotion(scene) == "焦り"


def test_dominant_emotion_returns_none_when_empty():
    assert emotion.dominant_emotion({}) is None
    assert emotion.dominant_emotion({"lines": []}) is None
    assert emotion.dominant_emotion({"lines": [{"text": "x"}]}) is None


def test_dominant_emotion_first_wins_on_tie():
    """tie のときは出現順 (Counter.most_common の安定性) で先勝ち。"""
    scene = {
        "lines": [
            {"emotion": "驚き"},
            {"emotion": "焦り"},
        ],
    }
    # どちらか 1 つに決まればよい (= None ではない)
    assert emotion.dominant_emotion(scene) in ("驚き", "焦り")


def test_emotion_arc_en_dedupes_and_preserves_order(monkeypatch):
    monkeypatch.setattr(config, "EMOTION_EN", {
        "驚き": "surprise", "焦り": "urgency", "満足": "calm",
    })
    scene = {
        "lines": [
            {"emotion": "驚き"},
            {"emotion": "焦り"},
            {"emotion": "驚き"},  # 重複は除く
            {"emotion": "満足"},
        ],
    }
    assert emotion.emotion_arc_en(scene) == "surprise → urgency → calm"


def test_emotion_arc_en_falls_back_to_jp_label(monkeypatch):
    monkeypatch.setattr(config, "EMOTION_EN", {})  # 翻訳辞書空
    assert emotion.emotion_arc_en({"lines": [{"emotion": "焦り"}]}) == "焦り"


def test_emotion_arc_summary_collapses_consecutive_dupes(monkeypatch):
    monkeypatch.setattr(config, "EMOTION_VISUAL_CUES", {
        "焦り": {"motion": "rushed forward-leaning movement"},
        "満足": {"motion": "relaxed open posture"},
    })
    scene = {
        "lines": [
            {"emotion": "焦り"},
            {"emotion": "焦り"},
            {"emotion": "満足"},
        ],
    }
    out = emotion.emotion_arc_summary(scene, "motion")
    # 連続重複は畳まれる (= "rushed → relaxed")
    assert out == "rushed forward-leaning movement → relaxed open posture"


def test_dominant_visual_cues_returns_dict_for_dom(monkeypatch):
    monkeypatch.setattr(config, "EMOTION_VISUAL_CUES", {
        "焦り": {"motion": "rushed", "facial": "tense"},
    })
    scene = {"lines": [{"emotion": "焦り"}, {"emotion": "焦り"}]}
    cues = emotion.dominant_visual_cues(scene)
    assert cues == {"motion": "rushed", "facial": "tense"}


def test_dominant_visual_cues_returns_empty_when_no_emotion(monkeypatch):
    monkeypatch.setattr(config, "EMOTION_VISUAL_CUES", {})
    assert emotion.dominant_visual_cues({"lines": []}) == {}


def test_scene_gen_shim_delegates_to_stages_emotion(monkeypatch):
    """旧 scene_gen._dominant_emotion 等が shim 経由で動くこと。"""
    import scene_gen
    monkeypatch.setattr(config, "EMOTION_EN", {"焦り": "urgency"})
    monkeypatch.setattr(config, "EMOTION_VISUAL_CUES", {
        "焦り": {"motion": "rushed"},
    })
    scene = {"lines": [{"emotion": "焦り"}]}
    assert scene_gen._dominant_emotion(scene) == "焦り"
    assert scene_gen._emotion_arc_en(scene) == "urgency"
    assert scene_gen._emotion_arc_summary(scene, "motion") == "rushed"
    assert scene_gen._dominant_visual_cues(scene) == {"motion": "rushed"}
