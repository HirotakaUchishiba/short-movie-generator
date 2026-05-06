"""Claude Opus 4.7 への入力 token 数の概算。

USD 換算は ``cost_tracking.estimator.estimate_analyze()`` (= 履歴ベース) に集約。
ここは「frame / transcript / shot / furigana → token 数」の推定だけを担う
(= 単価ハードコードを置かない、純粋に token 数を見積もる単一責務)。
"""

# 882×496 px JPEG 1 枚あたりの推定 token (Anthropic の image token 計算式から)
TOKENS_PER_FRAME = 1568

# 日本語テキスト 1 文字あたりの token 推定 (≈ 1.5 tok/char)
TOKENS_PER_JA_CHAR = 1.5

# システムプロンプト + タスク指示の固定オーバーヘッド
PROMPT_OVERHEAD_TOKENS = 3000

# screenplay JSON 出力の典型的 token (約 9 シーン台本で 10〜14k)
TYPICAL_OUTPUT_TOKENS = 12000


def estimate_tokens(
    *,
    frame_count: int,
    transcript: dict | None = None,
    shot_count: int = 0,
    known_furigana_count: int = 0,
    typical_output_tokens: int = TYPICAL_OUTPUT_TOKENS,
) -> dict:
    """Claude 呼び出しの input/output tokens を概算する (USD 換算は呼び出し側で)。

    Returns:
        {
            "input_tokens": int,
            "output_tokens": int,
            "breakdown": {
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

    return {
        "input_tokens": input_tokens,
        "output_tokens": typical_output_tokens,
        "breakdown": {
            "frames_tokens": frames_tokens,
            "transcript_tokens": transcript_tokens,
            "shots_tokens": shots_tokens,
            "furigana_tokens": furigana_tokens,
            "overhead_tokens": overhead_tokens,
        },
    }
