import os

# API key 群は config.api_keys から re-export (= §3.1.4 関心分離の起点)。
# load_dotenv() は api_keys 側で実行される。
from config.api_keys import (  # noqa: F401
    ANTHROPIC_API_KEY,
    ELEVENLABS_API_KEY,
    FAL_API_KEY,
    GOOGLE_API_KEY,
    SYNCSO_API_KEY,
)

# 動画基本表示設定は config.visual から re-export (= §3.1.4-b)。
from config.visual import (  # noqa: F401, E402
    FPS,
    LANGUAGE,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
)
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
# 字幕 1 行の最大文字数。これを超えるテキストは compositor._wrap_subtitle_text で
# 句読点・助詞境界を優先して自動改行される。
# 1080px 幅 + fontsize 76 だと安全に収まるのは ~17 文字。
SUBTITLE_MAX_CHARS_PER_LINE = 17

# 字幕を「短いテロップが次々に切り替わる」TikTok 風表示にする。
# True の場合、各 line.text を SUBTITLE_CHUNK_MAX_CHARS 文字以内の chunks に
# 自動分割し、line.start - line.end の間で文字数比例で時刻を割り当てる。
# False の場合は 1 line = 1 字幕表示 (従来動作)。
#
# MAX_CHARS は「許容上限」であって目標ではない。短いほうが視認しやすいが、
# 「です/ます」のような活用形末尾の途中分断を絶対に避けるため探索余裕が必要。
# 12 文字程度あれば日本語の自然な助詞・句読点境界がほぼ常に見つかる。
SUBTITLE_CHUNK_ENABLED = True
SUBTITLE_CHUNK_MAX_CHARS = 12

# chunk の表示時刻を「文字数比例」でなく TTS char-level timestamp (tts_full.json)
# の実発話時刻ベースで配分する。実音声の非線形な発話分布に字幕が追従する。
# char_ts 不在 / 複数話者 (per-voice) / 読込失敗時は文字数比例に自動 fallback。
SUBTITLE_TIMING_FROM_CHAR_TS = True

# TTS 関連の固定設定は config.tts から re-export (= §3.1.4-b 段階移行)。
from config.tts import (  # noqa: F401, E402
    ELEVENLABS_VOICE_ID,
    ELEVENLABS_VOICE_STABILITY,
    ELEVENLABS_VOICE_SIMILARITY_BOOST,
    ELEVENLABS_VOICE_STYLE,
    TTS_GLOBAL_SPEED,
    TTS_NATIVE_SPEED_MIN,
    TTS_NATIVE_SPEED_MAX,
    TTS_TRIM_LONG_SILENCES,
    TTS_MAX_SILENCE_MS,
    TTS_SILENCE_THRESHOLD_DB,
    TTS_SNAP_TOLERANCE_SEC,
)

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

# 日本語 emotion ラベル → 英語表現 (Imagen / Kling プロンプト合成で使用)。
# arc 表現 (= "驚き → 焦り → 中立") を英語化するための単一辞書。
EMOTION_EN: dict[str, str] = {
    "驚き": "surprise",
    "喜び": "joy",
    "焦り": "urgency",
    "落胆": "disappointment",
    "中立": "neutral",
    "満足": "satisfaction",
    "困惑": "confusion",
    "怒り": "anger",
    "恥ずかしさ": "embarrassment",
}


# Stage 別に出力する dom_cues カテゴリ。
# Imagen (静止画) は照明・トーンに絞り、顔の細部 (= 表情含む) は reference 画像に
# 任せて再解釈による崩壊を抑える。emotion 由来の facial cue を bg prompt に注入
# すると、シーンごとに Imagen が目・しわ・肌質を作り直して同一キャラが別人化
# (老け顔・別の目) するため bg からは除く。表情変化は Kling (動画) 側の facial
# cue が担当する。Kling は動き・視線・体勢など動的要素も含む。
STAGE_CUE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "bg": ("lighting", "tone"),
    "kling": ("motion", "facial", "tone", "eye_gaze", "body_posture", "camera"),
}


