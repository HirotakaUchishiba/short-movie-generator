"""QA 不良サンプルのカテゴリ enum 定義。

UI の reject ボタンで選択させるタグ + DB `qa_failures.tags` に書き込む値の
**SSOT (single source of truth)**。tag string / label / axis の 3 つ組をここで
保持し、frontend は ``GET /api/config/qa-tags`` 経由で取得する (= `qaCategories.ts`
の二重管理を解消)。Phase 2 の validator スイートが auto_flagged で書き込むタグも
同じ集合を共有する (= 人手 reject と自動検出が同じ軸で並ぶようにする)。
"""
from __future__ import annotations

from typing import TypedDict


class QaFailureTagDef(TypedDict):
    """1 つの QA failure tag の表示 / 分類メタ。"""
    tag: str
    label: str
    axis: str


# 5 軸: visual / audio / lipsync / subtitle / story。
# 新タグはここに 1 行足すだけで backend / frontend / DB 列挙すべてに反映される。
QA_FAILURE_TAG_DEFS: tuple[QaFailureTagDef, ...] = (
    # visual
    {"tag": "character_drift", "label": "キャラ崩壊", "axis": "visual"},
    {"tag": "storyboard_layout", "label": "漫画風コマ割り", "axis": "visual"},
    {"tag": "composition_off", "label": "構図ずれ", "axis": "visual"},
    {"tag": "subtitle_zone_blocked",
     "label": "字幕領域に被写体侵入", "axis": "visual"},
    # audio
    {"tag": "audio_silence", "label": "無音 / 音量不足", "axis": "audio"},
    {"tag": "audio_clipping", "label": "音割れ / clipping", "axis": "audio"},
    {"tag": "audio_mispronounce", "label": "誤読 / 発音ミス", "axis": "audio"},
    {"tag": "audio_wrong_emotion",
     "label": "感情の付け方が違う", "axis": "audio"},
    # lipsync
    {"tag": "lipsync_mouth_off",
     "label": "口の動きが合わない", "axis": "lipsync"},
    {"tag": "lipsync_no_movement", "label": "口が動かない", "axis": "lipsync"},
    {"tag": "lipsync_timing_off",
     "label": "リップシンク timing ずれ", "axis": "lipsync"},
    # subtitle
    {"tag": "subtitle_overlap_subject",
     "label": "字幕が被写体に被る", "axis": "subtitle"},
    {"tag": "subtitle_off_screen", "label": "字幕が画面外", "axis": "subtitle"},
    {"tag": "subtitle_too_long",
     "label": "字幕が長すぎる", "axis": "subtitle"},
    # story
    {"tag": "story_pacing_off", "label": "テンポが悪い", "axis": "story"},
    {"tag": "story_hook_weak", "label": "hook が弱い", "axis": "story"},
)

QA_AXIS_LABELS: dict[str, str] = {
    "visual": "ビジュアル",
    "audio": "音声",
    "lipsync": "リップシンク",
    "subtitle": "字幕",
    "story": "ストーリー",
}

# `QA_FAILURE_TAG_DEFS` から導出 (= 後方互換 + 高速 validate)。
QA_FAILURE_TAGS: tuple[str, ...] = tuple(d["tag"] for d in QA_FAILURE_TAG_DEFS)

# qa_failures.source の取りうる値:
#   - human_reject:           UI の reject ボタンで人手記録
#   - auto_flagged:           Phase 1+ の validator が自動検出
#   - regenerate_implicit:    UI / CLI の regenerate 直前に前世代を暗黙アーカイブ
#   - post_publish_lowperf:   Phase 3 で公開後メトリクスから低成績フラグ
QA_FAILURE_SOURCES: tuple[str, ...] = (
    "human_reject",
    "auto_flagged",
    "regenerate_implicit",
    "post_publish_lowperf",
)


def validate_tags(tags: list[str]) -> None:
    """tags 内の不正値を ValueError で reject する (= 空 list は許容)。"""
    for t in tags:
        if t not in QA_FAILURE_TAGS:
            raise ValueError(
                f"unknown qa_failure tag: {t!r} "
                f"(valid: {QA_FAILURE_TAGS})",
            )


def validate_source(source: str) -> None:
    if source not in QA_FAILURE_SOURCES:
        raise ValueError(
            f"unknown qa_failure source: {source!r} "
            f"(valid: {QA_FAILURE_SOURCES})",
        )
