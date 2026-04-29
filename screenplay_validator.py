import re

from jsonschema import Draft202012Validator

import config

# preset enum 一覧 (config.py から動的に取得して enum 制約に展開する)
_FACIAL_KEYS = list(config.FACIAL_PRESETS.keys())
_EYE_GAZE_KEYS = list(config.EYE_GAZE_PRESETS.keys())
_HAIR_KEYS = list(config.HAIR_PRESETS.keys())
_BODY_POSTURE_KEYS = list(config.BODY_POSTURE_PRESETS.keys())
_LIGHTING_KEYS = list(config.LIGHTING_PRESETS.keys())
_CAMERA_KEYS = list(config.CAMERA_PRESETS.keys())
_TONE_KEYS = list(config.TONE_PRESETS.keys())
_SCENE_ELEMENT_KEYS = list(config.SCENE_ELEMENT_PRESETS.keys())
_SCENE_TAGS = list(config.SCENE_TAGS)

SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["caption", "scenes"],
    # SSOT 強制: ルートも未定義キー拒否
    "additionalProperties": False,
    "properties": {
        "caption": {
            "type": "string",
            "minLength": 1,
            "description": "SNS投稿用キャプション本文（ハッシュタグ含む）",
        },
        "title_overlay": {
            "type": "string",
            "description": "動画上部に全編固定表示する黄色帯タイトル（改行は \\n）",
        },
        "audio_mode": {
            "enum": ["voiced", "silent"],
            "description": "voiced=TTS+リップシンク、silent=無音。既定 voiced",
        },
        "bgm_path": {
            "type": "string",
            "description": "全編に流すBGMファイル絶対パス。指定時はvoice下にmix",
        },
        "bgm_volume_db": {
            "type": "number",
            "description": "BGMの相対音量dB。既定 -18 (ボイスより小)",
        },
        "subtitle_y_from_bottom": {
            "type": "integer",
            "minimum": 0,
            "description": (
                "字幕の Y 位置 (画面下端からのピクセル数)。"
                "未指定なら config.SUBTITLE_Y_FROM_BOTTOM を使用"
            ),
        },
        "wardrobe_continuity": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "衣装識別子→説明 のマップ。scenes[].wardrobe.identifier と紐付け、Imagenプロンプトに自動展開",
        },
        "location_continuity": {
            "type": "object",
            "description": (
                "ロケーション識別子→属性辞書のマップ。"
                "scenes[].location_ref と紐付けて、同一動画内でロケの装飾・ライティング・"
                "色味・小道具・カメラ距離を一貫させる。各属性は background_prompt の先頭に注入される"
            ),
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "decor": {
                        "type": "string",
                        "description": "家具・壁・床・建材などのレイアウト記述",
                    },
                    "lighting": {
                        "type": "string",
                        "description": "光源・色温度・影の質感",
                    },
                    "color_palette": {
                        "type": "string",
                        "description": "全体の配色トーン",
                    },
                    "props": {
                        "type": "string",
                        "description": "小道具 (PC, マグカップ, 書類 等)",
                    },
                    "camera_distance": {
                        "type": "string",
                        "description": "推奨カメラ距離 (close-up / medium-close / medium / wide 等)",
                    },
                },
            },
        },
        "scoped_augmentations": {
            "type": "array",
            "description": (
                "横断適用ルール。scope 一致するシーンに scene_element preset を追加挿入する。"
                "値はすべて preset ID (enum) で SSOT 厳格"
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["scope", "elements"],
                "properties": {
                    "id": {"type": "string"},
                    "scope": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "tag": {"enum": _SCENE_TAGS},
                            "scene_idx": {
                                "type": "array",
                                "items": {"type": "integer", "minimum": 0},
                            },
                        },
                    },
                    "elements": {
                        "type": "array",
                        "items": {"enum": _SCENE_ELEMENT_KEYS},
                        "minItems": 1,
                    },
                },
            },
        },
        "_analysis": {
            "type": "object",
            "additionalProperties": True,
            "description": "analyze_video.py が書く解析メタデータ (analytics 用、再生成パイプには影響しない)",
        },
        "scenes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["duration", "background_prompt"],
                # SSOT 強制: 未定義のキーは拒否 (廃止フィールドの再混入を防ぐ)
                "additionalProperties": False,
                "properties": {
                    "time": {
                        "type": "string",
                        "description": "画面下部に大きく表示する時刻（例 \"8:50\"）",
                    },
                    "label": {
                        "type": "string",
                        "description": "時刻の下に表示するシーンラベル（例 \"起床\"）",
                    },
                    "duration": {
                        "type": "number",
                        "minimum": 3,
                        "description": "シーン秒数。Klingは5/10秒生成しこの値にtrim",
                    },
                    "background_prompt": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Imagenに渡す背景プロンプト（被写体=日本語+スタイル修飾=英語）",
                    },
                    "location_ref": {
                        "type": "string",
                        "description": (
                            "root.location_continuity のキーを参照。"
                            "ロケの装飾・ライティング・色味・小道具・カメラ距離が"
                            "background_prompt の先頭に自動注入される"
                        ),
                    },
                    "animation_prompt": {
                        "type": "string",
                        "description": "Kling V3に渡すモーションプロンプト（英語推奨、シーン全体の動き）",
                    },
                    "animation_prompt_auto": {
                        "type": "string",
                        "description": (
                            "auto_animation_prompt が lines/emotion/delivery/acoustic から"
                            "Claude Sonnet で自動生成した prompt。"
                            "scene.animation_prompt が空の場合のフォールバックとして使用される。"
                            "UI から「採用」すれば animation_prompt にコピーされる"
                        ),
                    },
                    "character_refs": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "description": "characters/<name>.png を参照。未指定なら config.DEFAULT_CHARACTER_REFS",
                    },
                    "lipsync": {
                        "type": "boolean",
                        "description": "このシーンでリップシンクを適用するか（既定true、audio_mode=silentなら無視）",
                    },
                    "characters": {
                        "type": "array",
                        "description": (
                            "シーンに登場する人物一覧 (多人数シーン時に使用)。"
                            "name / role のみ。outfit / ref は廃止 (SSOT原則)"
                        ),
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "name": {"type": "string"},
                                "role": {"type": "string", "description": "主役/相手/通行人 など"},
                            },
                        },
                    },
                    "wardrobe": {
                        "type": "object",
                        "additionalProperties": False,
                        "description": (
                            "シーン内の服装。identifier だけを書き、"
                            "実際の説明は root.wardrobe_continuity[identifier] を参照する"
                        ),
                        "properties": {
                            "identifier": {"type": "string"},
                        },
                    },
                    "tags": {
                        "type": "array",
                        "items": {"enum": _SCENE_TAGS},
                        "description": (
                            "scope 解決用のタグ。config.SCENE_TAGS の値のみ許容。"
                            "scoped_augmentations の scope.tag と照合される"
                        ),
                    },
                    "emotion_cue_overrides": {
                        "type": "object",
                        "additionalProperties": False,
                        "description": (
                            "EMOTION_VISUAL_CUES の上書き。値は preset ID (enum)。"
                            "上書きされなかったカテゴリは emotion 由来の既定 cue を使う"
                        ),
                        "properties": {
                            "facial":       {"enum": _FACIAL_KEYS},
                            "eye_gaze":     {"enum": _EYE_GAZE_KEYS},
                            "hair":         {"enum": _HAIR_KEYS},
                            "body_posture": {"enum": _BODY_POSTURE_KEYS},
                            "lighting":     {"enum": _LIGHTING_KEYS},
                            "camera":       {"enum": _CAMERA_KEYS},
                            "tone":         {"enum": _TONE_KEYS},
                        },
                    },
                    "lines": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["text", "start"],
                            "additionalProperties": False,
                            "properties": {
                                "text": {
                                    "type": "string",
                                    "minLength": 1,
                                    "pattern": r"^[^,.]*$",
                                },
                                "tts_text": {
                                    "type": "string",
                                    "description": "TTS送信用の上書きテキスト。指定時はpronunciation_hints/clean_textをスキップ",
                                },
                                "start": {
                                    "type": "number",
                                    "minimum": 0,
                                    "description": "シーン内相対秒でのセリフ開始",
                                },
                                "end": {
                                    "type": "number",
                                    "exclusiveMinimum": 0,
                                    "description": "字幕が消える相対秒（TTS長には使わない、字幕表示のみ）",
                                },
                                "rate": {
                                    "type": "string",
                                    "description": "TTS速度（例 +10%）",
                                },
                                "silence_after_ms": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 2000,
                                    "description": "このlineの後ろに含める自然音声の長さ (ms)。次lineを侵食しない範囲でclamp",
                                },
                                "emotion": {
                                    "type": "string",
                                    "description": "感情ラベル（例 驚き/喜び/焦り）。config.EMOTION_VOICE_PRESETSのキーと対応",
                                },
                                "emotion_intensity": {
                                    "type": "string",
                                    "enum": ["soft", "normal", "strong"],
                                    "description": "感情の強度。emotion presetに加算/減算修飾",
                                },
                                "audio_tags": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "eleven_v3 audio tags (例: [\"laughs\", \"whispers\"])",
                                },
                                "delivery": {
                                    "type": "string",
                                    "description": "話し方の自然言語記述（人間・LLMが読む参考情報）",
                                },
                                "acoustic": {
                                    "type": "object",
                                    "additionalProperties": True,
                                    "properties": {
                                        "pitch_hz_mean": {"type": "number"},
                                        "pitch_trend": {"type": "string"},
                                        "rms_peak": {"type": "number"},
                                        "wpm": {"type": "number"},
                                    },
                                    "description": "librosaから取得した音響特徴量",
                                },
                                "voice_overrides": {
                                    "type": "object",
                                    "additionalProperties": True,
                                    "properties": {
                                        "stability": {"type": "number"},
                                        "style": {"type": "number"},
                                        "similarity_boost": {"type": "number"},
                                        "voice_id": {"type": "string"},
                                    },
                                    "description": "このlineに限定したElevenLabsパラメータ上書き",
                                },
                                "pronunciation_hints": {
                                    "type": "object",
                                    "additionalProperties": {"type": "string"},
                                    "description": "TTS送信前のテキスト置換（例 {\"IT\": \"アイティー\"}）",
                                },
                                "pause_before": {
                                    "type": "number",
                                    "minimum": 0,
                                    "description": "このline直前に挿入する無音秒数",
                                },
                                "breath_before": {
                                    "type": "boolean",
                                    "description": "true なら短い吸気音を挿入",
                                },
                                "speaker": {
                                    "type": "string",
                                    "description": "発話者（複数キャラの場合）。scenes[].characters[].name と対応",
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}

