"""analyze 後処理 _normalize_action_and_intent の正規化を検証する。

actions/ と config/part_registry/visual_intents.yaml の実定義に依存する
(= gesture_pointing は action 未定義 / stand_thinking は定義済み /
talking_head_calm は驚き非許容 / talking_head_animated は驚き許容)。
"""

import video_analyzer


def test_drops_undefined_action_id() -> None:
    parsed = {"scenes": [{"action_id": "gesture_pointing", "annotation": {}, "lines": []}]}
    video_analyzer._normalize_action_and_intent(parsed)
    assert "action_id" not in parsed["scenes"][0]


def test_keeps_defined_action_id() -> None:
    parsed = {"scenes": [{"action_id": "stand_thinking", "annotation": {}, "lines": []}]}
    video_analyzer._normalize_action_and_intent(parsed)
    assert parsed["scenes"][0]["action_id"] == "stand_thinking"


def test_drops_intent_with_incompatible_start_emotion() -> None:
    # talking_head_calm の valid_start_emotions に 驚き は含まれない
    parsed = {"scenes": [{
        "annotation": {"visual_intent_id": "talking_head_calm"},
        "lines": [{"emotion": "驚き"}],
    }]}
    video_analyzer._normalize_action_and_intent(parsed)
    assert "visual_intent_id" not in parsed["scenes"][0]["annotation"]


def test_keeps_intent_with_compatible_start_emotion() -> None:
    # talking_head_animated は 驚き を許容
    parsed = {"scenes": [{
        "annotation": {"visual_intent_id": "talking_head_animated"},
        "lines": [{"emotion": "驚き"}],
    }]}
    video_analyzer._normalize_action_and_intent(parsed)
    assert parsed["scenes"][0]["annotation"]["visual_intent_id"] == "talking_head_animated"


def test_drops_undefined_visual_intent() -> None:
    parsed = {"scenes": [{"annotation": {"visual_intent_id": "nonexistent_intent"}, "lines": []}]}
    video_analyzer._normalize_action_and_intent(parsed)
    assert "visual_intent_id" not in parsed["scenes"][0]["annotation"]


def test_keeps_intent_when_no_start_emotion() -> None:
    # start_emotion が解決できない場合は valid_start_emotions チェックをスキップ (保持)
    parsed = {"scenes": [{"annotation": {"visual_intent_id": "talking_head_calm"}, "lines": []}]}
    video_analyzer._normalize_action_and_intent(parsed)
    assert parsed["scenes"][0]["annotation"]["visual_intent_id"] == "talking_head_calm"


def test_resolves_start_emotion_from_identity_first() -> None:
    # identity.start_emotion が lines[0].emotion より優先される
    parsed = {"scenes": [{
        "identity": {"start_emotion": "驚き"},
        "annotation": {"visual_intent_id": "talking_head_calm"},
        "lines": [{"emotion": "中立"}],
    }]}
    video_analyzer._normalize_action_and_intent(parsed)
    assert "visual_intent_id" not in parsed["scenes"][0]["annotation"]
