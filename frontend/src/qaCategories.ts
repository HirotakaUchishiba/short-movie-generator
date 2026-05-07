// QA failure tags の表示メタ。バックエンド `qa/categories.py` の
// `QA_FAILURE_TAGS` と同期させること (= 列挙の追加 / 削除は両側で行う)。
import type { QaFailureTag } from "./types";

export type QaAxis = "visual" | "audio" | "lipsync" | "subtitle" | "story";

export interface QaFailureTagDef {
  tag: QaFailureTag;
  label: string;
  axis: QaAxis;
}

export const QA_FAILURE_TAG_DEFS: QaFailureTagDef[] = [
  { tag: "character_drift", label: "キャラ崩壊", axis: "visual" },
  { tag: "storyboard_layout", label: "漫画風コマ割り", axis: "visual" },
  { tag: "composition_off", label: "構図ずれ", axis: "visual" },
  {
    tag: "subtitle_zone_blocked",
    label: "字幕領域に被写体侵入",
    axis: "visual",
  },
  { tag: "audio_silence", label: "無音 / 音量不足", axis: "audio" },
  { tag: "audio_clipping", label: "音割れ / clipping", axis: "audio" },
  { tag: "audio_mispronounce", label: "誤読 / 発音ミス", axis: "audio" },
  { tag: "audio_wrong_emotion", label: "感情の付け方が違う", axis: "audio" },
  { tag: "lipsync_mouth_off", label: "口の動きが合わない", axis: "lipsync" },
  { tag: "lipsync_no_movement", label: "口が動かない", axis: "lipsync" },
  {
    tag: "lipsync_timing_off",
    label: "リップシンク timing ずれ",
    axis: "lipsync",
  },
  {
    tag: "subtitle_overlap_subject",
    label: "字幕が被写体に被る",
    axis: "subtitle",
  },
  { tag: "subtitle_off_screen", label: "字幕が画面外", axis: "subtitle" },
  { tag: "subtitle_too_long", label: "字幕が長すぎる", axis: "subtitle" },
  { tag: "story_pacing_off", label: "テンポが悪い", axis: "story" },
  { tag: "story_hook_weak", label: "hook が弱い", axis: "story" },
];

export const QA_AXIS_LABELS: Record<QaAxis, string> = {
  visual: "ビジュアル",
  audio: "音声",
  lipsync: "リップシンク",
  subtitle: "字幕",
  story: "ストーリー",
};
