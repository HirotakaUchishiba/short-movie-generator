"""accept された novel intent 候補から visual_intents.yaml に貼り付ける snippet を生成する。

設計 doc: docs/plannings/2026-05-10_intent-suggestion-flow.md §3.1

不変条件: **すべての必須フィールドを埋めるところまで自動化しない**。粒度判断は
人間に委ねる (= TODO コメントで明示)。snippet は「貼り付ければ valid yaml になるが
そのままでは pool_target を満たさない」状態で出力する。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analyze.suggestion_store import IntentSuggestionRecord


_MOTION_KEYWORDS_HIGH = (
    "rapid", "frantic", "fast", "violent", "shouting", "running",
    "暴れ", "走", "急", "焦",
)
_MOTION_KEYWORDS_MEDIUM = (
    "gestur", "pointing", "talking", "explaining", "moving",
    "指差", "手振り", "歩",
)


def _guess_motion_intensity(rationale: str, description: str) -> str:
    """rationale + description から motion_intensity を heuristic 推定。

    既定は ``medium`` (= 失敗時のフォールバック)。視聴者から見て動きの量を
    判断するための簡易ルールで、運用者が yaml に貼り付けた後に必ず手で
    調整する前提。
    """

    text = (rationale + " " + description).lower()
    for kw in _MOTION_KEYWORDS_HIGH:
        if kw in text:
            return "high"
    for kw in _MOTION_KEYWORDS_MEDIUM:
        if kw in text:
            return "medium"
    return "low"


def _summarize_rationale(rationale: str, max_lines: int = 2) -> str:
    """rationale を 1-2 行に圧縮 (= description フィールド向け)。"""

    if not rationale:
        return "(rationale なし — 運用者が記述してください)"
    # 改行 / 複数空白を 1 つにまとめる
    flat = re.sub(r"\s+", " ", rationale.strip())
    # 句読点単位で軽く分割
    parts = re.split(r"[。．.！!？?]", flat)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return flat[:120]
    selected = parts[:max_lines]
    return "\n    ".join(selected)


def _normalize_yaml_id(proposed_id: str) -> str:
    """``proposed_<garbage>`` の prefix を剥がして短縮した暫定 id を返す。

    detect_novel_intent_candidates が描画する `proposed_` prefix は内部用なので、
    yaml entry に貼る時は外す (= 運用者が手で TODO リネームする想定)。
    """

    s = proposed_id
    if s.startswith("proposed_"):
        s = s[len("proposed_"):]
    # snake_case で残す
    s = re.sub(r"[^a-z0-9_]", "_", s.lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "TODO_RENAME_ME"


def render_yaml_snippet(record: "IntentSuggestionRecord") -> str:
    """1 entry を visual_intents.yaml に貼り付け可能な YAML snippet にする。

    出力例 (= 設計 doc §3.1):

      - id: frantic_typing_at_desk  # TODO: 適切なリネームを検討
        description: |
          subject types furiously at the laptop
        suggested_kling_template: |
          # TODO: 運用者が記述
          A {character} {pose_modifier} in {location_decor},
          {start_emotion_addon}, ...
        duration_buckets: [5, 10]   # 推定値、要調整
        valid_start_emotions: []    # TODO: 要記述
        motion_intensity_bucket: medium  # rationale から推定 (= 要確認)
        pool_target_size: 8
        compatible_with: []
        deprecated: false
    """

    yid = _normalize_yaml_id(record.proposed_id)
    desc = _summarize_rationale(record.rationale or record.description)
    motion = _guess_motion_intensity(record.rationale, record.description)
    return (
        f"- id: {yid}  # TODO: 適切なリネームを検討\n"
        f"  description: |\n"
        f"    {desc}\n"
        f"  suggested_kling_template: |\n"
        f"    # TODO: 運用者が記述\n"
        f"    A {{character}} {{pose_modifier}} in {{location_decor}},\n"
        f"    {{start_emotion_addon}}, ...\n"
        f"  duration_buckets: [5, 10]   # 推定値、要調整\n"
        f"  valid_start_emotions: []    # TODO: 要記述\n"
        f"  motion_intensity_bucket: {motion}  # rationale から推定 (= 要確認)\n"
        f"  pool_target_size: 8\n"
        f"  compatible_with: []\n"
        f"  deprecated: false\n"
    )
