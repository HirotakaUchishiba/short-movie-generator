import scene_gen


def test_strips_half_width_comma_period() -> None:
    assert scene_gen._clean_text("hello, world.") == "hello world"


def test_strips_full_width_comma_period() -> None:
    assert scene_gen._clean_text("転職の話、本当に。") == "転職の話本当に"


def test_strips_japanese_quote_brackets() -> None:
    assert scene_gen._clean_text("「キャリア」の「真実」") == "キャリアの真実"


def test_strips_double_quote_brackets() -> None:
    assert scene_gen._clean_text("『年収アップ』のコツ") == "年収アップのコツ"


def test_strips_numbered_prefix_at_start() -> None:
    assert scene_gen._clean_text("1. 退職理由") == "退職理由"
    assert scene_gen._clean_text("2) 次の話") == "次の話"


def test_strips_parenthetical_content() -> None:
    result = scene_gen._clean_text("(補足)ここで話します")
    assert "補足" not in result
    assert "ここで話します" in result


def test_combined_removal() -> None:
    result = scene_gen._clean_text("1. 「重要」な話、ここで(注)します。")
    assert "「" not in result
    assert "」" not in result
    assert "、" not in result
    assert "。" not in result
    assert "1." not in result
    assert "(注)" not in result
    assert "重要" in result