# 視覚プロンプト合成用 (Imagen / Kling 両方で使う決定論的cue mapping)。
# scene.lines[].emotion から dominant を求めて lookup → BG/Kling prompt に注入。
# Claude を使わずに line別感情を視覚言語に翻訳する単一の真実源。
#
# 表現方針: **映画的に感情が伝わる程度** に抑える。漫画的・誇張表現は避ける。
# 視聴者に感情が分かるレベルで、かつリアルで自然な範囲。
EMOTION_VISUAL_CUES: dict[str, dict] = {
    "驚き": {
        "lighting": "subtle key light bump, slightly raised contrast",
        "camera": "quick push-in then steady hold",
        "motion": "head pulls back slightly, shoulders tense up, hand may rise toward chest",
        "facial": "eyes widening, eyebrows raised, mouth opening slightly",
        "tone": "caught off guard, alert",
    },
    "喜び": {
        "lighting": "warm soft natural light, gentle backlight",
        "camera": "gentle steady shot with mild push-in",
        "motion": "shoulders relaxed, slight lean forward, natural open hand gestures",
        "facial": "genuine smile, eyes brightening with mild crow's feet at corners",
        "tone": "warm, pleased, naturally cheerful",
    },
    "焦り": {
        "lighting": "slightly cool tones, neutral natural shadows",
        "camera": "subtle handheld with small reframings",
        "motion": "leaning forward, quickened pace, restless hand movements",
        "facial": "alert wide eyes, brows softly raised, mouth gently relaxed (no frowning, no tight jaw)",
        "tone": "lightly hurried, focused but composed",
    },
    "落胆": {
        "lighting": "slightly muted palette, soft directional light",
        "camera": "static frame, gentle slow drift",
        "motion": "shoulders lowering, slow exhale, head tilting down a touch",
        "facial": "downcast eyes, soft frown, lips slightly pursed",
        "tone": "subdued, weighed down",
    },
    "中立": {
        "lighting": "balanced even daylight, neutral white-balanced fill",
        "camera": "static locked-off frame, calm well-composed shot",
        "motion": "still and grounded, minimal natural breathing motion",
        "facial": "calm composed neutral expression, soft eye gaze",
        "tone": "matter-of-fact, observational",
    },
    "満足": {
        "lighting": "warm afternoon light, soft amber tone",
        "camera": "slow tender handheld, gentle pull-back",
        "motion": "relaxed exhale, body settling back, arms uncrossing",
        "facial": "warm soft smile, softened eyelids, mouth corners gently raised",
        "tone": "settled, content, quietly pleased",
    },
    "困惑": {
        "lighting": "soft mixed light with mild ambiguous shadows",
        "camera": "subtle slow push-in then pause, slight off-center framing",
        "motion": "head tilting, hand hovering near chin or temple, brief pause mid-gesture",
        "facial": "knit brow, slight frown, eyes searching",
        "tone": "uncertain, pondering",
    },
    "怒り": {
        "lighting": "slightly cool harsh light, defined shadows",
        "camera": "tighter framing with slight forward dolly",
        "motion": "shoulders squared, more deliberate gestures, jaw set",
        "facial": "narrowed eyes, firm mouth, tightened brow",
        "tone": "irritated, firm, suppressed displeasure",
    },
    "恥ずかしさ": {
        "lighting": "soft warm light, gentle glow",
        "camera": "slight pull-back, mild handheld",
        "motion": "hand rising near face, head ducking slightly, body angling away",
        "facial": "soft blush, gaze averted, awkward small smile",
        "tone": "flustered, sheepish",
    },
}


# Kling V3 が PC やスマホ操作シーンで勝手にチャット UI / 通知ポップアップ /
# テキスト吹き出し / グラフィック等を hallucinate するのを抑止する negative 文。
# scene_gen._augment_animation_prompt で全シーンの prompt 末尾に冪等付加される。
# 台本の animation_prompt に "chat bubble", "notification", "graphic that pops up"
# 等の UI 誘発語を直接書くと打ち消せないので、台本側でも書かないこと。
KLING_NEGATIVE_CONSTRAINT = (
    "no UI overlays, no chat bubbles, no notifications, no on-screen text, "
    "no smartphone popups, no infographics, no floating graphics"
)


# ─────────────────────────────────────────────────────────
# 視覚演出の preset ライブラリ
#
# 各 preset ID → 実テキスト辞書。scene_gen の compose ロジックが
# emotion 由来の dominant cue として参照する。値はすべて preset ID で
# SSOT 厳格 (validator が enum を保証)。
# 拡張は preset を 1 行 config に追加するだけ。
# ─────────────────────────────────────────────────────────

