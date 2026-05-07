"""QA 不良サンプルのカテゴリ enum 定義。

UI の reject ボタンで選択させるタグ + DB `qa_failures.tags` に書き込む値の
SSOT。Phase 2 の validator スイートが auto_flagged で書き込むタグも同じ集合
を共有する (= 人手 reject と自動検出が同じ軸で並ぶようにする)。
"""
from __future__ import annotations

# 5 軸: visual / audio / lipsync / subtitle / story。各軸 2-4 タグ。
# 新タグを足す場合は frontend の reject モーダルにも追加すること。
QA_FAILURE_TAGS: tuple[str, ...] = (
    # visual
    "character_drift",
    "storyboard_layout",
    "composition_off",
    "subtitle_zone_blocked",
    # audio
    "audio_silence",
    "audio_clipping",
    "audio_mispronounce",
    "audio_wrong_emotion",
    # lipsync
    "lipsync_mouth_off",
    "lipsync_no_movement",
    "lipsync_timing_off",
    # subtitle
    "subtitle_overlap_subject",
    "subtitle_off_screen",
    "subtitle_too_long",
    # story
    "story_pacing_off",
    "story_hook_weak",
)

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
