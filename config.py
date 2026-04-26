import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
FAL_API_KEY = os.getenv("FAL_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 60

LANGUAGE = "ja"
FONT_PATH = "/System/Library/Fonts/ヒラギノ角ゴシック W7.ttc"
FONT_SIZE = 78
FONT_BORDER_WIDTH = 6

TITLE_BAR_COLOR = "#FFE135"
TITLE_TEXT_COLOR = "#000000"
TITLE_FONT_SIZE = 74
TITLE_BAR_Y = 110
TITLE_BAR_PADDING_X = 76
TITLE_BAR_PADDING_Y = 24
TITLE_LINE_GAP = 18

TIME_FONT_SIZE = 160
TIME_TEXT_COLOR = "#FFFFFF"
TIME_BORDER_COLOR = "#000000"
TIME_BORDER_WIDTH = 12
TIME_Y_FROM_BOTTOM = 660

LABEL_FONT_SIZE = 110
LABEL_Y_FROM_BOTTOM = 410

SUBTITLE_FONT_SIZE = 76
SUBTITLE_Y_FROM_BOTTOM = 950
SUBTITLE_LINE_GAP = 14

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
# True なら tts_full.mp3 内の TTS_MAX_SILENCE_MS を超える無音を圧縮
# silence_after_ms (per-line) の自然音声抽出最大値もこの値で決まる
TTS_TRIM_LONG_SILENCES = True
TTS_MAX_SILENCE_MS = 250                # この長さまでの無音は残し、超過分はカット
TTS_SILENCE_THRESHOLD_DB = -40.0        # この音量以下を無音と判定

EMOTION_VOICE_PRESETS: dict[str, dict] = {
    # 驚き: style高め=陽キャ的になりがちなので低めに、stabilityも上げて短い"はっ!"を表現
    "驚き":   {"stability": 0.45, "style": 0.35, "similarity_boost": 0.75, "rate_pct": 8},
    "喜び":   {"stability": 0.35, "style": 0.5,  "similarity_boost": 0.75, "rate_pct": 5},
    "焦り":   {"stability": 0.25, "style": 0.55, "similarity_boost": 0.75, "rate_pct": 15},
    "落胆":   {"stability": 0.6,  "style": 0.2,  "similarity_boost": 0.8,  "rate_pct": -5},
    "中立":   {"stability": 0.5,  "style": 0.3,  "similarity_boost": 0.75, "rate_pct": 0},
    "満足":   {"stability": 0.45, "style": 0.4,  "similarity_boost": 0.75, "rate_pct": 0},
    "困惑":   {"stability": 0.55, "style": 0.3,  "similarity_boost": 0.75, "rate_pct": -3},
    "怒り":   {"stability": 0.3,  "style": 0.6,  "similarity_boost": 0.75, "rate_pct": 5},
    "恥ずかしさ": {"stability": 0.55, "style": 0.3, "similarity_boost": 0.8, "rate_pct": -5},
}

EMOTION_MOTION_ADDONS: dict[str, str] = {
    "驚き": "sudden eye widening, quick startled motion",
    "喜び": "bright relaxed joyful movement",
    "焦り": "quick nervous motion, restless gestures",
    "落胆": "slow downcast motion, slight shoulder drop",
    "満足": "warm relaxed posture, gentle smile",
    "困惑": "subtle head tilt, uncertain pause",
    "怒り": "firm assertive posture, sharp gaze",
    "恥ずかしさ": "softened shy gesture, slight look away",
}

# eleven_v3 audio tags (公式サポートの英語タグ)
# 各 emotion のlineに自動付与する。EMOTION_AUDIO_TAGS_ENABLED=False で無効化可
EMOTION_AUDIO_TAGS_ENABLED = True
EMOTION_AUDIO_TAGS: dict[str, list[str]] = {
    "驚き":     ["surprised"],
    "喜び":     ["happy"],
    "焦り":     ["nervously", "rushed"],
    "落胆":     ["sad", "sighs"],
    "中立":     [],
    "満足":     ["satisfied"],
    "困惑":     ["confused"],
    "怒り":     ["angry"],
    "恥ずかしさ": ["shyly"],
}

# Intensity 修飾子: emotion preset の値に加算/減算する補正
# 軽め=控えめ表現、強め=演技がかった表現
EMOTION_INTENSITY_MULTIPLIERS: dict[str, dict] = {
    "soft":   {"stability": +0.15, "style": -0.15, "rate_pct": 0},
    "normal": {"stability": 0.0,   "style": 0.0,   "rate_pct": 0},
    "strong": {"stability": -0.15, "style": +0.20, "rate_pct": +3},
}

# UI ヘルパー: audio_tagsの候補一覧
AVAILABLE_AUDIO_TAGS = [
    # 笑い・声色
    "laughs", "chuckles", "giggles",
    # ため息・呼吸
    "sighs", "gasps", "exhales", "breathes",
    # 静かさ・大きさ
    "whispers", "shouts", "yells",
    # 感情
    "excited", "happy", "sad", "angry", "surprised", "confused",
    "nervously", "confidently", "shyly", "satisfied",
    # 速度
    "rushed", "slowly",
    # その他
    "crying", "sobbing", "mischievously", "sarcastically",
]

WPM_BASELINE = 280
WPM_RATE_GAIN = 0.0011
WPM_RATE_BOUND_PCT = 25

PITCH_TREND_STYLE_DELTA = {
    "rising": 0.10,
    "falling": -0.05,
    "flat": 0.0,
}

RMS_VOLUME_QUIET_THRESHOLD = 0.30
RMS_VOLUME_LOUD_THRESHOLD = 0.55
RMS_VOLUME_QUIET_DB = -6.0
RMS_VOLUME_LOUD_DB = 3.0

DELIVERY_TAG_FORMAT = "[{delivery}] {text}"
DELIVERY_TAG_ENABLED = True

# TTSの文中に挿入される長すぎる無音を圧縮する後処理
TTS_TRIM_INTERNAL_PAUSES = True
TTS_PAUSE_THRESHOLD_DB = -35.0  # これより小さい音を「無音」と判定
TTS_PAUSE_KEEP_MS = 70          # 圧縮後に残す無音の長さ (短いほど詰まる)
TTS_TEMPO_MULTIPLIER = 1.0      # 1.0 で無効。1.05 で5%早回し (微妙にテンポ向上)

# ElevenLabs Voice Library から「Language: Japanese」で絞り込み、
# 試聴 → "Add to my voices" した上で voice_id を取得して登録する。
VOICE_LIBRARY: list[dict] = [
    {
        "voice_id": "0ptCJp0xgdabdcpVtCB5",
        "name": "日本語ネイティブ女性",
        "gender": "female",
        "age": "adult",
        "language": "ja",
    },
]

BGM_DEFAULT_VOLUME_DB = -18.0
BREATH_DEFAULT_DURATION = 0.25

SCENE_MIN_DURATION = 3.0
SCENE_TTS_TAIL_BUFFER = 0.3
SCENE_TTS_NATURAL_GAP = 0.3
TEMPO_MAX_AS_WARNING_ONLY = True
TEMPO_MAX_NO_LINES = 3.0
TEMPO_MAX_SINGLE_LINE = 3.5
TEMPO_MAX_MULTI_LINE = 5.0
TEMPO_MAX_LONG_TEXT = 7.0
TEMPO_TEXT_MEDIUM_THRESHOLD = 25
TEMPO_TEXT_LONG_THRESHOLD = 50

ACTION_FRONTLOAD_RATIO = 0.7
ACTION_IDLE_THRESHOLD = 0.005
ACTION_IDLE_MIN_DURATION = 0.3

LIPSYNC_ENABLED = os.getenv("LIPSYNC_ENABLED", "true").lower() == "true"
LIPSYNC_PROVIDER = os.getenv("LIPSYNC_PROVIDER", "fal-sync")
LIPSYNC_MODEL = os.getenv("LIPSYNC_MODEL", "lipsync-1.9.0-beta")
LIPSYNC_SYNC_MODE = os.getenv("LIPSYNC_SYNC_MODE", "cut_off")
LIPSYNC_COST_PER_SECOND = 0.05

MIN_SEGMENT_CHARS = 15
MAX_MERGED_CHARS_PER_GROUP = 105

BASE_DIR = os.path.dirname(__file__)
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
TEMP_DIR = os.path.join(BASE_DIR, "temp")
SCREENPLAYS_DIR = os.path.join(BASE_DIR, "screenplays")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
POST_CAPTIONS_DIR = os.path.join(BASE_DIR, "post_captions")
CHARACTERS_DIR = os.path.join(BASE_DIR, "characters")
DEFAULT_CHARACTER_REFS: list[str] = ["female_engineer"]
JOBS_DIR = os.path.join(REPORTS_DIR, "jobs")
COST_HISTORY_PATH = os.path.join(REPORTS_DIR, "cost_history.jsonl")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE")