FACIAL_PRESETS: dict[str, str] = {
    # neutral / 平静系
    "neutral": "calm composed neutral expression, soft eye gaze",
    "thoughtful": "slight inward gaze, gentle furrow, hand near chin",
    "focused": "alert focused gaze, mouth gently set, brow neutral",
    "deadpan": "expressionless flat face, blank gaze",
    # 喜び系
    "slight_smile": "warm gentle smile, eyes softened, mouth corners raised",
    "wide_smile": "broad open smile, eyes squinting from joy",
    "satisfied_smile": "warm crinkle-eyed smile, softened eyelids, head slightly back",
    "shy_smile": "small awkward smile, soft blush, gaze averted",
    "knowing_smirk": "subtle one-sided smirk, raised eyebrow",
    "laugh_open": "open-mouth laugh, eyes squeezed shut, head tipped back",
    # 驚き系
    "surprised_mild": "eyes widening, eyebrows raised, mouth opening slightly",
    "surprised_pleasant": "eyes brightening, hand to mouth, parted lips in delight",
    "shocked": "eyes blown wide, jaw dropped, frozen still",
    "alarmed": "wide eyes darting, body tensing back",
    # 焦り / 緊張系
    "alert_focused": "alert wide eyes, brows softly raised, mouth gently relaxed",
    "anxious": "knit brow, alert eyes, slight worry crease",
    "panicked": "wide eyes, tense jaw, brow furrowed in panic",
    "stressed": "tight jaw, eyes darting, slight hand to forehead",
    # 落胆 / 悲しみ系
    "subdued": "downcast eyes, soft frown, lips slightly pursed",
    "deflated": "drooped lids, heavy mouth corners down, hollow gaze",
    "tearful": "wet glistening eyes, trembling lip, brow heavy",
    "wistful": "soft melancholy gaze, faint half-smile, distant eyes",
    # 怒り系
    "annoyed": "narrowed eyes, slight tight mouth, mild brow tension",
    "angry": "narrowed eyes, firm mouth, tightened brow",
    "furious": "deep furrowed brow, clenched jaw, lips showing teeth",
    "cold_glare": "intense direct stare, neutral mouth, frozen jaw",
    # 困惑系
    "confused": "knit brow asymmetrically, lips parted, searching eyes",
    "skeptical": "raised eyebrow, slight squint, lips tightened",
    "puzzled": "head tilted slightly, eyes slowly blinking, lips parted",
    # 羞恥系
    "embarrassed": "averted gaze, soft blush, awkward small smile",
    "flustered": "blush spreading on cheeks, hand near face, half-laugh",
    "shy_glance": "quick glance to side, lashes lowered, faint smile",
    # 寝起き / 疲れ系
    "sleepy": "half-closed lids, relaxed jaw, slow blink",
    "groggy_morning": "tousled state, soft squint, slight yawn",
    "exhausted": "heavy lidded eyes, slack jaw, hollow expression",
    "yawning": "open mouth in yawn, eyes squeezed, hand near mouth",
    # 集中 / 観察系
    "concentrating": "intent focused gaze on screen, slight squint, lips pressed",
    "observing": "eyes tracking carefully, head subtly tilted, neutral mouth",
    "reading": "eyes scanning text, brow slightly knit, neutral mouth",
    # 喜び/驚きの混合
    "delighted_surprise": "wide bright smile, eyes lighting up, hand near mouth",
    "warm_relief": "soft smile, exhaled relief, eyes softening",
    # その他
    "determined": "set jaw, focused eyes, slight forward lean to face",
    "contemplative": "soft far-off gaze, gentle relaxed expression",
    "playful": "mischievous slight smile, sparkling eyes, raised brow",
    "tender": "warm soft eyes, gentle smile, head slightly tilted",
    "professional": "composed alert expression, slight polite smile",
    "concerned_warm": "soft worried brow, attentive eyes, lips slightly parted",
}

EYE_GAZE_PRESETS: dict[str, str] = {
    "to_camera": "looking directly at camera",
    "off_left": "gaze towards off-screen left",
    "off_right": "gaze towards off-screen right",
    "downward": "downward gaze",
    "upward": "upward gaze",
    "middle_distance": "looking into middle distance, contemplative",
    "phone_screen": "eyes locked on phone screen",
    "laptop_screen": "eyes focused on laptop screen",
    "notebook_paper": "eyes on notebook or paper at hand",
    "across_room": "eyes drifting across the room",
    "subject_off_frame": "eyes following something just off frame",
    "out_window": "looking out the window thoughtfully",
    "to_other_character": "eyes on the other person in the scene",
    "averted_shy": "averted gaze with lashes lowered",
    "rolling_back": "eyes briefly rolling, mock-exasperated",
}

HAIR_PRESETS: dict[str, str] = {
    "long_natural": "natural long hair, slightly wavy",
    "long_straight": "long straight hair, neatly arranged",
    "low_ponytail": "loose low ponytail with strands escaping",
    "high_ponytail": "neat high ponytail",
    "messy_morning": "tousled morning hair, slightly disheveled",
    "low_bun": "low bun with stray strands",
    "tucked_behind_ear": "hair tucked behind one ear",
    "shoulder_length": "shoulder length hair, natural fall",
    "half_up": "half-up half-down style",
    "swept_aside": "hair swept dramatically to one side",
}

