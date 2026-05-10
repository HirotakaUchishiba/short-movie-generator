import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

TAGGER_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 600

# config/transformation_taxonomy.yaml は schema v11 で追加された概念モデル。
# 運用者管理ファイルなので読み込み失敗時は graceful degradation で taxonomy
# 説明を空文字に倒す (= 既存 5 フィールドの分類は引き続き動く)。
_TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "config" / "transformation_taxonomy.yaml"


def _load_taxonomy() -> dict:
    if not _TAXONOMY_PATH.exists():
        return {"transformations": [], "tree_main_branches": [], "povs": []}
    try:
        import yaml
        with _TAXONOMY_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("transformation_taxonomy.yaml 読込失敗: %s", e)
        return {"transformations": [], "tree_main_branches": [], "povs": []}
    return {
        "transformations": data.get("transformations") or [],
        "tree_main_branches": data.get("tree_main_branches") or [],
        "povs": data.get("povs") or [],
    }


def _format_taxonomy_section(label: str, items: list[dict]) -> str:
    if not items:
        return f"{label}: (taxonomy 未定義 — 自由文字列で返してよい)"
    lines = [f"{label}:"]
    for it in items:
        iid = it.get("id") or ""
        desc = it.get("description") or ""
        lines.append(f"  - {iid}: {desc}")
    return "\n".join(lines)


def _build_system_prompt(taxonomy: dict) -> str:
    transformation_section = _format_taxonomy_section(
        "transformation の候補", taxonomy["transformations"],
    )
    branch_section = _format_taxonomy_section(
        "tree_main_branch の候補", taxonomy["tree_main_branches"],
    )
    pov_section = _format_taxonomy_section(
        "pov_id の候補", taxonomy["povs"],
    )
    return f"""あなたはショート動画の台本を分類する専門家です。
与えられたscreenplay JSONを読み、下記フィールドを推論して**JSONのみ**を返してください。

出力フォーマット:
{{
  "hook_type": "timeline|reveal|tips|contrast|transformation|comparison|storytime|testimonial|question_hook|shock|other",
  "tone": "casual|emotional|informative|humorous|serious|encouraging",
  "dominant_emotion": "驚き|喜び|焦り|落胆|中立|満足|困惑|怒り|恥ずかしさ",
  "theme": "career_change|salary|skills|work_life_balance|industry_reality|self_improvement|other",
  "character_archetype": "簡潔な自然言語（例 \\"若い女性エンジニア\\" \\"副業志望の会社員\\"）",
  "transformation": "視聴者にもたらすスキル / 信念の変化を 1 行で。下記候補から 1 つ選ぶか、当てはまる候補が無ければ自由文字列で。",
  "tree_main_branch": "下記 4 候補のいずれか",
  "pov_id": "下記候補から 1 つ選ぶか、当てはまる候補が無ければ自由文字列で"
}}

----- 候補一覧 (= config/transformation_taxonomy.yaml から動的に生成) -----
{transformation_section}

{branch_section}

{pov_section}
-----

説明・コメントは一切出力しないこと。純粋なJSON1つだけ。"""


SYSTEM_PROMPT = _build_system_prompt(_load_taxonomy())


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
