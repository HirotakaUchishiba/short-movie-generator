# stages パッケージ — scene_gen.py を per-stage に分割するための受け皿。
#
# 段階的移行計画:
#   1. (済)  stages/text_utils.py — text 整形・clean / pronunciation hints
#   2. (TODO) stages/emotion.py — _emotion_arc_* / _dominant_emotion / _dominant_visual_cues
#   3. (TODO) stages/tts.py — generate_tts_for_screenplay / generate_screenplay_tts_one_shot
#   4. (TODO) stages/bg.py — generate_backgrounds + per-scene helpers
#   5. (TODO) stages/kling.py — generate_kling_for_screenplay + cache management
#   6. (TODO) stages/scene_compose.py — Stage 5 の音声合成・lipsync 経路
#
# 移行原則:
#   - scene_gen.py の **公開 API シグネチャ (= staged_pipeline 経由で呼ばれるもの)** は
#     一切変えない。internal な _ プレフィックス helper のみを移動する。
#   - 各 stage 移行で 1214+ 件の pytest 全件 PASS を維持する。
