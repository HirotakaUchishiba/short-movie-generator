import json
import logging
import os

logger = logging.getLogger(__name__)

TAGGER_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 400

SYSTEM_PROMPT = """あなたはショート動画の台本を分類する専門家です。
与えられたscreenplay JSONを読み、下記フィールドを推論して**JSONのみ**を返してください。

出力フォーマット:
{
  "hook_type": "timeline|reveal|tips|contrast|transformation|comparison|storytime|testimonial|question_hook|shock|other",
  "tone": "casual|emotional|informative|humorous|serious|encouraging",
  "dominant_emotion": "驚き|喜び|焦り|落胆|中立|満足|困惑|怒り|恥ずかしさ",
  "theme": "career_change|salary|skills|work_life_balance|industry_reality|self_improvement|other",
  "character_archetype": "簡潔な自然言語（例 \"若い女性エンジニア\" \"副業志望の会社員\"）"
}

説明・コメントは一切出力しないこと。純粋なJSON1つだけ。"""


def classify_screenplay(screenplay: dict, api_key: str | None = None) -> dict:
    """Claude Haiku 4.5で台本を分類してタグ辞書を返す。"""
    import anthropic

    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY未設定")

    minimal = {
        "caption": screenplay.get("caption"),
        "audio_mode": screenplay.get("audio_mode"),
        "scenes": [
            {
                "label": s.get("label"),
                "duration": s.get("duration"),
                "lines": [
                    {"text": l.get("text"), "emotion": l.get("emotion")}
                    for l in (s.get("lines") or [])
                ],
            }
            for s in (screenplay.get("scenes") or [])
        ],
    }

    client = anthropic.Anthropic(api_key=key)
    response = client.messages.create(
        model=TAGGER_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [{
                "type": "text",
                "text": "# 分類対象の台本\n\n" + json.dumps(minimal, ensure_ascii=False, indent=2),
            }],
        }],
    )

    text = "".join(
        block.text for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()

    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
        if text.endswith("```"):
            text = text[:-3].strip()

    try:
        tags = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("auto_tag JSON parse error: %s\n%s", e, text[:500])
        raise RuntimeError(f"auto_tag応答がJSON parse不能: {e}")

    return tags
