"""シーンの lines / emotion / delivery / acoustic / location_ref から
Kling V3 用 animation_prompt を Claude Sonnet で自動生成する。

設計方針:
  - scene.lines[] は既に「シーン意図の決定論的記述」になっているので、
    これをそのまま LLM に渡して身体動作シーケンスに翻訳させる。
  - 出力は subject / action_sequence / camera / mood の構造化フォーマットで
    取得し、合成して 1 文の prompt にする。
  - UI hallucination 抑止 (chat bubble / notification 等) を system prompt
    レベルで強制する。
  - 入力ハッシュベースのキャッシュで同じ入力 → 同じ prompt を保証する
    (Stage 4 を何度走らせても安定)。

呼出元:
  - scene_gen._get_animation_prompt: 手書き animation_prompt が無い場合に
    自動生成して採用する。
  - preview_server: UI から手動で再生成リクエスト。
"""

import hashlib
import json
import logging
import os

import config

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a prompt writer for the Kling V3 image-to-video model.
Generate a body-motion description for the entire scene from the provided lines.

REQUIREMENTS:
- Use concrete body verbs (gasps, leans, eyes widen, exhales, tilts head).
  NEVER use abstract verbs like "reacts", "discovers", "checks", "notices".
- NEVER mention UI elements: no chat bubbles, no notifications, no popups,
  no on-screen text, no smartphone screens, no infographics.
- Build a continuous motion ARC across all lines (not isolated per-line snapshots).
  Use acoustic.pitch_trend, rms_peak, wpm, delivery, emotion to derive motion onset
  and timing.
- Match the wpm: high wpm → quicker, sharper motions / low wpm → slower, settled.
- Match pitch_trend: rising → upward gaze/posture, falling → downward/relax.
- Keep camera and lighting subtle (the scene-level emotion cues already exist
  in the pipeline; do not duplicate them).
- Output language: ENGLISH for animation_prompt fields (Kling responds best
  to English structural prompts).

Output ONLY valid JSON with this exact shape:
{
  "subject": "<who is on screen, e.g. 'Young woman in glasses'>",
  "action_sequence": "<continuous body motion arc in one sentence, no UI words>",
  "camera": "<short camera direction, e.g. 'subtle slow zoom-in then steady'>",
  "mood": "<one short phrase, e.g. 'tense relief'>"
}

