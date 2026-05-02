"""Claude Opus 4.7 を使った analyze pipeline のコスト推定。

Vision モデルへのフレーム画像入力、transcript / furigana 辞書の text 入力、
output JSON の token 消費量を概算する。

コストゲート (Phase 5 の awaiting_confirm) でユーザー confirm 前に推定値を
見せる用途。
"""

# Claude Opus 4.7 価格 (2026 時点)
INPUT_USD_PER_MTOK = 15.0
OUTPUT_USD_PER_MTOK = 75.0

# 882×496 px JPEG 1 枚あたりの推定 token (Anthropic の image token 計算式から)
TOKENS_PER_FRAME = 1568

# 日本語テキスト 1 文字あたりの token 推定 (≈ 1.5 tok/char)
TOKENS_PER_JA_CHAR = 1.5

# システムプロンプト + タスク指示の固定オーバーヘッド
PROMPT_OVERHEAD_TOKENS = 3000

# screenplay JSON 出力の典型的 token (約 9 シーン台本で 10〜14k)
TYPICAL_OUTPUT_TOKENS = 12000


def estimate(
    *,
    frame_count: int,
    transcript: dict | None = None,
    shot_count: int = 0,
    known_furigana_count: int = 0,
    typical_output_tokens: int = TYPICAL_OUTPUT_TOKENS,
) -> dict:
    """Claude 呼び出しの input/output tokens と USD コストを概算する。

    Returns:
        {
            "input_tokens": int,
            "output_tokens": int,
            "cost_usd": float,
            "cost_breakdown": {
                "frames_tokens": int,
                "transcript_tokens": int,
                "shots_tokens": int,
                "furigana_tokens": int,
                "overhead_tokens": int,
            },
        }
    """
    transcript_text = ""
    if transcript:
        transcript_text = transcript.get("text", "") or ""
    transcript_chars = len(transcript_text)

    frames_tokens = frame_count * TOKENS_PER_FRAME
    transcript_tokens = int(transcript_chars * TOKENS_PER_JA_CHAR)
    shots_tokens = shot_count * 30
    furigana_tokens = known_furigana_count * 10
    overhead_tokens = PROMPT_OVERHEAD_TOKENS

    input_tokens = (
        overhead_tokens
        + frames_tokens
        + transcript_tokens
        + shots_tokens
        + furigana_tokens
    )
    output_tokens = typical_output_tokens

    cost_usd = (
        input_tokens * INPUT_USD_PER_MTOK / 1_000_000
        + output_tokens * OUTPUT_USD_PER_MTOK / 1_000_000
    )

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 4),
        "cost_breakdown": {
            "frames_tokens": frames_tokens,
            "transcript_tokens": transcript_tokens,
            "shots_tokens": shots_tokens,
            "furigana_tokens": furigana_tokens,
            "overhead_tokens": overhead_tokens,
        },
    }


def actual_cost(input_tokens: int, output_tokens: int) -> float:
    """実際のレスポンス usage から正確な USD コストを算出する。"""
    return round(
        input_tokens * INPUT_USD_PER_MTOK / 1_000_000
        + output_tokens * OUTPUT_USD_PER_MTOK / 1_000_000,
        4,
    )
