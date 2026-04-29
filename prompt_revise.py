"""日本語の修正指示を既存の英語プロンプトに反映するモジュール。

UI から「もっとカメラを引いて」「背景を窓辺に変えて」など日本語で修正案を入力すると、
Claude Sonnet が既存の background_prompt / animation_prompt を最小限の差分で書き換える。

呼出元: preview_server の revise-prompt エンドポイント。
"""

import logging
import os

import config

logger = logging.getLogger(__name__)


_BG_SYSTEM_PROMPT = """You are a prompt editor for the Imagen text-to-image model.

You will receive:
1. The CURRENT prompt (mostly English with possible Japanese subject phrases).
2. A Japanese revision instruction from the user.

Your job: produce a REVISED prompt that incorporates the user's instruction
while preserving everything not explicitly addressed.

REQUIREMENTS:
- Output language: keep the original mix (subject phrases may stay Japanese,
  style modifiers stay English). If the user instruction adds new subject
  matter, write it in Japanese; new style modifiers in English.
- Be MINIMAL: only change what the instruction asks. Do not paraphrase,
  reorder, or "improve" untouched parts.
- NEVER add UI elements: no chat bubbles, notifications, on-screen text,
  smartphone screens, infographics, popups, speech bubbles.
- Keep cinematic / photographic style modifiers intact unless the user
  asks to change them (e.g. "cinematic lighting", "shallow depth of field").
- If the user instruction is ambiguous, apply the most literal interpretation.
- Do NOT add commentary, quotes, or markdown fences.

Output ONLY the revised prompt as a single line of plain text. No prefix.
No explanation."""


_ANIM_SYSTEM_PROMPT = """You are a prompt editor for the Kling V3 image-to-video model.

You will receive:
1. The CURRENT animation_prompt (English, describing body motion across the scene).
2. A Japanese revision instruction from the user.

Your job: produce a REVISED prompt that incorporates the user's instruction
while preserving everything not explicitly addressed.

REQUIREMENTS:
- Output language: ENGLISH (Kling responds best to English structural prompts).
- Use concrete body verbs (gasps, leans, eyes widen, exhales, tilts head).
  NEVER use abstract verbs like "reacts", "discovers", "checks", "notices".
- NEVER mention UI elements: no chat bubbles, notifications, popups,
  on-screen text, smartphone screens, infographics, speech bubbles.
- Be MINIMAL: only change what the instruction asks. Do not paraphrase,
  reorder, or "improve" untouched parts.
- Preserve continuity (the prompt describes a single scene's motion arc).
- If the user instruction is ambiguous, apply the most literal interpretation.
- Do NOT add commentary, quotes, or markdown fences.

Output ONLY the revised prompt as a single line of plain text. No prefix.
No explanation."""


_FORBIDDEN_TOKENS = (
    "chat bubble", "notification", "popup", "smartphone screen",
    "on-screen text", "infographic", "speech bubble",
)


def _validate_revised(text: str) -> None:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("修正後 prompt が空")
    blob = text.lower()
    hits = [t for t in _FORBIDDEN_TOKENS if t in blob]
    if hits:
        raise ValueError(
            f"修正後 prompt に UI 誘発語を検出: {hits}. 修正指示を見直してください。"
        )


def _strip_wrappers(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```", 2)
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json") or text.startswith("text"):
                text = text.split("\n", 1)[1] if "\n" in text else ""
            text = text.strip()
            if text.endswith("```"):
                text = text[:-3].strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1].strip()
    return text


def revise(
    current_prompt: str,
    instruction_ja: str,
    field: str,
    model: str | None = None,
    max_tokens: int | None = None,
) -> dict:
    """日本語修正指示を反映した新プロンプトを返す。

    Args:
        current_prompt: 現在の (合成済み) プロンプト
        instruction_ja: 日本語の修正指示
        field: "background_prompt" or "animation_prompt"
        model: Claude モデル ID (省略時は config から取得)
        max_tokens: 最大トークン数

    Returns:
        {"revised": "<new prompt>", "model": "...", "field": "..."}
    """
    if field not in ("background_prompt", "animation_prompt"):
        raise ValueError(f"未知の field: {field}")
    if not isinstance(current_prompt, str):
        raise ValueError("current_prompt は文字列必須")
    if not isinstance(instruction_ja, str) or not instruction_ja.strip():
        raise ValueError("instruction_ja が空")

    import anthropic

    key = config.ANTHROPIC_API_KEY if hasattr(config, "ANTHROPIC_API_KEY") \
        else os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY が未設定。prompt_revise は使用できません。"
        )

    system = _BG_SYSTEM_PROMPT if field == "background_prompt" else _ANIM_SYSTEM_PROMPT
    model_id = model or config.PROMPT_REVISE_MODEL
    max_tok = max_tokens or config.PROMPT_REVISE_MAX_TOKENS

    user_text = (
        f"# CURRENT prompt\n{current_prompt}\n\n"
        f"# Revision instruction (Japanese)\n{instruction_ja.strip()}"
    )

    client = anthropic.Anthropic(api_key=key)
    response = client.messages.create(
        model=model_id,
        max_tokens=max_tok,
        system=system,
        messages=[{"role": "user", "content": user_text}],
    )
    raw = "".join(
        block.text for block in response.content
        if getattr(block, "type", None) == "text"
    )
    revised = _strip_wrappers(raw)
    _validate_revised(revised)

    logger.info(
        "prompt_revise: field=%s model=%s instruction=%r len_before=%d len_after=%d",
        field, model_id, instruction_ja[:40], len(current_prompt), len(revised),
    )
    return {"revised": revised, "model": model_id, "field": field}
