"""Claude が抽出した抽象台本を Gemini で言い換える (= 翻案権配慮)。

設計 doc: docs/plannings/2026-05-17_gemini-dialogue-rewrite.md

analyze pipeline の `claude` phase 完了直後、`save` phase 直前に呼ばれる。
入力 screenplay の `line.text` と `caption` だけを「同じ意味・同じ感情・
独自の言い回し」で書き換え、構造 / メタ field は一切触らない。

失敗時 (= API error / 構造変化 / 文字数比率超過) は graceful に Claude
original にフォールバックする (= rewrite は付加価値、analyze 全体は止めない)。
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import config

logger = logging.getLogger(__name__)

MODEL_ID = os.getenv("GEMINI_REWRITE_MODEL", "gemini-2.5-pro")
REQUEST_TIMEOUT_SEC = 120
MAX_RETRIES = 2
BACKOFF_SECONDS = (5, 15)
TEMPERATURE = 0.7

# line.text と原文の文字数比率がこの範囲外なら該当 line のみ original に戻す
# (= TTS 尺崩壊防止、±20%)
LENGTH_RATIO_MIN = 0.8
LENGTH_RATIO_MAX = 1.2

# validator が拒否する半角句読点 (= ScreenplayValidator と一致)
FORBIDDEN_ASCII_PUNCT = {",", "."}

# rewrite phase の kill switch (= env var で off できる)
ENABLED_ENV_VAR = "ANALYZE_DIALOGUE_REWRITE_ENABLED"

# 出力 status の列挙
RewriteStatus = Literal["success", "partial", "skipped", "error"]


@dataclass
class RewriteResult:
    """rewrite phase の結果。

    Fields:
      status: "success" / "partial" / "skipped" / "error"
        - success: 全 line + caption が正常 rewrite
        - partial: 一部 line が per-line fallback で original
        - skipped: API key 不在 / kill switch / structure mismatch 等で全 original
        - error: 予期しない例外 (= 呼出元で warn ログ、original 採用)
      screenplay: rewrite 後 (= status=="success"/"partial") または Claude original
        (= status=="skipped"/"error") の screenplay。常に caller に返せる
        形になっている (= 呼出元はこの screenplay をそのまま save できる)
      reason: skipped / error の理由 (audit 用)
      input_tokens / output_tokens: cost 記録用 (skipped / error なら 0)
      per_line_fallback_count: partial のとき何 line が original に戻ったか
    """

    status: RewriteStatus
    screenplay: dict
    reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    per_line_fallback_count: int = 0
    fallback_indices: tuple[tuple[int, int], ...] = field(default_factory=tuple)


def _enabled_from_env() -> bool:
    """env var で kill-switch されていないか確認。"""

    raw = os.getenv(ENABLED_ENV_VAR, "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _collect_lines_flat(sp: dict) -> list[tuple[int, int, str]]:
    """screenplay から (scene_idx, line_idx, text) を flatten で集める。"""

    out: list[tuple[int, int, str]] = []
    for s_idx, scene in enumerate(sp.get("scenes") or []):
        for l_idx, line in enumerate(scene.get("lines") or []):
            text = line.get("text")
            if isinstance(text, str):
                out.append((s_idx, l_idx, text))
    return out


def _build_prompt(sp: dict) -> str:
    """Gemini に渡す instruction + 入力 screenplay JSON。"""

    lines_flat = _collect_lines_flat(sp)
    if not lines_flat:
        return ""

    # 入力データを flatten 形式で送る (= scene/line 構造はメタとして示す)
    lines_payload = [
        {"scene_idx": s, "line_idx": l, "text": t}
        for s, l, t in lines_flat
    ]
    caption = sp.get("caption", "")

    return (
        "あなたは台本リライト専門のエディタです。\n"
        "他者の動画から抽出されたセリフを、意味と感情を保ったまま、\n"
        "独自の言い回しで書き直してください。\n\n"
        "# ルール\n"
        "1. 各 line の `text` を別の言い回しで書き換える (= 同じ意味、同じ\n"
        "   感情)。意訳・要約はしない\n"
        f"2. 各 line の文字数は元の **±20% 以内** (= {LENGTH_RATIO_MIN}〜"
        f"{LENGTH_RATIO_MAX} 倍)\n"
        "3. ASCII の `,` と `.` は使わない (= 全角句読点を使う)\n"
        "4. caption も同じ方針で書き換える (= ハッシュタグはそのまま維持か\n"
        "   等価な日本語タグに置換可)\n"
        "5. line の順序・件数は **絶対に変えない** (= 入力と同じ並びで返す)\n"
        "6. 各 line の scene_idx / line_idx は **入力と同じ** で返す (= 識別用)\n\n"
        "# 出力形式 (= JSON、コードブロックは不要)\n"
        "{\n"
        '  "caption": "<rewritten caption>",\n'
        '  "lines": [\n'
        '    {"scene_idx": 0, "line_idx": 0, "text": "<rewritten>"},\n'
        "    ...\n"
        "  ]\n"
        "}\n\n"
        f"# 入力 caption\n{caption}\n\n"
        "# 入力 lines (= 順序保持で返すこと)\n"
        f"{json.dumps(lines_payload, ensure_ascii=False, indent=2)}\n"
    )


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_json_fence(text: str) -> str:
    """Gemini が ```json ... ``` で囲んできた場合に剥がす。"""

    return _JSON_FENCE_RE.sub("", text).strip()


def _extract_json_object(text: str) -> dict | None:
    """text から JSON object を抽出。失敗なら None。"""

    cleaned = _strip_json_fence(text)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # fallback: 最初の { から最後の } までを slice して再 parse
    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if first >= 0 and last > first:
        try:
            parsed = json.loads(cleaned[first:last + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _validate_text(rewritten: str, original: str) -> str | None:
    """rewrite された text を検査。問題があれば理由を返す、OK なら None。

    - 空文字 / non-str → reject
    - 半角 , / . を含む → reject (= validator 違反)
    - 文字数比率が ±20% 外 → reject
    """

    if not isinstance(rewritten, str) or not rewritten.strip():
        return "empty"
    if any(ch in rewritten for ch in FORBIDDEN_ASCII_PUNCT):
        return "forbidden_ascii_punct"
    if not original:
        return None
    ratio = len(rewritten) / len(original)
    if ratio < LENGTH_RATIO_MIN or ratio > LENGTH_RATIO_MAX:
        return f"length_ratio={ratio:.2f}"
    return None


def _validate_caption(rewritten: str, original: str) -> str | None:
    """caption は文字数チェック緩め (= ±50%、ハッシュタグの増減が許容範囲)。

    ASCII , . 禁止は line と同じく必須。
    """

    if not isinstance(rewritten, str) or not rewritten.strip():
        return "empty"
    if any(ch in rewritten for ch in FORBIDDEN_ASCII_PUNCT):
        return "forbidden_ascii_punct"
    if not original:
        return None
    ratio = len(rewritten) / len(original)
    if ratio < 0.5 or ratio > 1.5:
        return f"length_ratio={ratio:.2f}"
    return None


def _call_gemini(prompt: str) -> tuple[str, int, int]:
    """Gemini API を呼び、(text, input_tokens, output_tokens) を返す。

    SDK 例外はそのまま raise (= 呼出元で retry / fallback 判断)。
    """

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GOOGLE_API_KEY)
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT"],
            temperature=TEMPERATURE,
            http_options=types.HttpOptions(
                timeout=REQUEST_TIMEOUT_SEC * 1000,
            ),
        ),
    )
    text = response.text or ""
    usage = getattr(response, "usage_metadata", None)
    input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
    return text, input_tokens, output_tokens


def _apply_rewrites(
    sp: dict,
    rewrite: dict,
    lines_flat: list[tuple[int, int, str]],
) -> tuple[dict, int, list[tuple[int, int]]]:
    """rewrite payload を sp に適用。original deep copy 上で破壊する。

    Returns:
      (new_sp, fallback_count, fallback_indices)
      fallback_indices は per-line fallback された (scene_idx, line_idx) tuple list。
    """

    new_sp = copy.deepcopy(sp)

    # caption
    new_caption_raw = rewrite.get("caption")
    original_caption = sp.get("caption", "")
    if isinstance(new_caption_raw, str):
        why = _validate_caption(new_caption_raw, original_caption)
        if why is None:
            new_sp["caption"] = new_caption_raw
        else:
            logger.warning(
                "[rewrite] caption fallback to original (reason=%s)", why,
            )
    else:
        logger.warning("[rewrite] caption が str でない → original 維持")

    # lines: payload を (scene_idx, line_idx) で lookup できる dict 化
    payload_lines = rewrite.get("lines")
    if not isinstance(payload_lines, list):
        return new_sp, len(lines_flat), [
            (s, l) for s, l, _ in lines_flat
        ]

    payload_map: dict[tuple[int, int], str] = {}
    for entry in payload_lines:
        if not isinstance(entry, dict):
            continue
        s = entry.get("scene_idx")
        l = entry.get("line_idx")
        t = entry.get("text")
        if (isinstance(s, int) and isinstance(l, int)
                and isinstance(t, str)):
            payload_map[(s, l)] = t

    fallback_indices: list[tuple[int, int]] = []
    for s_idx, l_idx, original_text in lines_flat:
        rewritten = payload_map.get((s_idx, l_idx))
        if rewritten is None:
            logger.warning(
                "[rewrite] line (%d,%d) missing in payload → original 維持",
                s_idx, l_idx,
            )
            fallback_indices.append((s_idx, l_idx))
            continue
        why = _validate_text(rewritten, original_text)
        if why is not None:
            logger.warning(
                "[rewrite] line (%d,%d) fallback to original (reason=%s)",
                s_idx, l_idx, why,
            )
            fallback_indices.append((s_idx, l_idx))
            continue
        # OK → 適用
        new_sp["scenes"][s_idx]["lines"][l_idx]["text"] = rewritten

    return new_sp, len(fallback_indices), fallback_indices


def rewrite_screenplay(sp: dict) -> RewriteResult:
    """Claude 出力 screenplay の line.text + caption を Gemini で言い換える。

    必ず ``RewriteResult`` を返す (= 例外を上に投げない)。呼出元は
    ``result.screenplay`` をそのまま save できる (status に応じて
    original or rewritten が入っている)。
    """

    # 1. kill switch
    if not _enabled_from_env():
        return RewriteResult(
            status="skipped", screenplay=sp, reason="disabled_by_env",
        )

    # 2. API key
    api_key = getattr(config, "GOOGLE_API_KEY", None)
    if not api_key:
        return RewriteResult(
            status="skipped", screenplay=sp, reason="no_api_key",
        )

    # 3. 構造抽出
    lines_flat = _collect_lines_flat(sp)
    if not lines_flat and not sp.get("caption"):
        # 書き換える対象が無い
        return RewriteResult(
            status="skipped", screenplay=sp, reason="no_content",
        )

    prompt = _build_prompt(sp)
    if not prompt:
        return RewriteResult(
            status="skipped", screenplay=sp, reason="empty_prompt",
        )

    # 4. API call + retry
    last_err: Exception | None = None
    text = ""
    input_tokens = 0
    output_tokens = 0
    for attempt in range(MAX_RETRIES + 1):
        try:
            text, input_tokens, output_tokens = _call_gemini(prompt)
            break
        except Exception as e:  # noqa: BLE001 — SDK は色々投げる
            last_err = e
            if attempt < MAX_RETRIES:
                wait = BACKOFF_SECONDS[
                    min(attempt, len(BACKOFF_SECONDS) - 1)
                ]
                logger.warning(
                    "[rewrite] Gemini API 失敗 (attempt %d): %s → %ds 後 retry",
                    attempt + 1, str(e)[:120], wait,
                )
                time.sleep(wait)
            else:
                logger.warning(
                    "[rewrite] Gemini API %d 回 retry 後 fail: %s → original 採用",
                    MAX_RETRIES + 1, str(e)[:200],
                )
                return RewriteResult(
                    status="skipped", screenplay=sp,
                    reason=f"api_error: {type(e).__name__}",
                )
    else:
        # for-else は break 無しで到達 (= 上で return 済なので実際には到達しない)
        return RewriteResult(
            status="skipped", screenplay=sp,
            reason=f"api_error: {last_err}",
        )

    # 5. JSON parse
    parsed = _extract_json_object(text)
    if parsed is None:
        logger.warning(
            "[rewrite] Gemini 応答が JSON でなく fallback (head=%s)",
            text[:200],
        )
        return RewriteResult(
            status="skipped", screenplay=sp,
            reason="parse_error", input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    # 6. per-line / caption の検証 + 適用
    new_sp, fallback_count, fallback_indices = _apply_rewrites(
        sp, parsed, lines_flat,
    )

    status: RewriteStatus = "success"
    if fallback_count == len(lines_flat):
        # 全 line fallback (= caption だけ rewrite 成功 or 全 fail) は
        # structure_drift とみなす
        status = "skipped"
        reason = "all_lines_fallback"
        # screenplay は new_sp だが結果的に original と同等
        return RewriteResult(
            status=status, screenplay=sp, reason=reason,
            input_tokens=input_tokens, output_tokens=output_tokens,
            per_line_fallback_count=fallback_count,
            fallback_indices=tuple(fallback_indices),
        )
    elif fallback_count > 0:
        status = "partial"

    logger.info(
        "[rewrite] status=%s rewritten_lines=%d fallback=%d tokens=%d/%d",
        status, len(lines_flat) - fallback_count, fallback_count,
        input_tokens, output_tokens,
    )
    return RewriteResult(
        status=status, screenplay=new_sp, reason="",
        input_tokens=input_tokens, output_tokens=output_tokens,
        per_line_fallback_count=fallback_count,
        fallback_indices=tuple(fallback_indices),
    )
