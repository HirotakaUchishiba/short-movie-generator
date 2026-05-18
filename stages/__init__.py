# stages パッケージ — scene_gen.py から段階的に切り出した pure helper 群。
#
# 進行状況 (= 2026-05-19 時点):
#   ✓ stages/audio_helpers.py    — ffmpeg / silence / TTS speed helpers
#                                  (= extract / concat / silencedetect /
#                                  silenceremove / atempo / split_global_speed /
#                                  full_screenplay_voice_settings /
#                                  trim_internal_pauses)
#   ✓ stages/character_refs.py   — resolve_character_refs
#   ✓ stages/emotion.py          — dominant_emotion / emotion_arc_en /
#                                  emotion_arc_summary / dominant_visual_cues
#   ✓ stages/ffmpeg_helpers.py   — get_duration / apply_volume / trim_video /
#                                  extend_video_to_duration / replace_audio
#   ✓ stages/image_helpers.py    — prepare_background (PIL リサイズ)
#   ✓ stages/prompts.py          — augment_animation_prompt
#   ✓ stages/text_mapping.py     — resolve_inline_tag / build_screenplay_text /
#                                  build_position_to_time_map /
#                                  find_line_time_range
#   ✓ stages/text_utils.py       — clean_text / apply_pronunciation_hints /
#                                  load_global_furigana_dict / neighbor_line_text
#
# scene_gen.py に残るのは scene-aware (= dict / metadata を引きずる) な
# 大型 helper:
#   - _build_scene_audio (TTS multi-input concat)
#   - _extract_line_audio_segment (test の monkeypatch 都合で scene_gen 内固定)
#   - _build_audios_from_{full,per_voice} (= TTS dispatcher)
#   - _kling_for_scene / _scene_video_for_scene (= Stage 4 / 5 orchestrator)
#   - _generate_background_with_retry / _generate_single_background
#   - bg_scan_cache / bg_commit_cache / bg_generate_fresh + kling 系
# これらは routes/stage_cache.py / staged_pipeline から呼ばれる **公開 API**
# としての性質も持つため、pure helper 抽出ではなく scene_gen 内の整理対象。
#
# 移行原則:
#   - scene_gen.py の公開 API シグネチャは一切変えない。internal な
#     `_` プレフィックス helper だけが移動対象。
#   - 移行後は scene_gen.py 内に shim (= 1 行 delegate) を残し、test の
#     monkeypatch 互換を保つ。
#   - 各 stage 移行で 1768+ tests 全 pass を維持。
#
# 参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.1.1
