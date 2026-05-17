"""抽象台本 → 完全 screenplay の合成 (決定論的)。

各シーンが自分自身で持つフィールドだけで完結する:
  - scene.animation_style ("subtle" | "standard" | "expressive")
  - scene.location_ref (locations/<id>.json)
  - scene.character_selection (= featured_characters の subset)

ロケ詳細は locations/<id>.json から、キャラ voice は characters/<id>.json から
グローバルに引き当てる。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from analyze import character_meta as cmeta_mod
from analyze import location as loc_mod

logger = logging.getLogger(__name__)

# raw 匿名 ID (= speaker_1, speaker_2, ...) — frontend collectRawSpeakers と
# 同じ正規表現で判定する。"speaker_xyz" のような変則値は ref 扱い。
_RAW_SPEAKER_RE = re.compile(r"^speaker_\d+$", re.IGNORECASE)


_CAMERA_LABELS = {
    "close-up": "close-up shot",
    "medium-close": "medium close-up shot",
    "medium": "medium shot",
    "wide": "wide shot",
}

_ANIMATION_STYLE_MODIFIERS = {
    "subtle": "with minimal hand movement, mostly facial expression",
    "standard": "with natural hand gestures and body language",
    "expressive": "with energetic gestures and pronounced movement",
}

DEFAULT_ANIMATION_STYLE = "standard"


def _resolve_line_speaker(
    raw_speaker: str | None,
    available_refs: list[str],
    fallback_ref: str | None,
) -> str | None:
    """line.speaker を ref に解決する (= 2026-05-17 schema 撤廃版)。

    `speaker_to_ref` mapping schema は撤廃 (= analyze が resolved id を
    直接書く方式に変更)。本関数は line.speaker の検証 + fallback のみ。

    優先順位:
      1. raw_speaker が available_refs に含まれる ref → そのまま
      2. raw_speaker が空 (= 単一キャラ動画) → fallback_ref
      3. 未解決 (= 未知 ref) → None
    """
    if not raw_speaker:
        return fallback_ref
    if raw_speaker in available_refs:
        return raw_speaker
    return None


def diagnose_abstract(abstract: dict) -> dict:
    """compose 出力の品質に影響する不整合を抽出する (UI 警告バナー用)。

    2026-05-17 schema 撤廃: `speaker_to_ref` / `speaker_profiles` を廃止し
    line.speaker に resolved id を直書きするモデルに変更。`unmapped_speakers`
    キーは互換のため空配列で返すが、検出対象としては raw `speaker_N` 形式の
    残骸 (= 旧 snapshot の遺物) を集める。

    Returns:
        {
          "unmapped_speakers": [str, ...],          # 旧 raw speaker_N の残骸 (= 撤廃後は migration 漏れ検知用)
          "scenes_without_location": [int, ...],    # location_ref 未設定のシーン idx
          "scenes_without_characters": [int, ...],  # character_selection=[] かつ
                                                     # speaker からの推論も空のシーン
          "invalid_camera_distance": [{...}, ...],  # _CAMERA_LABELS にない値
          "unknown_character_refs": {               # characters/ に存在しない ref
              "featured": [str, ...],
              "character_selection": [{scene_idx, ref}, ...],
              "speaker": [{scene_idx, line_idx, ref}, ...],
          },
        }
    """
    from analyze import character_meta as cmeta_mod

    featured = [str(c) for c in (abstract.get("featured_characters") or []) if c]
    available_chars = set(cmeta_mod.list_character_images())

    raw_speaker_residue: set[str] = set()
    no_location: list[int] = []
    no_characters: list[int] = []
    invalid_camera: list[dict] = []

    unknown_refs: dict[str, list] = {
        "featured": [],
        "character_selection": [],
        "speaker": [],
    }

    def _ref_unknown(ref: object) -> bool:
        # characters/ が空 (= テスト環境) なら検証スキップ
        if not available_chars:
            return False
        return isinstance(ref, str) and bool(ref) and ref not in available_chars

    for ref in featured:
        if _ref_unknown(ref):
            unknown_refs["featured"].append(ref)

    for s_idx, src in enumerate(abstract.get("scenes") or []):
        if not src.get("location_ref"):
            no_location.append(s_idx)

        cd = src.get("camera_distance")
        if cd is not None and cd not in _CAMERA_LABELS:
            invalid_camera.append({"scene_idx": s_idx, "value": cd})

        sel = src.get("character_selection")
        if isinstance(sel, list):
            for ref in sel:
                if _ref_unknown(ref):
                    unknown_refs["character_selection"].append(
                        {"scene_idx": s_idx, "ref": ref},
                    )

        for l_idx, line in enumerate(src.get("lines") or []):
            sp = line.get("speaker")
            if not sp:
                continue
            if isinstance(sp, str) and _RAW_SPEAKER_RE.match(sp):
                # 旧 raw 形式の残骸 (= migration 漏れ)
                raw_speaker_residue.add(sp)
                continue
            # raw 形式で無い値は ref として扱われる前提
            if _ref_unknown(sp):
                unknown_refs["speaker"].append(
                    {"scene_idx": s_idx, "line_idx": l_idx, "ref": sp},
                )

        # シーン人物推論を再現して 0 人になるかチェック
        if "character_selection" in src:
            sel = src.get("character_selection") or []
            if isinstance(sel, list) and len(sel) == 0:
                no_characters.append(s_idx)
            continue
        speakers = {
            l.get("speaker") for l in src.get("lines") or []
            if l.get("speaker")
        }
        resolved = {sp for sp in speakers if sp in featured}
        if not resolved and not featured:
            no_characters.append(s_idx)

    return {
        "unmapped_speakers": sorted(raw_speaker_residue),
        "scenes_without_location": no_location,
        "scenes_without_characters": no_characters,
        "invalid_camera_distance": invalid_camera,
        "unknown_character_refs": unknown_refs,
    }


def compose_screenplay(abstract: dict) -> dict:
    """抽象台本を完全 screenplay に変換する。

    **pass-through 契約 (= Phase A 不変条件)**:
    本関数は abstract に書かれた **すべての非派生フィールド** をそのまま
    compose 後にも残す。compose は派生フィールドを **追加** するだけで、
    abstract の他キーは破壊しない。

    派生フィールド (= compose が生成 / 上書きする):
      - root: caption は明示的に str 化
      - scene: characters / character_refs / location_ref / lipsync /
               background_prompt / animation_prompt / identity (条件付き) /
               lines[].speaker (= ref 解決) / lines[].voice_overrides (= キャラ
               base voice + line 個別 override の merge)

    保持フィールド (= 旧実装で silent strip されていたもの):
      - root: featured_characters / speaker_to_ref / subtitle_y_from_bottom /
              hook_id / arc_id / その他 root keys
      - scene: action_id / annotation / camera_distance /
               duration / animation_style / character_selection /
               _override_background_prompt / _override_animation_prompt /
               旧 alias (start_emotion / visual_intent_id / duration_bucket /
               motion_intensity の flat) / その他 scene keys

    voice_overrides は characters/<id>.json から引く。
    """
    featured = abstract.get("featured_characters") or []
    char_ids = [str(c) for c in featured if c]

    voice_by_id: dict[str, dict] = {}
    for cid in char_ids:
        try:
            meta = cmeta_mod.load_character_meta(cid)
            voice_by_id[cid] = dict(meta.voice_overrides)
        except Exception as e:
            logger.warning("character meta 読み込み失敗 %s: %s", cid, e)
            voice_by_id[cid] = {}

    fallback_ref = char_ids[0] if char_ids else None
    default_voice = voice_by_id.get(fallback_ref or "", {}) if fallback_ref else {}

    # ── pass-through 起点: abstract の root を shallow copy ──
    # caption は str に正規化、scenes は新規 list (= 各 scene を src 起点で
    # 構築するため後で上書き)。それ以外の非派生 key (featured_characters /
    # subtitle_y_from_bottom / hook_id / arc_id 等) はそのまま残る。
    # speaker_to_ref / speaker_profiles は 2026-05-17 schema 撤廃で消える。
    sp: dict[str, Any] = dict(abstract)
    sp["caption"] = abstract.get("caption", "")
    sp["scenes"] = []
    # 旧 schema の残骸を drop (= 古い snapshot との後方互換)
    sp.pop("speaker_to_ref", None)
    sp.pop("speaker_profiles", None)

    for i, src in enumerate(abstract.get("scenes") or []):
        scene_anim = src.get("animation_style") or DEFAULT_ANIMATION_STYLE
        scene_chars = _resolve_scene_characters(src, char_ids)
        location_ref = src.get("location_ref") or ""

        # ── pass-through 起点: src scene を shallow copy ──
        # 旧 alias / action_id / その他 abstract 由来 key を
        # すべて維持する。下で派生フィールドを上書き。
        scene: dict[str, Any] = dict(src)
        # flat schema (Phase 5 撤去): src 由来の flat alias を pop。
        # downstream はすべて nested identity 経由で読む。
        scene.pop("character_refs", None)
        scene.pop("location_ref", None)
        scene.pop("camera_distance", None)
        # 派生フィールド (= compose が常に生成する)
        scene["characters"] = [{"name": cid} for cid in scene_chars]
        scene["lipsync"] = True
        scene["lines"] = []   # 下で line 個別 voice merge 後に再構築
        if "duration" in src:
            scene["duration"] = float(src["duration"])

        # ── Step 2: identity 派生 (= clip_library cache 鍵) ──
        # 必須フィールド (location_ref / start_emotion / camera_distance) が
        # 揃っていれば scene["identity"] を必ず入れる。character_refs は空でも
        # 許容 (= 背景のみシーン)。必須欠落は ValueError で fail-fast し、
        # 部分 identity を生成しない (= 不変条件 #2: 誤 hit 防止)。
        # _derive_identity / _compose_background は scene の flat field を
        # 参照する設計のため、derive / background_prompt 生成前に temporary に
        # flat を注入し、生成後に pop する。
        scene["character_refs"] = list(scene_chars)
        scene["location_ref"] = location_ref
        if src.get("camera_distance"):
            scene["camera_distance"] = src["camera_distance"]
        scene["identity"] = _derive_identity(scene, src)

        scene["background_prompt"] = _compose_background(scene, location_ref)
        scene["animation_prompt"] = _compose_animation(src, scene_anim)

        # temporary flat の片付け (= flat schema は Phase 5 で撤去済)
        scene.pop("character_refs", None)
        scene.pop("location_ref", None)
        scene.pop("camera_distance", None)

        for line in src.get("lines") or []:
            new_line = dict(line)
            raw_speaker = line.get("speaker")
            resolved_ref = _resolve_line_speaker(
                raw_speaker, char_ids, fallback_ref,
            )
            # line 個別の voice_overrides は キャラの base voice よりも優先する
            # (= UI から line に直接書いた override は compose で潰さない)
            line_explicit = dict(line.get("voice_overrides") or {})
            if resolved_ref:
                new_line["speaker"] = resolved_ref
                base_voice = voice_by_id.get(resolved_ref) or {}
                merged = {**base_voice, **line_explicit}
                if merged:
                    new_line["voice_overrides"] = merged
            else:
                new_line.pop("speaker", None)
                merged = {**default_voice, **line_explicit}
                if merged:
                    new_line["voice_overrides"] = merged
                if raw_speaker:
                    logger.warning(
                        "speaker '%s' を ref に解決できませんでした (scene=%d)",
                        raw_speaker, i,
                    )
            scene["lines"].append(new_line)

        sp["scenes"].append(scene)

    return sp


def _derive_identity(
    composed_scene: dict, src_scene: dict
) -> dict:
    """clip_library の hard match キー (= identity) を派生する。

    必須フィールド (location_ref / start_emotion) が欠けていれば ValueError を
    投げる (= 部分 identity は作らず fail-fast)。character_refs は空でも許容し
    (= 背景のみシーン)、camera_distance は scene > location 既定 >
    "medium-close" の優先順位で fallback する。

    各フィールドの調達元:
      - character_refs: composed scene が解決した list (= 順不同に sorted で
        正規化、cache 鍵の同等性を確保)。空 list は背景のみシーン扱い
      - location_ref: src 由来の string、空文字列は不在扱い (= ValueError)
      - start_emotion: lines[0].emotion (= シーン冒頭の表情、bg.png 生成時点)
      - camera_distance: src.camera_distance > location 既定 > "medium-close"

    必須欠落で ValueError を投げる理由: cache の hard match 鍵に半端な値を
    入れると別シーンと誤 hit して見た目崩壊する (= 不変条件 #2)。analyze
    pipeline が identity を SSOT として常に produce する責務を負う。
    """

    char_refs = composed_scene.get("character_refs") or []

    location_ref = composed_scene.get("location_ref") or ""
    if not location_ref:
        raise ValueError(
            "_derive_identity: location_ref が空です。analyze pipeline は "
            "全シーンに location_ref を必ず設定する必要があります。",
        )

    lines = src_scene.get("lines") or []
    start_emotion: str | None = None
    for line in lines:
        emo = line.get("emotion")
        if isinstance(emo, str) and emo:
            start_emotion = emo
            break
    if not start_emotion:
        raise ValueError(
            "_derive_identity: start_emotion が決定できません "
            "(lines[*].emotion がすべて空)。analyze pipeline は各シーンの "
            "lines に必ず emotion を 1 つ以上設定する必要があります。",
        )

    camera_distance = composed_scene.get("camera_distance")
    if not camera_distance:
        # location 既定を引き当てる (= scene 未指定時の SSOT)
        try:
            base_loc = loc_mod.load_location(location_ref)
            camera_distance = base_loc.camera_distance or None
        except FileNotFoundError:
            camera_distance = None
    if not camera_distance:
        camera_distance = "medium-close"

    # 順不同性を保証して cache 鍵を安定化 (= clip_library.ClipIdentity も
    # char_set() で順不同 match するが、scene["identity"] 自体も sorted で
    # 統一しておくと register / lookup の dict 比較が偶然壊れない)
    return {
        "character_refs": sorted(char_refs),
        "location_ref": location_ref,
        "start_emotion": start_emotion,
        "camera_distance": camera_distance,
    }


def _resolve_scene_characters(
    src_scene: dict,
    available_ids: list[str],
) -> list[str]:
    """シーンに登場するキャラ ID のリストを解決する。

    優先順位:
      1. ``src_scene["character_selection"]`` が **明示的に存在** すれば、その
         ID list を available_ids と突合せて選ぶ (= ユーザの override)。
         - ``[]`` (空 list)         = 登場人物 0 人 (背景だけ生成)
         - ``[...]``                = 指定された ID のキャラだけ
      2. lines[].speaker (= resolved id) から出現する ref の subset。
         multi-speaker 動画はここで自動的に「シーンに映るキャラ」が決まる。
      3. fallback: 全 available_ids (= 単一キャラ動画 / speaker タグ無しシーン)
    """
    if "character_selection" in src_scene:
        selection = src_scene.get("character_selection") or []
        if not isinstance(selection, list):
            raise ValueError(
                f"character_selection は list である必要があります: {selection!r}",
            )
        wanted = set(selection)
        return [cid for cid in available_ids if cid in wanted]

    speakers = {
        l.get("speaker") for l in src_scene.get("lines") or []
        if l.get("speaker")
    }
    resolved: set[str] = set()
    for sp in speakers:
        if sp in available_ids:
            resolved.add(sp)
    if resolved:
        return [cid for cid in available_ids if cid in resolved]

    return list(available_ids)


def _subject_phrase(num_chars: int) -> str:
    """登場人数から人物表現を派生させる (= キャラ ID は reference 画像が SSOT)。

    1 人 → the depicted subject
    2 人 → the two depicted people facing each other in conversation
    N 人 (>=3) → a group of {N} depicted people
    0 人 → no people, scenery only
    """
    if num_chars == 0:
        return "no people, scenery only"
    if num_chars == 1:
        return "the depicted subject"
    if num_chars == 2:
        return "the two depicted people facing each other in conversation"
    return f"a group of {num_chars} depicted people"


def _compose_background(scene: dict, location_ref: str) -> str:
    """カメラ距離 + 人物表現の 1 文を返す (決定論的・英文)。

    ロケ詳細 (decor/lighting/color_palette/props) は SSOT 1 箇所 = scene_gen の
    `_build_background_prompt` で `locations/<id>.json` から直接注入する
    (= compose 側では引かない、二重注入を避ける)。
    camera_distance だけはここで 1 回だけ解決する (= scene_gen 側でも引かない、
    1 値の SSOT 経路を確保するため)。
    衣装は characters/<id>.png reference 画像が SSOT (prompt 側では触れない)。
    """
    base_loc = None
    if location_ref:
        try:
            base_loc = loc_mod.load_location(location_ref)
        except FileNotFoundError:
            logger.warning("location '%s' が見つかりません", location_ref)

    camera_distance = (
        scene.get("camera_distance")
        or (base_loc.camera_distance if base_loc else None)
        or "medium"
    )
    if camera_distance not in _CAMERA_LABELS:
        logger.warning(
            "camera_distance '%s' は未知の値です (allowed=%s)。'medium' にフォールバック",
            camera_distance, sorted(_CAMERA_LABELS.keys()),
        )
        camera_distance = "medium"

    characters = scene.get("characters") or []
    distance_label = _CAMERA_LABELS[camera_distance]
    subject = _subject_phrase(len(characters))
    if len(characters) == 0:
        return f"{distance_label}, {subject}"
    return f"{distance_label} of {subject}"


def _compose_animation(src_scene: dict, animation_style: str) -> str:
    """emotion arc + animation_style から 1 文を生成 (英語)。

    arc は config.EMOTION_EN で日本語 emotion を英訳する (= プロンプト完全英文化)。
    """
    import config as _config
    emotions = [
        l.get("emotion") for l in src_scene.get("lines") or []
        if l.get("emotion")
    ]
    arc_parts: list[str] = []
    seen: set[str] = set()
    for e in emotions:
        if e not in seen:
            arc_parts.append(_config.EMOTION_EN.get(e, e))
            seen.add(e)
    arc = " → ".join(arc_parts) if arc_parts else "neutral"

    modifier = _ANIMATION_STYLE_MODIFIERS.get(
        animation_style, _ANIMATION_STYLE_MODIFIERS["standard"],
    )
    return (
        f"subject speaks naturally following the emotion arc ({arc}), "
        f"{modifier}"
    )
