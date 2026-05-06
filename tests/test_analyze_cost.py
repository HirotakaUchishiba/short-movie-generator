"""analyze.cost の単体テスト (token 数推定; USD 換算は cost_tracking.estimator)。"""
from analyze import cost


def test_estimate_zero_frames_returns_overhead_only() -> None:
    e = cost.estimate_tokens(frame_count=0, transcript={"text": ""})
    assert e["input_tokens"] == cost.PROMPT_OVERHEAD_TOKENS
    assert e["output_tokens"] == cost.TYPICAL_OUTPUT_TOKENS


def test_estimate_scales_with_frames() -> None:
    e0 = cost.estimate_tokens(frame_count=0)
    e60 = cost.estimate_tokens(frame_count=60)
    delta = e60["input_tokens"] - e0["input_tokens"]
    assert delta == 60 * cost.TOKENS_PER_FRAME


def test_estimate_scales_with_transcript_length() -> None:
    short = cost.estimate_tokens(frame_count=0, transcript={"text": "あ" * 10})
    long = cost.estimate_tokens(frame_count=0, transcript={"text": "あ" * 100})
    assert long["input_tokens"] > short["input_tokens"]


def test_estimate_breakdown_sums_to_input() -> None:
    e = cost.estimate_tokens(
        frame_count=30,
        transcript={"text": "テスト" * 50},
        shot_count=10,
        known_furigana_count=20,
    )
    bd = e["breakdown"]
    total = sum(bd.values())
    assert total == e["input_tokens"]


def test_estimate_returns_no_usd_field() -> None:
    """USD 換算は estimator 経由なので cost.estimate_tokens の戻り値には含めない。"""
    e = cost.estimate_tokens(frame_count=10)
    assert "cost_usd" not in e
    assert "cost_breakdown" not in e
