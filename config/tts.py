"""TTS 関連の固定設定 (= ElevenLabs voice / 速度 / 無音圧縮)。

EMOTION_* / DELIVERY_* / AVAILABLE_AUDIO_TAGS 系は将来 PR で本モジュールに
段階移行する (= 計画書 §3.1.4-b)。

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.1.4
"""

ELEVENLABS_VOICE_ID = "0ptCJp0xgdabdcpVtCB5"
ELEVENLABS_VOICE_STABILITY = 0.5
ELEVENLABS_VOICE_SIMILARITY_BOOST = 0.75
ELEVENLABS_VOICE_STYLE = 0.3

# TTS全体の速度倍率 (0.5x〜2.0x)。
# 0.7〜1.2 までは ElevenLabs の native speed パラメータを使用。
# それ以外の範囲は ffmpeg atempo で後処理して合計速度を達成。
TTS_GLOBAL_SPEED = 1.0
TTS_NATIVE_SPEED_MIN = 0.7  # ElevenLabs公式下限
TTS_NATIVE_SPEED_MAX = 1.2  # ElevenLabs公式上限

# 長い無音を圧縮する後処理 (ElevenLabsが文間に挿入する間を切り詰める)
# True なら tts_full.mp3 内の TTS_MAX_SILENCE_MS を超える無音を圧縮。
# 値は per-line audio 末尾の自然な余白秒数にも使われる (= 全 line 共通)
TTS_TRIM_LONG_SILENCES = True
TTS_MAX_SILENCE_MS = 250  # この長さまでの無音は残し、超過分はカット
TTS_SILENCE_THRESHOLD_DB = -40.0  # この音量以下を無音と判定
# char_ts (eleven_v3 の文字タイムスタンプ) は感情タグ [happy] 等の分だけ実音声
# より後ろにズレる (実測で最大 ~0.4s)。line 境界を直前の無音明けへ後退 snap する
# 際の探索許容幅。tag のズレを吸収できるよう広めに取る (= 0.2 では頭切れが残った)。
TTS_SNAP_TOLERANCE_SEC = 0.5
