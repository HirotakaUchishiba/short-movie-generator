"""analyze.cost の単体テスト (コスト推定)。"""
from analyze import cost


def test_estimate_zero_frames_returns_overhead_only() -> None:
    e = cost.estimate(frame_count=0, transcript={"text": ""})
    assert e["input_tokens"] == cost.PROMPT_OVERHEAD_TOKENS
    assert e["output_tokens"] == cost.TYPICAL_OUTPUT_TOKENS
    assert e["cost_usd"] > 0


def test_estimate_scales_with_frames() -> None:
    e0 = cost.estimate(frame_count=0)
    e60 = cost.estimate(frame_count=60)
    delta = e60["input_tokens"] - e0["input_tokens"]
    assert delta == 60 * cost.TOKENS_PER_FRAME


def test_estimate_scales_with_transcript_length() -> None:
    short = cost.estimate(frame_count=0, transcript={"text": "あ" * 10})
    long = cost.estimate(frame_count=0, transcript={"text": "あ" * 100})
    assert long["input_tokens"] > short["input_tokens"]


def test_estimate_breakdown_sums_to_input() -> None:
    e = cost.estimate(
        frame_count=30,
        transcript={"text": "テスト" * 50},
        shot_count=10,
        known_furigana_count=20,
    )
    bd = e["cost_breakdown"]
    total = sum(bd.values())
    assert total == e["input_tokens"]


def test_estimate_typical_video() -> None:
    """9シーン台本の典型値で約 ¥250〜400 (≒ $1.7〜2.7) になることを確認。"""
    # 0.5秒刻みで 60秒動画 = 120 フレーム
    e = cost.estimate(
        frame_count=120,
        transcript={"text": "あ" * 200},
        shot_count=15,
        known_furigana_count=50,
    )
    # $1〜$5 のレンジに入る
    assert 1.0 < e["cost_usd"] < 5.0


def test_actual_cost_matches_pricing_constants() -> None:
    c = cost.actual_cost(input_tokens=1_000_000, output_tokens=0)
    assert c == round(cost.INPUT_USD_PER_MTOK, 4)
    c2 = cost.actual_cost(input_tokens=0, output_tokens=1_000_000)
    assert c2 == round(cost.OUTPUT_USD_PER_MTOK, 4)