BODY_POSTURE_PRESETS: dict[str, str] = {
    "standing_alert": "standing upright, attentive posture",
    "standing_relaxed": "standing relaxed, weight on one foot",
    "sitting_comfortable": "sitting comfortably, weight settled",
    "sitting_alert": "sitting upright, engaged posture",
    "leaning_forward": "leaning forward at desk, engaged",
    "leaning_back_relaxed": "leaning back, arms relaxed",
    "slumped": "shoulders forward, slightly slumped",
    "rushing": "mid-stride, hurried movement, body angled forward",
    "stretching": "arms raised in stretch, slight back arch",
    "side_three_quarter": "three-quarter side angle, slight body turn",
    "facing_away": "facing slightly away from camera",
    "lying_relaxed": "lying down in a relaxed pose",
    "kneeling": "kneeling on the floor",
    "hands_on_hips": "standing with hands on hips, confident pose",
    "arms_crossed": "arms crossed in front, neutral stance",
}

LIGHTING_PRESETS: dict[str, str] = {
    "warm_morning": "warm soft morning light, golden tones",
    "cool_morning": "cool soft morning light, blue tint",
    "bright_daylight": "bright airy daylight, soft shadows",
    "afternoon_warm": "warm afternoon light, amber cast",
    "golden_hour": "golden hour warm sunset light, lens halation",
    "evening_ambient": "warm evening ambient light, soft glow",
    "night_indoor": "warm indoor lamp light, low-key ambient",
    "cool_office": "cool fluorescent office light, slight blue tint",
    "dramatic_blue": "cool blue tones, sharp shadows",
    "neutral_studio": "balanced even daylight, neutral fill",
    "moody_lowkey": "moody low-key lighting, deep shadows",
    "overcast_soft": "soft overcast diffuse light",
    "high_contrast": "harsh high-contrast light with strong shadows",
    "rim_backlight": "warm rim backlight, glowing silhouette",
}

CAMERA_PRESETS: dict[str, str] = {
    "static_locked": "static locked-off frame, calm composition",
    "subtle_handheld": "subtle handheld breathing motion",
    "push_in_slow": "smooth slow push-in",
    "push_in_quick": "quick push-in then steady hold",
    "pull_back_slow": "gentle slow pull-back",
    "snap_zoom": "snap zoom in",
    "low_angle": "low-angle hero shot",
    "overhead": "overhead bird's eye view",
    "dutch_tilt_mild": "slightly tilted Dutch angle",
    "shoulder_close": "tight shoulder-and-up close-up",
    "wide_establishing": "wide establishing shot of the space",
    "over_shoulder": "over-the-shoulder framing",
    "tracking_side": "tracking sideways alongside subject",
}

TONE_PRESETS: dict[str, str] = {
    "warm_settled": "warm, settled, naturally pleased",
    "tense_focused": "tense, focused, time-pressured",
    "lightly_hurried": "lightly hurried but composed",
    "energetic_upbeat": "energetic, upbeat, naturally cheerful",
    "subdued_weighty": "subdued, weighed down",
    "alert_observant": "alert, observant, slightly cautious",
    "uncertain_pondering": "uncertain, pondering, considering",
    "matter_of_fact": "matter-of-fact, observational, neutral",
    "playful_relaxed": "playful, relaxed, easy-going",
    "embarrassed_sheepish": "embarrassed, sheepish, flustered",
    "tender_intimate": "tender, intimate, quiet warmth",
    "professional_composed": "professional, composed, deliberate",
}

# composer / API が動的 lookup するための集約 dict
PROMPT_PRESET_LIBRARIES: dict[str, dict[str, str]] = {
    "facial": FACIAL_PRESETS,
    "eye_gaze": EYE_GAZE_PRESETS,
    "hair": HAIR_PRESETS,
    "body_posture": BODY_POSTURE_PRESETS,
    "lighting": LIGHTING_PRESETS,
    "camera": CAMERA_PRESETS,
    "tone": TONE_PRESETS,
}

