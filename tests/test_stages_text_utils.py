"""stages.text_utils の単体テスト (= scene_gen から抽出した text 整形)。"""
import pytest

from stages import text_utils


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1. これは文", "これは文"),
        ("2) また別の文", "また別の文"),
        ("ラベル（補足）本文", "ラベル本文"),
        ("a, b. c。", "a b c"),
        ("これは⁉ びっくり‼", "これは!? びっくり!!"),
        ("〜伸ばし〜", "ー伸ばしー"),  # U+301C wave dash → ー
        ("…省略", "省略"),
    ],
)
def test_clean_text(raw, expected):
    assert text_utils.clean_text(raw) == expected


def test_apply_pronunciation_hints_line_overrides_global():
    """line.hints の key は global を上書きする。"""
    out = text_utils.apply_pronunciation_hints(
        "AI と IT の話",
        hints={"AI": "エーアイ"},
        global_dict={"AI": "アイ", "IT": "アイティー"},
    )
    assert out == "エーアイ と アイティー の話"


def test_apply_pronunciation_hints_long_key_first():
    """長い key が先に置換される (= prefix 衝突対策)。"""
    out = text_utils.apply_pronunciation_hints(
        "AIモデル を見る",
        hints=None,
        global_dict={"AI": "エイ", "AIモデル": "エーアイモデル"},
    )
    assert out == "エーアイモデル を見る"


def test_apply_pronunciation_hints_empty_returns_input():
    out = text_utils.apply_pronunciation_hints("そのまま", None, None)
    assert out == "そのまま"


def test_scene_gen_shim_delegates_to_stages_text_utils():
    """旧 scene_gen._clean_text / _apply_pronunciation_hints が shim 経由で動くこと。"""
    import scene_gen
    assert scene_gen._clean_text("1. テスト、") == "テスト"
    assert scene_gen._apply_pronunciation_hints(
        "AI", {"AI": "エーアイ"}, None,
    ) == "エーアイ"