No prose. No markdown fence. No explanation. JSON only."""


# ─────────────────────── キャッシュ ───────────────────────


def _cache_dir(ts_path: str) -> str:
    return os.path.join(ts_path, config.AUTO_ANIMATION_PROMPT_CACHE_SUBDIR)


def _cache_path(ts_path: str, scene_idx: int) -> str:
    return os.path.join(_cache_dir(ts_path), f"scene_{scene_idx:03d}.json")


def _input_signature(scene: dict, screenplay: dict | None) -> dict:
    """ハッシュ生成用の入力スナップショット。
    変わったら再生成、変わらなければキャッシュ命中。"""
    lines = scene.get("lines") or []
    return {
        "duration": scene.get("duration"),
        "label": scene.get("label"),
        "location_ref": scene.get("location_ref"),
        "wardrobe_id": (scene.get("wardrobe") or {}).get("identifier"),
        "characters": scene.get("characters") or [],
        "lines": [
            {
                "text": l.get("text"),
                "emotion": l.get("emotion"),
                "emotion_intensity": l.get("emotion_intensity"),
                "delivery": l.get("delivery"),
                "acoustic": l.get("acoustic"),
                "speaker": l.get("speaker"),
                "pause_before": l.get("pause_before"),
                "breath_before": l.get("breath_before"),
            }
            for l in lines
        ],
        "model": config.AUTO_ANIMATION_PROMPT_MODEL,
    }


def _input_hash(sig: dict) -> str:
    canonical = json.dumps(sig, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read_cache(ts_path: str, scene_idx: int, expected_hash: str) -> dict | None:
    p = _cache_path(ts_path, scene_idx)
    if not os.path.exists(p):
        return None
    try:
        with open(p) as f:
            entry = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if entry.get("input_hash") != expected_hash:
        return None
    return entry


def _write_cache(ts_path: str, scene_idx: int, entry: dict) -> None:
    os.makedirs(_cache_dir(ts_path), exist_ok=True)
    p = _cache_path(ts_path, scene_idx)
    with open(p, "w") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)


# ─────────────────────── LLM 呼出 ───────────────────────


def _build_user_payload(scene: dict, screenplay: dict | None) -> str:
    """LLM に渡す入力を整形する。

    location や wardrobe は ID だけ渡す (詳細は他段でプロンプトに展開済み)。
    """
    lines = scene.get("lines") or []
    payload = {
        "duration": scene.get("duration"),
        "label": scene.get("label"),
        "location_ref": scene.get("location_ref"),
        "wardrobe_id": (scene.get("wardrobe") or {}).get("identifier"),
        "characters": scene.get("characters") or [],
        "lines": [
            {
                "text": l.get("text"),
                "emotion": l.get("emotion"),
                "emotion_intensity": l.get("emotion_intensity"),
                "delivery": l.get("delivery"),
                "acoustic": l.get("acoustic"),
                "speaker": l.get("speaker"),
                "pause_before": l.get("pause_before"),
                "breath_before": l.get("breath_before"),
                "start": l.get("start"),
            }
            for l in lines
        ],
    }
    return "# Scene metadata\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        # ``` または ```json
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    return text


_REQUIRED_KEYS = ("subject", "action_sequence", "camera", "mood")
_FORBIDDEN_TOKENS = (
    "chat bubble", "notification", "popup", "smartphone screen",
    "on-screen text", "infographic", "speech bubble",
)


def _validate_structured(parsed: dict) -> None:
    for k in _REQUIRED_KEYS:
        v = parsed.get(k)
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"animation_prompt の {k} が空または非文字列: {v!r}")
    blob = " ".join(str(parsed[k]) for k in _REQUIRED_KEYS).lower()
    hits = [t for t in _FORBIDDEN_TOKENS if t in blob]
    if hits:
        raise ValueError(
            f"LLM 出力に UI 誘発語を検出: {hits}. システム指示を強化しても再発する場合は手書きで上書き推奨。"
        )


def _compose_prompt(parsed: dict) -> str:
    """構造化フィールドを 1 文の英語 prompt に連結する。"""
    return (
        f"{parsed['subject'].strip()} {parsed['action_sequence'].strip()}, "
        f"{parsed['camera'].strip()}, {parsed['mood'].strip()}"
    )


def _call_llm(scene: dict, screenplay: dict | None) -> dict:
    """Anthropic API 呼出 + JSON parse + 検証 + 連結。"""
    import anthropic

    key = config.ANTHROPIC_API_KEY if hasattr(config, "ANTHROPIC_API_KEY") \
        else os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY が未設定。auto_animation_prompt は使用できません。"
        )

    client = anthropic.Anthropic(api_key=key)
    response = client.messages.create(
        model=config.AUTO_ANIMATION_PROMPT_MODEL,
        max_tokens=config.AUTO_ANIMATION_PROMPT_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [{
                "type": "text",
                "text": _build_user_payload(scene, screenplay),
            }],
        }],
    )

    raw = "".join(
        block.text for block in response.content
        if getattr(block, "type", None) == "text"
    )
    cleaned = _strip_json_fence(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error("auto_animation_prompt JSON parse 失敗: %s\nraw=%s", e, raw[:500])
        raise RuntimeError(f"LLM 応答が JSON parse 不能: {e}")

    _validate_structured(parsed)
    composed = _compose_prompt(parsed)

    return {
        "structured": parsed,
        "composed": composed,
        "model": config.AUTO_ANIMATION_PROMPT_MODEL,
    }


# ─────────────────────── 公開 API ───────────────────────


def generate(scene: dict, screenplay: dict | None,
             ts_path: str | None, scene_idx: int,
             force: bool = False) -> dict:
    """シーンの auto animation_prompt を取得する。

    優先順位:
      1. force=False かつ 入力ハッシュ一致するキャッシュがあればそれを返す
      2. LLM を呼出して新規生成、ts_path があればキャッシュに保存

    戻り値: {"structured": {...}, "composed": "<prompt>", "model": "...", "input_hash": "..."}
    """
    sig = _input_signature(scene, screenplay)
    h = _input_hash(sig)

    if not force and ts_path:
        cached = _read_cache(ts_path, scene_idx, h)
        if cached:
            logger.debug("auto_animation_prompt cache hit: scene=%d", scene_idx)
            return cached

    result = _call_llm(scene, screenplay)
    entry = {**result, "input_hash": h}

    if ts_path:
        _write_cache(ts_path, scene_idx, entry)
        logger.info(
            "auto_animation_prompt 生成: scene=%d model=%s",
            scene_idx, result["model"],
        )

    return entry


def get_cached(ts_path: str, scene_idx: int, scene: dict,
               screenplay: dict | None) -> dict | None:
    """キャッシュ命中分のみを返す (LLM は呼ばない)。
    UI で「現状の自動 prompt」を表示するため。"""
    sig = _input_signature(scene, screenplay)
    h = _input_hash(sig)
    return _read_cache(ts_path, scene_idx, h)