# preset ID → 日本語ラベル (UI 表示用、SSOT原則: 値は preset ID のまま、表示だけ日本語)
PRESET_LABELS_JA: dict[str, dict[str, str]] = {
    "facial": {
        "neutral": "平静",
        "thoughtful": "考え事",
        "focused": "集中",
        "deadpan": "無表情",
        "slight_smile": "微笑み",
        "wide_smile": "大きな笑顔",
        "satisfied_smile": "満足げな笑顔",
        "shy_smile": "照れ笑い",
        "knowing_smirk": "意味深なニヤリ",
        "laugh_open": "口を開けて笑う",
        "surprised_mild": "軽い驚き",
        "surprised_pleasant": "嬉しい驚き",
        "shocked": "衝撃",
        "alarmed": "ぎょっとした",
        "alert_focused": "気を張った集中",
        "anxious": "不安げ",
        "panicked": "パニック",
        "stressed": "ストレス顔",
        "subdued": "しょんぼり",
        "deflated": "落ち込み",
        "tearful": "涙ぐむ",
        "wistful": "切ない眼差し",
        "annoyed": "ムッとした",
        "angry": "怒り",
        "furious": "激怒",
        "cold_glare": "冷たい視線",
        "confused": "困惑",
        "skeptical": "疑い",
        "puzzled": "不思議そう",
        "embarrassed": "恥ずかしい",
        "flustered": "うろたえ",
        "shy_glance": "恥じらいの視線",
        "sleepy": "眠たげ",
        "groggy_morning": "寝起きでぼんやり",
        "exhausted": "疲労困憊",
        "yawning": "あくび",
        "concentrating": "画面に集中",
        "observing": "注意深く観察",
        "reading": "読む",
        "delighted_surprise": "嬉しい驚き (大)",
        "warm_relief": "温かい安堵",
        "determined": "決意",
        "contemplative": "物思い",
        "playful": "いたずらっぽい",
        "tender": "優しい眼差し",
        "professional": "プロフェッショナル",
        "concerned_warm": "心配そうな温かさ",
    },
    "eye_gaze": {
        "to_camera": "カメラ目線",
        "off_left": "画面外左",
        "off_right": "画面外右",
        "downward": "下を見る",
        "upward": "上を見る",
        "middle_distance": "遠くを見る",
        "phone_screen": "スマホ画面を見る",
        "laptop_screen": "ラップトップを見る",
        "notebook_paper": "ノート/紙を見る",
        "across_room": "部屋を見渡す",
        "subject_off_frame": "画面外の何かを追う",
        "out_window": "窓の外を見る",
        "to_other_character": "相手キャラを見る",
        "averted_shy": "恥じらいで目を逸らす",
        "rolling_back": "目を一瞬回す",
    },
    "hair": {
        "long_natural": "ナチュラルロング",
        "long_straight": "ストレートロング",
        "low_ponytail": "ゆるいローポニー",
        "high_ponytail": "ハイポニー",
        "messy_morning": "寝起きの乱れ髪",
        "low_bun": "ローシニヨン",
        "tucked_behind_ear": "片耳にかける",
        "shoulder_length": "肩までの自然なヘア",
        "half_up": "ハーフアップ",
        "swept_aside": "片側に流す",
    },
    "body_posture": {
        "standing_alert": "シャキッと立つ",
        "standing_relaxed": "リラックスして立つ",
        "sitting_comfortable": "ゆったり座る",
        "sitting_alert": "シャキッと座る",
        "leaning_forward": "前のめり",
        "leaning_back_relaxed": "後ろにもたれる",
        "slumped": "前かがみで猫背気味",
        "rushing": "駆け足の体勢",
        "stretching": "伸びをする",
        "side_three_quarter": "3/4 横向き",
        "facing_away": "やや背を向ける",
        "lying_relaxed": "リラックスして寝そべる",
        "kneeling": "ひざまずく",
        "hands_on_hips": "腰に手",
        "arms_crossed": "腕組み",
    },
    "lighting": {
        "warm_morning": "温かい朝の光",
        "cool_morning": "涼しげな朝の光",
        "bright_daylight": "明るい昼光",
        "afternoon_warm": "温かい午後の光",
        "golden_hour": "ゴールデンアワー",
        "evening_ambient": "夜の柔らかい室内光",
        "night_indoor": "夜のランプ光",
        "cool_office": "オフィスの蛍光灯",
        "dramatic_blue": "クールな青み",
        "neutral_studio": "中立スタジオ照明",
        "moody_lowkey": "ローキー暗め",
        "overcast_soft": "曇天柔らか",
        "high_contrast": "ハードシャドウ",
        "rim_backlight": "温かい逆光リム",
    },
    "camera": {
        "static_locked": "固定ショット",
        "subtle_handheld": "微細な手持ち",
        "push_in_slow": "ゆっくり寄る",
        "push_in_quick": "素早く寄って止まる",
        "pull_back_slow": "ゆっくり引く",
        "snap_zoom": "急ズーム",
        "low_angle": "ローアングル",
        "overhead": "俯瞰",
        "dutch_tilt_mild": "わずかに傾けたダッチ",
        "shoulder_close": "胸上クロースアップ",
        "wide_establishing": "広角全景",
        "over_shoulder": "肩越し",
        "tracking_side": "横移動トラッキング",
    },
    "tone": {
        "warm_settled": "温かく落ち着いた",
        "tense_focused": "緊張感のある集中",
        "lightly_hurried": "軽く急いでいる",
        "energetic_upbeat": "エネルギッシュで陽気",
        "subdued_weighty": "重く沈んだ",
        "alert_observant": "警戒した観察モード",
        "uncertain_pondering": "不確実で考え込む",
        "matter_of_fact": "淡々と事実を述べる",
        "playful_relaxed": "遊び心のあるリラックス",
        "embarrassed_sheepish": "気まずく恥じる",
        "tender_intimate": "優しく親密",
        "professional_composed": "プロらしく落ち着いた",
    },
    "scene_element": {
        "standing_desk": "スタンディングデスク",
        "ergonomic_chair": "エルゴノミクスチェア",
        "plants_background": "観葉植物の背景",
        "bookshelf_bg": "本棚の背景",
        "art_painting_bg": "アート絵画の背景",
        "window_morning_light": "朝日の差す窓",
        "window_afternoon": "午後の光の窓",
        "coffee_cup": "コーヒーカップ",
        "smartphone_visible": "スマホが映る",
        "laptop_macbook": "MacBook",
        "notebook_pen": "ノートとペン",
        "minimalist_decor": "ミニマル北欧インテリア",
        "warm_wood_decor": "ウッドトーン暖色インテリア",
        "modern_office": "モダンなホームオフィス",
        "cozy_living_room": "リビングのソファ",
        "bedroom_furniture": "ベッドルームの家具",
        "kitchen_modern": "モダンキッチン",
        "outdoor_street": "住宅街の屋外",
        "office_meeting_room": "オフィス会議室",
        "headphones_visible": "ヘッドフォン着用",
    },
}

