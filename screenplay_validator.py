
import logging

from jsonschema import Draft202012Validator

import atomic_assets
import config

logger = logging.getLogger(__name__)

# preset enum 一覧 (config.py から動的に取得して enum 制約に展開する)
_FACIAL_KEYS = list(config.FACIAL_PRESETS.keys())
_EYE_GAZE_KEYS = list(config.EYE_GAZE_PRESETS.keys())
_HAIR_KEYS = list(config.HAIR_PRESETS.keys())
_BODY_POSTURE_KEYS = list(config.BODY_POSTURE_PRESETS.keys())
_LIGHTING_KEYS = list(config.LIGHTING_PRESETS.keys())
_CAMERA_KEYS = list(config.CAMERA_PRESETS.keys())
_TONE_KEYS = list(config.TONE_PRESETS.keys())

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
        "featured_characters": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "description": (
                "動画全体の登場人物 (= 解決済み character ref のリスト)。"
                "compose 入力で各シーンの character_refs / character_selection の"
                "候補として使われる。abstract 形式専用フィールドだが、composed "
                "snapshot にも残しても無害なので schema は両方を許容する"
            ),
        },
        "subtitle_y_from_bottom": {
            "type": "integer",
            "minimum": 0,
            "description": (
                "字幕の Y 位置 (画面下端からのピクセル数)。"
                "未指定なら config.SUBTITLE_Y_FROM_BOTTOM を使用"
            ),
        },
        "hook_id": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Phase X-2a: 動画冒頭のフックパターン (= hooks/<id>.json)。"
                "存在チェックは _check_atomic_refs で実施"
            ),
        },
        "arc_id": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Phase X-2a: シーン進行の感情変化テンプレ (= arcs/<id>.json)。"
                "存在チェックは _check_atomic_refs で実施"
            ),
        },
        "scenes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                # background_prompt は composed 形式でのみ必須。
                # abstract 形式 (= snapshot 上) では未生成の状態で許容され、
                # `validate_screenplay(..., require_composed=True)` で後段直前に
                # 強制チェックされる
                "additionalProperties": False,
                "properties": {
                    "duration": {
                        "type": "number",
                        "description": (
                            "シーン秒数。Stage 2 (TTS) が実音声長から書き込む。"
                            "Stage 1 抽象台本では未指定が正常"
                        ),
                    },
                    "background_prompt": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Imagenに渡す背景プロンプト (composed 形式で必須、"
                            "abstract では未生成)"
                        ),
                    },
                    "character_selection": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "description": (
                            "compose 入力でこのシーンに登場させるキャラ ref の "
                            "subset。空配列は人物 0 人 (背景のみ)。abstract 専用"
                            "フィールドで composed 結果には残らない"
                        ),
                    },
                    "action_id": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Phase X-2a: 動作テンプレ (= actions/<id>.json)。"
                            "指定すると subject_state / animation_motion から "
                            "scene の background_prompt / animation_prompt が "
                            "自動派生する (= 既存の自由テキストは override 用に残せる)。"
                            "存在チェックは _check_atomic_refs で実施"
                        ),
                    },
                    "animation_prompt": {
                        "type": "string",
                        "description": "Kling V3に渡すモーションプロンプト（英語推奨、シーン全体の動き）",
                    },
                    "lipsync": {
                        "type": "boolean",
                        "description": "このシーンでリップシンクを適用するか（既定true）",
                    },
                    "characters": {
                        "type": "array",
                        "description": (
                            "シーンに登場する人物一覧 (多人数シーン時に使用)。"
                            "name には characters/<name>.png の ref が入る "
                            "(= scene.character_refs[] と一致する想定)"
                        ),
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "characters/<name>.png の ref",
                                },
                            },
                        },
                    },
                    "animation_style": {
                        "type": "string",
                        "enum": ["subtle", "standard", "expressive"],
                        "description": "シーンごとのアニメーションの強さ",
                    },
                    # ── abstract 入力フィールド (= analyze pipeline が産出) ──
                    # compose が identity に畳み込む元データ。composed snapshot
                    # では compose が pop するので残らないが、abstract / snapshot
                    # 直書きの段階では scene root に存在する。
                    "location_ref": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "locations/<id>.json のキー。analyze が catalog から "
                            "選定し、compose が identity.location_ref に畳み込む"
                        ),
                    },
                    "camera_distance": {
                        "type": "string",
                        "enum": ["close-up", "medium-close", "medium", "wide"],
                        "description": (
                            "シーンの寄り引き。analyze が選定し、compose が "
                            "identity.camera_distance に畳み込む"
                        ),
                    },
                    # ───── Compositional Architecture (= clip library) ─────
                    # 詳細: docs/plannings/2026-05-10_compositional-architecture.md §3
                    # Phase 1 ではすべて optional。新スキーマで使う場合のみ指定する。
                    "identity": {
                        "type": "object",
                        "additionalProperties": False,
                        "description": (
                            "Layer 1 (clip library) の hard match キー。"
                            "scene の identity 情報はこの入れ子のみで表現する "
                            "(= flat schema は撤去済み)"
                        ),
                        "properties": {
                            "character_refs": {
                                "type": "array",
                                "items": {"type": "string", "minLength": 1},
                            },
                            "location_ref": {"type": "string", "minLength": 1},
                            "start_emotion": {"type": "string", "minLength": 1},
                            "camera_distance": {
                                "type": "string",
                                "enum": ["close-up", "medium-close", "medium", "wide"],
                            },
                        },
                        "required": [
                            "character_refs",
                            "location_ref",
                            "start_emotion",
                            "camera_distance",
                        ],
                    },
                    "annotation": {
                        "type": "object",
                        "additionalProperties": False,
                        "description": (
                            "Layer 1 (clip library) の soft rank に使う注釈。"
                            "完全一致が無くても compatible_with 経由で fallback する"
                        ),
                        "properties": {
                            "visual_intent_id": {
                                "type": "string",
                                "description": "config/part_registry/visual_intents.yaml の id",
                            },
                            "duration_bucket": {
                                "type": "integer",
                                "enum": [5, 10],
                            },
                            "motion_intensity": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                            },
                            "generation_seed": {"type": "integer"},
                        },
                    },
                    "_override_background_prompt": {
                        "type": ["string", "null"],
                        "description": (
                            "novel intent / 緊急対応用 escape hatch。指定すると "
                            "atom_key を bypass して旧 free-text 経路で生成する"
                        ),
                    },
                    "_override_animation_prompt": {
                        "type": ["string", "null"],
                        "description": "_override_background_prompt と同様",
                    },
                    "lines": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["text"],
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
                                "emotion": {
                                    "type": "string",
                                    "description": "感情ラベル（例 驚き/喜び/焦り）。config.EMOTION_AUDIO_TAGS のキーと対応 (eleven_v3 inline tag に変換)",
                                },
                                "emotion_intensity": {
                                    "type": "string",
                                    "enum": ["soft", "normal", "strong"],
                                    "description": "感情の強度。analyzer / UI 編集用メタ (TTS パラメータには反映されない)",
                                },
                                "audio_tags": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "eleven_v3 audio tags (例: [\"laughs\", \"whispers\"])。line.text の先頭に [tag] として挿入される",
                                },
                                "delivery": {
                                    "type": "string",
                                    "description": "話し方の自然言語記述。DELIVERY_TAG_ENABLED 時は eleven_v3 inline tag として送信",
                                },
                                "acoustic": {
                                    "type": "object",
                                    "additionalProperties": True,
                                    "description": "analyze pipeline (librosa) 由来の音響メタ (pitch/rms/wpm)。表示・LLM 補助入力用で TTS には反映されない",
                                    "properties": {
                                        "pitch_trend": {"type": "string"},
                                        "rms_peak": {"type": "number"},
                                        "wpm": {"type": "number"},
                                    },
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
                                    "description": "compose が character.voice.json から merge する voice メタの保管庫",
                                },
                                "pronunciation_hints": {
                                    "type": "object",
                                    "additionalProperties": {"type": "string"},
                                    "description": "TTS送信前のテキスト置換（例 {\"IT\": \"アイティー\"}）",
                                },
                                "speaker": {
                                    "type": "string",
                                    "description": (
                                        "発話者の ref (= characters/<ref>.png のキー、"
                                        "scene.character_refs[] / scene.characters[].name "
                                        "と一致)。複数キャラのシーンで「誰のセリフか」を "
                                        "識別する。単一キャラのシーンでは省略可。"
                                    ),
                                },
                                "hidden": {
                                    "type": "boolean",
                                    "description": "true ならこの line の字幕を焼き込まない (TTS は通常通り)",
                                },
                                "subtitles": {
                                    "type": "array",
                                    "description": (
                                        "字幕の手動チャンク指定。各要素は {text} が必須、"
                                        "{start, end} は optional (両方指定 or 両方省略)。"
                                        "省略時は line.start - line.end の範囲を文字数比例で"
                                        "自動配分。指定するとこの line に対する自動分割を"
                                        "完全にスキップする"
                                    ),
                                    "items": {
                                        "type": "object",
                                        "required": ["text"],
                                        "additionalProperties": False,
                                        "properties": {
                                            "text": {
                                                "type": "string",
                                                "minLength": 1,
                                                "description": "字幕テキスト (改行は \\n)",
                                            },
                                            "start": {
                                                "type": "number",
                                                "minimum": 0,
                                                "description": "シーン内相対秒で字幕表示開始 (省略可)",
                                            },
                                            "end": {
                                                "type": "number",
                                                "exclusiveMinimum": 0,
                                                "description": "シーン内相対秒で字幕消去 (省略可)",
                                            },
                                        },
                                    },
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
        has_duration = isinstance(duration, (int, float))
        for l_idx, line in enumerate(scene.get("lines", []) or []):
            start = line.get("start")
            end = line.get("end")
            path = f"scenes/{s_idx}/lines/{l_idx}"
            if has_duration and isinstance(start, (int, float)) and start > duration:
                errors.append(f"{path}/start: start={start}がシーン長{duration}を超えています")
            if has_duration and isinstance(end, (int, float)) and end > duration + 0.01:
                errors.append(f"{path}/end: end={end}がシーン長{duration}を超えています")
            if (isinstance(start, (int, float)) and isinstance(end, (int, float))
                    and end <= start):
                errors.append(f"{path}: end({end}) <= start({start})")
            subs = line.get("subtitles", []) or []
            for sub_idx, sub in enumerate(subs):
                sub_path = f"{path}/subtitles/{sub_idx}"
                has_start = "start" in sub
                has_end = "end" in sub
                if has_start != has_end:
                    errors.append(
                        f"{sub_path}: start と end は両方指定するか両方省略してください "
                        f"(片方だけ指定は不可)"
                    )
                s_start = sub.get("start")
                s_end = sub.get("end")
                if has_duration and isinstance(s_start, (int, float)) and s_start > duration:
                    errors.append(
                        f"{sub_path}/start: start={s_start}がシーン長{duration}を超えています"
                    )
                if has_duration and isinstance(s_end, (int, float)) and s_end > duration + 0.01:
                    errors.append(
                        f"{sub_path}/end: end={s_end}がシーン長{duration}を超えています"
                    )
                if (isinstance(s_start, (int, float)) and isinstance(s_end, (int, float))
                        and s_end <= s_start):
                    errors.append(f"{sub_path}: end({s_end}) <= start({s_start})")
                # 隣接 anchor の順序違反: 前 chunk の end が次 chunk の start より大きい。
                # _resolve_subtitle_timings は片方を silent に上書きするため、ここで早期 reject。
                if (isinstance(s_end, (int, float)) and sub_idx + 1 < len(subs)):
                    next_sub = subs[sub_idx + 1] or {}
                    next_start = next_sub.get("start")
                    if (isinstance(next_start, (int, float))
                            and next_start + 0.001 < s_end):
                        errors.append(
                            f"{sub_path}: end({s_end}) が次 chunk の "
                            f"start({next_start}) を超えています (隣接 anchor の "
                            f"順序違反 — そのままだと字幕が silent に消える)"
                        )
    return errors


def _resolve_scene_location_ref(scene: dict) -> str | None:
    """scene から location_ref を解決する (= identity / scene root flat の順)。

    concrete snapshot は identity.location_ref、abstract / snapshot 直書きは
    scene root の flat location_ref を持つ。両形式を許容する。
    """
    ident = scene.get("identity")
    if isinstance(ident, dict):
        ref = ident.get("location_ref")
        if isinstance(ref, str) and ref:
            return ref
    ref = scene.get("location_ref")
    if isinstance(ref, str) and ref:
        return ref
    return None


def _check_location_refs(screenplay: dict) -> list[str]:
    """scene の location_ref が グローバル locations/<id>.json に存在するか検証。"""
    from analyze import location as loc_mod
    errors: list[str] = []
    available = set(loc_mod.list_locations())
    for s_idx, scene in enumerate(screenplay.get("scenes", [])):
        ref = _resolve_scene_location_ref(scene)
        if ref is None:
            continue
        if ref not in available:
            keys = ", ".join(sorted(available)) or "(空)"
            errors.append(
                f"scenes/{s_idx}/location_ref: '{ref}' は locations/ に未定義 "
                f"(定義済み: {keys})"
            )
    return errors


def _check_character_refs(screenplay: dict) -> list[str]:
    """character ref が characters/ ディレクトリに物理存在するか検証する。

    対象:
        featured_characters / scene.character_selection /
        scene.identity.character_refs / line.speaker (= resolved id 必須)

    characters/ が空 (= テスト環境) の場合は検証スキップする。
    Stage 3 (Imagen 背景合成) でファイル参照失敗するのを台本作成段階で弾くのが
    目的。

    2026-05-17 schema 撤廃: 旧 raw 匿名 ID (= `speaker_N` 形式) は禁止。
    紛れていれば validator が reject する (= migration 漏れの検知)。
    """
    import re
    from analyze import character_meta as cmeta_mod
    errors: list[str] = []
    available = set(cmeta_mod.list_character_images())
    if not available:
        return errors

    available_str = ", ".join(sorted(available))
    raw_re = re.compile(r"^speaker_\d+$", re.IGNORECASE)

    def _missing(ref: str) -> bool:
        return isinstance(ref, str) and bool(ref) and ref not in available

    for ref in screenplay.get("featured_characters") or []:
        if _missing(ref):
            errors.append(
                f"featured_characters: '{ref}' は characters/ に未定義 "
                f"(定義済み: {available_str})",
            )

    for s_idx, scene in enumerate(screenplay.get("scenes") or []):
        sel = scene.get("character_selection")
        if isinstance(sel, list):
            for ref in sel:
                if _missing(ref):
                    errors.append(
                        f"scenes/{s_idx}/character_selection: '{ref}' は "
                        f"characters/ に未定義",
                    )
        ident = scene.get("identity")
        if isinstance(ident, dict):
            for ref in ident.get("character_refs") or []:
                if _missing(ref):
                    errors.append(
                        f"scenes/{s_idx}/identity/character_refs: '{ref}' は "
                        f"characters/ に未定義",
                    )
        for l_idx, line in enumerate(scene.get("lines") or []):
            sp = line.get("speaker")
            if not isinstance(sp, str) or not sp:
                continue
            # 旧 raw 匿名 ID (= 撤廃済) → migration 漏れとして reject
            if raw_re.match(sp):
                errors.append(
                    f"scenes/{s_idx}/lines/{l_idx}/speaker: '{sp}' は旧 raw "
                    "匿名 ID 形式 (= 2026-05-17 schema 撤廃)。"
                    "scripts/migrate_speaker_schema.py で resolved id に変換してください",
                )
                continue
            if sp not in available:
                errors.append(
                    f"scenes/{s_idx}/lines/{l_idx}/speaker: '{sp}' は "
                    f"characters/ に未定義",
                )
    return errors


# ───────────── part_registry (visual_intents) 整合性チェック ─────────────
#
# scenes[].annotation.visual_intent_id が `config/part_registry/visual_intents.yaml`
# に存在し、かつ id ごとの valid_start_emotions 制約を満たすことを検証する。
# 不正 id は **fast fail** で reject (= clip_library lookup の遅い throw を防ぐ)。
# yaml が無い場合 (= 半完成 deployment) は警告ログのみで pass。
#
# yaml load + cache は part_registry_loader (= SSOT) に集約。テストからは
# reset_part_registry_cache() を呼ぶと SSOT cache がクリアされる。

import part_registry_loader as _registry


def reset_part_registry_cache() -> None:
    """テスト用: yaml を読み直すための cache クリア (= SSOT cache を消す)。"""

    _registry.reset_cache()


def _check_part_registry(screenplay: dict) -> list[str]:
    """scenes[].annotation.visual_intent_id の整合性を検証。

    1. id が visual_intents.yaml に存在するか
    2. id ごとの valid_start_emotions に scene の start_emotion が含まれるか
    """

    errors: list[str] = []
    intent_ids = _registry.list_ids("visual_intents")
    intent_valid_emotions = _load_visual_intent_valid_emotions()

    for s_idx, scene in enumerate(screenplay.get("scenes", []) or []):
        ann = scene.get("annotation") or {}
        if not isinstance(ann, dict):
            continue
        vi = ann.get("visual_intent_id")
        if not isinstance(vi, str):
            continue
        if intent_ids and vi not in intent_ids:
            errors.append(
                f"scenes/{s_idx}/annotation/visual_intent_id: "
                f"'{vi}' は config/part_registry/visual_intents.yaml に未定義"
            )
            continue
        # valid_start_emotions 制約 (= id 不正は上で reject 済み)
        valid_emos = intent_valid_emotions.get(vi)
        if valid_emos:
            start_emo = _resolve_scene_start_emotion(scene)
            if start_emo is not None and start_emo not in valid_emos:
                allowed = ", ".join(sorted(valid_emos))
                errors.append(
                    f"scenes/{s_idx}/annotation/visual_intent_id: "
                    f"'{vi}' の valid_start_emotions "
                    f"({allowed}) に start_emotion='{start_emo}' は含まれない"
                )

    return errors


def _load_visual_intent_valid_emotions() -> dict[str, frozenset[str]]:
    """visual_intents.yaml の id → valid_start_emotions(frozenset) map を返す。"""

    out: dict[str, frozenset[str]] = {}
    for entry in _registry.load_registry("visual_intents"):
        eid = entry.get("id")
        if not isinstance(eid, str):
            continue
        emos = entry.get("valid_start_emotions") or []
        if isinstance(emos, list):
            out[eid] = frozenset(e for e in emos if isinstance(e, str))
    return out


def _resolve_scene_start_emotion(scene: dict) -> str | None:
    """scene から start_emotion を解決する (= identity / lines[0].emotion の順)。"""

    ident = scene.get("identity")
    if isinstance(ident, dict):
        emo = ident.get("start_emotion")
        if isinstance(emo, str) and emo:
            return emo
    lines = scene.get("lines") or []
    for line in lines:
        if not isinstance(line, dict):
            continue
        emo = line.get("emotion")
        if isinstance(emo, str) and emo:
            return emo
    return None


def _check_composed_required(screenplay: dict) -> list[str]:
    """composed 形式 (= Stage 2 以降が読む形) で必須のフィールドをチェック。

    abstract 形式では `background_prompt` が未生成でも許容するが、後段
    (TTS / 背景 / Kling) に渡す直前にはこの形に解決済みである必要がある。

    Phase X-2a: scene に ``action_id`` がある場合は atomic SSOT 経路で
    ``background_prompt`` が scene_gen 側で派生されるため、composed 必須
    チェックの対象外とする。
    """
    errors: list[str] = []
    for s_idx, scene in enumerate(screenplay.get("scenes", []) or []):
        if scene.get("action_id"):
            continue
        bg = scene.get("background_prompt")
        if not isinstance(bg, str) or not bg.strip():
            errors.append(
                f"scenes/{s_idx}/background_prompt: composed 形式では必須 "
                "(abstract 形式なら compose を経由してください)",
            )
    return errors


def _check_atomic_refs(screenplay: dict) -> list[str]:
    """Phase X-2a: hook_id / arc_id / scenes[].action_id が atomic SSOT に存在するか検証。

    atomic_assets.list_*_ids() 経由で hooks/ arcs/ actions/ ディレクトリの中身と
    照合する。空集合 (= テスト環境で SSOT を置いていない) の場合はスキップする
    (= scene 側の参照が存在しないだけのチェックを通す)。
    """
    errors: list[str] = []

    available_hooks = set(atomic_assets.list_hook_ids())
    hook_id = screenplay.get("hook_id")
    if isinstance(hook_id, str) and hook_id and available_hooks:
        if hook_id not in available_hooks:
            keys = ", ".join(sorted(available_hooks)) or "(空)"
            errors.append(
                f"hook_id: '{hook_id}' は hooks/ に未定義 (定義済み: {keys})",
            )

    available_arcs = set(atomic_assets.list_arc_ids())
    arc_id = screenplay.get("arc_id")
    if isinstance(arc_id, str) and arc_id and available_arcs:
        if arc_id not in available_arcs:
            keys = ", ".join(sorted(available_arcs)) or "(空)"
            errors.append(
                f"arc_id: '{arc_id}' は arcs/ に未定義 (定義済み: {keys})",
            )

    available_actions = set(atomic_assets.list_action_ids())
    if available_actions:
        for s_idx, scene in enumerate(screenplay.get("scenes") or []):
            action_id = scene.get("action_id")
            if not isinstance(action_id, str) or not action_id:
                continue
            if action_id not in available_actions:
                keys = ", ".join(sorted(available_actions)) or "(空)"
                errors.append(
                    f"scenes/{s_idx}/action_id: '{action_id}' は actions/ "
                    f"に未定義 (定義済み: {keys})",
                )

    return errors


def validate_screenplay(screenplay: dict,
                         strict: bool = True,
                         require_composed: bool = True) -> list[str]:
    """台本 JSON を検証する。

    Args:
        screenplay: 検証対象 dict
        strict: True なら検出エラーで raise する。False ならエラー list を返す
        require_composed: True なら composed 形式必須項目 (= background_prompt)
            までチェックする。False なら abstract 形式 (= snapshot 直書き) でも
            通る。Stage 2 以降に渡す直前は True、PUT abstract / pipeline 出力
            検証は False を渡す
    """
    errors: list[str] = []

    for err in _VALIDATOR.iter_errors(screenplay):
        path = "/".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{path}: {err.message}")

    errors.extend(_check_line_bounds(screenplay))
    errors.extend(_check_location_refs(screenplay))
    errors.extend(_check_character_refs(screenplay))
    errors.extend(_check_atomic_refs(screenplay))
    errors.extend(_check_part_registry(screenplay))
    if require_composed:
        errors.extend(_check_composed_required(screenplay))

    if strict and errors:
        raise ValueError(
            "台本バリデーションエラー:\n" + "\n".join(f"  - {e}" for e in errors)
        )
    return errors


def validate_abstract(abstract: dict, strict: bool = True) -> list[str]:
    """abstract 形式 (= snapshot 直書き) 用の軽量 validate。

    `validate_screenplay(..., require_composed=False)` のショートカット。
    PUT /api/projects/<ts>/abstract 等で使用。
    """
    return validate_screenplay(abstract, strict=strict, require_composed=False)