_VALIDATOR = Draft202012Validator(SCHEMA)


def _check_line_bounds(screenplay: dict) -> list[str]:
    errors: list[str] = []
    for s_idx, scene in enumerate(screenplay.get("scenes", [])):
        duration = scene.get("duration")
        if not isinstance(duration, (int, float)):
            continue
        for l_idx, line in enumerate(scene.get("lines", []) or []):
            start = line.get("start")
            end = line.get("end")
            path = f"scenes/{s_idx}/lines/{l_idx}"
            if isinstance(start, (int, float)) and start > duration:
                errors.append(f"{path}/start: start={start}がシーン長{duration}を超えています")
            if isinstance(end, (int, float)) and end > duration + 0.01:
                errors.append(f"{path}/end: end={end}がシーン長{duration}を超えています")
            if (isinstance(start, (int, float)) and isinstance(end, (int, float))
                    and end <= start):
                errors.append(f"{path}: end({end}) <= start({start})")
    return errors


def _check_location_refs(screenplay: dict) -> list[str]:
    """scenes[].location_ref が root.location_continuity に存在するか検証。"""
    errors: list[str] = []
    locations = screenplay.get("location_continuity") or {}
    for s_idx, scene in enumerate(screenplay.get("scenes", [])):
        ref = scene.get("location_ref")
        if ref is None:
            continue
        if ref not in locations:
            keys = ", ".join(sorted(locations.keys())) or "(空)"
            errors.append(
                f"scenes/{s_idx}/location_ref: '{ref}' は location_continuity に未定義 "
                f"(定義済み: {keys})"
            )
    return errors


def validate_screenplay(screenplay: dict, strict: bool = True) -> list[str]:
    errors: list[str] = []

    for err in _VALIDATOR.iter_errors(screenplay):
        path = "/".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{path}: {err.message}")

    errors.extend(_check_line_bounds(screenplay))
    errors.extend(_check_location_refs(screenplay))

    if strict and errors:
        raise ValueError(
            "台本バリデーションエラー:\n" + "\n".join(f"  - {e}" for e in errors)
        )
    return errors
