"""scene_gen.py から text→time mapping 系 helper を切り出した module。

ElevenLabs API が返す char-level timestamps を line.text に対応付けるための
純粋関数群。scene 状態に依存せず、screenplay dict / char_timestamps から
派生する。scene_gen 側は private shim を残して既存 callsite を破壊しない。

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.1.1
"""

from __future__ import annotations

import config

# 半角スペース×2: line間/scene間の区切り。ElevenLabs char_alignment は
# 全 char を返すため、separator は input_text の length に直接寄与する。
SCREENPLAY_TEXT_SEPARATOR = "  "


def resolve_inline_tag(line: dict, _scene: dict, _line_idx: int) -> str:
    """この line に対する ElevenLabs V3 inline tag を解決する。

    優先順位:
      1. line.audio_tags[0] (ユーザー手動指定)
      2. line.emotion → config.EMOTION_AUDIO_TAGS の最初のタグ (自動補完)
      3. なし (タグ無し)
    """
    user_tags = line.get("audio_tags") or []
    if user_tags:
        first = str(user_tags[0]).strip()
        if first:
            return first
    emo = line.get("emotion")
    if emo and getattr(config, "EMOTION_AUDIO_TAGS_ENABLED", True):
        auto = config.EMOTION_AUDIO_TAGS.get(emo, [])
        if auto:
            first = str(auto[0]).strip()
            if first:
                return first
    return ""


def build_screenplay_text(screenplay: dict) -> tuple[str, list[dict]]:
    """全 line.text を半角スペース×2 で連結。

    各 line の char offset を line_specs に記録して返す。
    line.audio_tags / line.emotion 由来の inline tag があれば line.text の
    直前に "[tag] " を挿入する。line_specs.char_start は **発話本文 (text)**
    の先頭位置を指す (タグ部分は char_alignment 上スキップされる前提なので
    マッピングに影響しない)。
    """
    line_specs: list[dict] = []
    text_parts: list[str] = []
    cursor = 0
    for s_idx, scene in enumerate(screenplay["scenes"]):
        for l_idx, line in enumerate(scene.get("lines") or []):
            t = line["text"]
            tag = resolve_inline_tag(line, scene, l_idx)
            prefix = f"[{tag}] " if tag else ""
            if cursor > 0:
                cursor += len(SCREENPLAY_TEXT_SEPARATOR)
            text_parts.append(prefix + t)
            cursor += len(prefix)
            line_specs.append({
                "scene_idx": s_idx,
                "line_idx": l_idx,
                "char_start": cursor,
                "char_end": cursor + len(t),
            })
            cursor += len(t)
    return SCREENPLAY_TEXT_SEPARATOR.join(text_parts), line_specs


def build_position_to_time_map(
    input_text: str, char_timestamps: list[dict],
) -> list[dict | None]:
    """input_text の各文字位置 → {start, end} のマップを構築。

    API が入力 char の一部を返さない / 順序が異なる場合に備えて、順次マッチで
    紐付ける。
    """
    result: list[dict | None] = [None] * len(input_text)
    cursor = 0
    for entry in char_timestamps:
        ch = entry["char"]
        while cursor < len(input_text) and input_text[cursor] != ch:
            cursor += 1
        if cursor < len(input_text):
            result[cursor] = {
                "start": float(entry["start"]),
                "end": float(entry["end"]),
            }
            cursor += 1
    return result


def find_line_time_range(
    pos_to_time: list[dict | None], char_start: int, char_end: int,
) -> tuple[float | None, float | None]:
    """[char_start, char_end) 範囲内で最初/最後の有効 timestamp を探す。"""
    abs_start = None
    for i in range(char_start, min(char_end, len(pos_to_time))):
        if pos_to_time[i]:
            abs_start = pos_to_time[i]["start"]
            break
    abs_end = None
    upper = min(char_end, len(pos_to_time)) - 1
    for i in range(upper, char_start - 1, -1):
        if pos_to_time[i]:
            abs_end = pos_to_time[i]["end"]
            break
    return abs_start, abs_end