# UI dropdown のカテゴリ名 (preset library のキー → 日本語名)
PRESET_CATEGORY_LABELS_JA: dict[str, str] = {
    "facial": "表情",
    "eye_gaze": "視線",
    "hair": "髪型",
    "body_posture": "体勢",
    "lighting": "照明",
    "camera": "カメラ",
    "tone": "トーン",
    "scene_element": "シーン要素",
}

# emotion (lines[].emotion) → 各カテゴリーで採用される preset ID。
# UI で「現在 emotion から導出されている既定 preset」を表示するために使う。
# composer 側は EMOTION_VISUAL_CUES (テキスト) 経由で展開しているので、
# この対応表は UI 表示用のヒントとして機能する。
EMOTION_DEFAULT_PRESET_IDS: dict[str, dict[str, str]] = {
    "驚き":     {"facial": "surprised_mild", "tone": "alert_observant"},
    "喜び":     {"facial": "slight_smile",   "tone": "energetic_upbeat"},
    "焦り":     {"facial": "alert_focused",  "tone": "lightly_hurried"},
    "落胆":     {"facial": "subdued",        "tone": "subdued_weighty"},
    "中立":     {"facial": "neutral",        "tone": "matter_of_fact"},
    "満足":     {"facial": "satisfied_smile","tone": "warm_settled"},
    "困惑":     {"facial": "confused",       "tone": "uncertain_pondering"},
    "怒り":     {"facial": "angry",          "tone": "tense_focused"},
    "恥ずかしさ": {"facial": "embarrassed",  "tone": "embarrassed_sheepish"},
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

DELIVERY_TAG_FORMAT = "[{delivery}] {text}"
DELIVERY_TAG_ENABLED = True

# TTSの文中に挿入される長すぎる無音を圧縮する後処理
TTS_TRIM_INTERNAL_PAUSES = True
TTS_PAUSE_THRESHOLD_DB = -35.0  # これより小さい音を「無音」と判定
TTS_PAUSE_KEEP_MS = 70          # 圧縮後に残す無音の長さ (短いほど詰まる)
TTS_TEMPO_MULTIPLIER = 1.0      # 1.0 で無効。1.05 で5%早回し (微妙にテンポ向上)

# ElevenLabs Voice Library から「Language: Japanese」で絞り込み、
# 試聴 → "Add to my voices" した上で voice_id を取得して登録する。
# 各 entry の voice_id は characters/<base>/voice.json.voice_id から参照され、
# Stage 2 TTS で per-character の声色として使われる (= 未設定キャラは
# ELEVENLABS_VOICE_ID へフォールバック)。
VOICE_LIBRARY: list[dict] = [
    {
        "voice_id": "0ptCJp0xgdabdcpVtCB5",
        "name": "日本語ネイティブ女性 (f1: 20代前半・活発)",
        "gender": "female",
        "age": "young_adult",
        "language": "ja",
    },
    {
        "voice_id": "gARvXPexe5VF3cKZBian",
        "name": "日本語ネイティブ女性 (f2: 20代後半・知的)",
        "gender": "female",
        "age": "young_adult",
        "language": "ja",
    },
    {
        "voice_id": "OSwaPSNdfituxkWcjlkR",
        "name": "日本語ネイティブ女性 (f3: 30代前半・優しい)",
        "gender": "female",
        "age": "adult",
        "language": "ja",
    },
    {
        "voice_id": "tpdfLrb2z3dwaZQdMBjP",
        "name": "日本語ネイティブ男性 (m1: 20代中盤・爽やか)",
        "gender": "male",
        "age": "young_adult",
        "language": "ja",
    },
    {
        "voice_id": "vzIXwvf41vKosKu00hYj",
        "name": "日本語ネイティブ男性 (m2: 30代前半・知的)",
        "gender": "male",
        "age": "adult",
        "language": "ja",
    },
]

BREATH_DEFAULT_DURATION = 0.25

# scene.duration の末尾余白。0.3 だと merged 連結時に _merge_scenes が tpad で
# 末尾フレームを 0.3s クローンし、各シーン末尾が一瞬フリーズして切替が不自然に
# なる (= scene 動画自体は末尾まで動いている)。0 にして duration を実発話長に
# 揃え tpad を発動させない。シーン間の「間」は scene 動画末尾の発話後区間
# (= line.end〜音声末尾、動いている映像) が担う。
SCENE_TTS_TAIL_BUFFER = 0.0
SCENE_TTS_NATURAL_GAP = 0.3

# 主要動作をクリップのこの割合までに終える指示 (残りは静止保持で末尾トリム用)。
# 0.7 だと末尾静止 30% が、動画が TTS より短い時の slow_mo 延長で目立つフリーズに
# なりシーン切替が不自然。0.85 にして末尾静止を短く保ち、切替を自然にする。
ACTION_FRONTLOAD_RATIO = 0.85
ACTION_IDLE_THRESHOLD = 0.005
ACTION_IDLE_MIN_DURATION = 0.3

# Kling V3 は 5s と 10s しか生成できない。TTS が 5.0 を僅かに超えただけで
# 10s クリップ ($0.84) に切り替わるとコスパが悪いため、許容比率を導入する。
# - target ≤ 5.0 * KLING_DURATION_TOLERANCE_RATIO → 5s クリップ + slow_mo
# - それ以外 → 10s クリップ
# 1.2 = 5s クリップで TTS 6.0s まで、10s クリップで TTS 12.0s まで吸収。
# slow_mo ratio が 1.2x 以下に収まるため知覚的に自然。
KLING_DURATION_TOLERANCE_RATIO = 1.2

# fal_client.subscribe() は完了まで内部で永久にポーリングする。
# fal.ai 側の stuck job (= 6 時間 202 が続く等) で無限待機しないよう、
# クライアント側で総ジョブ尺をタイムアウトする (案 A: threading watchdog)。
# 期限超過で TimeoutError 相当を投げ、上位の MAX_RETRIES ループで停止する。
FAL_KLING_TIMEOUT_SEC = float(os.getenv("FAL_KLING_TIMEOUT_SEC", "3600"))     # 1 hour

# lipsync / Sync.so 関連は config.audio から re-export (= §3.1.4-b)。
from config.audio import (  # noqa: F401, E402
    LIPSYNC_ENABLED,
    LIPSYNC_HTTP_TIMEOUT_DOWNLOAD_SEC,
    LIPSYNC_HTTP_TIMEOUT_QUERY_SEC,
    LIPSYNC_HTTP_TIMEOUT_SUBMIT_SEC,
    LIPSYNC_HTTP_TIMEOUT_UPLOAD_SEC,
    LIPSYNC_SYNC_MODE,
    SYNCSO_BASE_URL,
    SYNCSO_LIPSYNC_MODEL,
    SYNCSO_MAX_FILE_MB,
    SYNCSO_POLL_INTERVAL_SEC,
    SYNCSO_POLL_TIMEOUT_SEC,
)

MIN_SEGMENT_CHARS = 15
MAX_MERGED_CHARS_PER_GROUP = 105

# パッケージ化 (= config/__init__.py) 後は __file__ が config/ 配下を指すため、
# project root に上がるよう dirname を 1 段追加する (= 旧 config.py 時代の挙動と
# 一致させ、LOCATIONS_DIR 等が project root 直下の locations/ を指すように)。
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
TEMP_DIR = os.path.join(BASE_DIR, "temp")
SCREENPLAYS_DIR = os.path.join(BASE_DIR, "screenplays")
POST_CAPTIONS_DIR = os.path.join(BASE_DIR, "post_captions")
CHARACTERS_DIR = os.path.join(BASE_DIR, "characters")
DEFAULT_CHARACTER_REFS: list[str] = ["f1"]

# cache 関連は config.cache から re-export (= §3.1.4-b)。
from config.cache import (  # noqa: F401, E402
    BG_CACHE_DIR,
    BG_CACHE_ENABLED,
    BG_CACHE_REQUIRE_APPROVAL,
    BG_CACHE_TTL_DAYS,
    BG_CACHE_VERSION,
    CLIP_LIBRARY_DIR,
    CLIP_LIBRARY_ENABLED,
    CLIP_LIBRARY_VERSION,
    CLIP_POOL_AUTO_APPROVE,
    CLIP_POOL_MAX_TOTAL_GB,
    CLIP_POOL_TARGET_SIZE,
    CLIP_POOL_TOP_K,
    KLING_CACHE_AUTO_PRUNE,
    KLING_CACHE_DIR,
    KLING_CACHE_ENABLED,
    KLING_CACHE_MAX_BYTES,
    KLING_CACHE_MISMATCH_THRESHOLD,
    KLING_CACHE_REQUIRE_APPROVAL,
    KLING_CACHE_TTL_DAYS,
    KLING_CACHE_VERSION,
)
# part_registry の SSOT yaml 群が住むディレクトリ
PART_REGISTRY_DIR = os.environ.get(
    "PART_REGISTRY_DIR", os.path.join(BASE_DIR, "config", "part_registry"))
# Phase 6: analyze pipeline が visual_intent_id を推定する際の confidence 閾値。
# これ未満なら free-text fallback (= _override_animation_prompt) を使う。
INTENT_CONFIDENCE_THRESHOLD = float(
    os.getenv("INTENT_CONFIDENCE_THRESHOLD", "0.7"))

# novel intent suggestion inbox (= analyze pipeline 検出 + UI トリアージの SSOT)。
# 詳細は docs/plannings/2026-05-10_intent-suggestion-flow.md §2.3
INTENT_SUGGESTIONS_PATH = os.environ.get(
    "INTENT_SUGGESTIONS_PATH",
    os.path.join(BASE_DIR, "data", "intent_suggestions.json"),
)
INTENT_SUGGESTIONS_ARCHIVE_DIR = os.environ.get(
    "INTENT_SUGGESTIONS_ARCHIVE_DIR",
    os.path.join(BASE_DIR, "data", "intent_suggestions_archive"),
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE")
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(20 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "10"))

# ───────────── Phase 1: フルオート量産経路 ─────────────
# cost / cap 系は config.cost から re-export (= §3.1.4-b)。
from config.cost import (  # noqa: F401, E402
    AUTO_LOOP_ALLOW_PUBLIC,
    AUTO_LOOP_STAGE_SOFT_LIMIT_SEC,
    DAILY_COST_CAP_USD,
    DAILY_VIDEO_CAP,
    MONTHLY_COST_CAP_USD,
    SLACK_WEBHOOK_URL,
)

# ───────────── Phase 2-4: QA / Bandit / Human gate ─────────────
# QA validator / bandit / production gate 系は config.qa から re-export。
from config.qa import (  # noqa: F401, E402
    BANDIT_AXES,
    BANDIT_EPSILON,
    IMPROVEMENT_STRATEGY,
    PRODUCTION_HUMAN_GATE_ENABLED,
    QA_RETRY_LIMITS,
    QA_VALIDATOR_BLACKLIST,
    QA_VALIDATORS_ENABLED,
    SUBTITLE_AUDIO_SYNC_MATCH_MIN,
    SUBTITLE_RENDER_EDGE_DENSITY_MIN,
    SUBTITLE_TIMING_DRIFT_RATIO_MAX,
    SUBTITLE_TIMING_DRIFT_RATIO_MIN,
    VALID_IMPROVEMENT_STRATEGIES,
)
