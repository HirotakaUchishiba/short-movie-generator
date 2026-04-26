import re

from jsonschema import Draft202012Validator

SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["caption", "scenes"],
    "additionalProperties": True,
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
        "wardrobe_continuity": {
            "type": "object",
            "additionalProperties": True,
            "description": "衣装識別子→説明 のマップ。scenes[].wardrobe.identifier と紐付け、Imagenプロンプトに自動展開",
        },
        "scenes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["duration", "background_prompt"],
                "additionalProperties": True,
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
                    "animation_prompt": {
                        "type": "string",
                        "description": "Kling V3に渡すモーションプロンプト（英語推奨、シーン全体の動き）",
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
                        "description": "シーンに登場する人物一覧",
                        "items": {
                            "type": "object",
                            "additionalProperties": True,
                            "properties": {
                                "name": {"type": "string"},
                                "role": {"type": "string", "description": "主役/相手/通行人 など"},
                                "ref": {"type": "string", "description": "characters/<ref>.png のキー"},
                                "outfit": {"type": "string", "description": "服装の自然言語記述"},
                            },
                        },
                    },
                    "wardrobe": {
                        "type": "object",
                        "additionalProperties": True,
                        "description": "シーン内の主役キャラの服装。同一identifierなら他シーンと一貫性を保つ",
                        "properties": {
                            "identifier": {"type": "string"},
                            "top": {"type": "string"},
                            "bottom": {"type": "string"},
                            "accessories": {"type": "string"},
                            "hair": {"type": "string"},
                        },
                    },
                    "facial_expression": {
                        "type": "string",
                        "description": "シーン全体の主要な表情（例 \"細目で寝起き顔\" \"驚いて目を見開く\"）",
                    },
                    "hand_gesture": {
                        "type": "string",
                        "description": "シーン全体の主要な手の動き（例 \"頭を抱える\" \"スマホを見せる\"）",
                    },
                    "lines": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["text", "start"],
                            "additionalProperties": True,
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


def validate_screenplay(screenplay: dict, strict: bool = True) -> list[str]:
    errors: list[str] = []

    for err in _VALIDATOR.iter_errors(screenplay):
        path = "/".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{path}: {err.message}")

    errors.extend(_check_line_bounds(screenplay))

    if strict and errors:
        raise ValueError(
            "台本バリデーションエラー:\n" + "\n".join(f"  - {e}" for e in errors)
        )
    return errors
