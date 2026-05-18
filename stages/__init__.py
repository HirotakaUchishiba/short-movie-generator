# stages パッケージ — scene_gen.py を per-stage に分割するための受け皿。
#
# 進行状況 (= 2026-05-18 時点):
#   ✓ stages/text_utils.py — clean_text / apply_pronunciation_hints
#   ✓ stages/emotion.py — dominant_emotion / emotion_arc_en / emotion_arc_summary
#                          / dominant_visual_cues
#
# 残 (= scene_gen.py 内に直書きされたまま、2683 行):
#   TODO stages/prompts.py — _build_background_prompt / _augment_animation_prompt
#   TODO stages/bg.py — _scene_bg_inputs / _build_bg_cache_meta /
#                        generate_backgrounds + per-scene helpers (= ~250 行)
#   TODO stages/kling.py — _generate_kling + cache management (= ~200 行)
#   TODO stages/audio.py — _build_audios_from_full / _build_audios_from_per_voice
#                          + _extract_line_audio_segment (= ~400 行)
#   TODO stages/scene_compose.py — Stage 5 音声合成・lipsync 経路 (= ~300 行)
#
# 移行原則:
#   - scene_gen.py の **公開 API シグネチャ (= staged_pipeline 経由で呼ばれる
#     もの)** は一切変えない。internal な `_` プレフィックス helper を移動。
#   - 移行後は scene_gen.py 内に 1 行の shim (= `def _x(...): return y.x(...)`)
#     を残し、shim 経由で呼ばれるテスト互換を保つ。
#   - 各 stage 移行で全 pytest pass を維持 (= 1737+ 件)。
#
# 参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.1.1
