import glob
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess as sp
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image

import config
import elevenlabs_client
import fal_video_client
import imagen_client
import lipsync_client

SCREENPLAY_TEXT_SEPARATOR = "  "  # 半角スペース×2: line間/scene間の区切り

logger = logging.getLogger(__name__)

BG_PARALLEL_WORKERS = 4


def _dominant_emotion(scene: dict) -> str | None:
    emotions = [l.get("emotion") for l in (scene.get("lines") or []) if l.get("emotion")]
    if not emotions:
        return None
    from collections import Counter
    return Counter(emotions).most_common(1)[0][0]


def _emotion_arc_summary(scene: dict, cue_key: str) -> str:
    """lines[].emotion ごとに EMOTION_VISUAL_CUES[cue_key] を引き、" → " 連結。

    例: ["焦り", "焦り", "満足"] + "motion" →
        "rushed forward-leaning movement → rushed forward-leaning movement →
         relaxed open posture"
    """
    cues: list[str] = []
    for line in scene.get("lines", []) or []:
        emo = line.get("emotion")
        if not emo:
            continue
        v = config.EMOTION_VISUAL_CUES.get(emo, {}).get(cue_key)
        if v:
            cues.append(v)
    # 連続重複を畳む (見栄え対策)
    deduped: list[str] = []
    for c in cues:
        if not deduped or deduped[-1] != c:
            deduped.append(c)
    return " → ".join(deduped)


def _dominant_visual_cues(scene: dict) -> dict:
    """EMOTION_VISUAL_CUES の dominant emotion 既定 cue に
    scene.emotion_cue_overrides (preset ID → 実テキスト) を上書き適用する。

    overrides の値は preset ID で、validator が enum を保証する。
    library lookup で実テキストに展開してから cue dict にマージ。
    """
    dom = _dominant_emotion(scene)
    cues: dict = dict(config.EMOTION_VISUAL_CUES.get(dom or "", {}))
    overrides = scene.get("emotion_cue_overrides") or {}
    libs = config.PROMPT_PRESET_LIBRARIES
    for category, preset_id in overrides.items():
        lib = libs.get(category)
        if not lib:
            continue
        text = lib.get(preset_id)
        if text:
            cues[category] = text
    return cues


def _scope_matches(scope: dict, scene: dict, s_idx: int) -> bool:
    """scoped_augmentations の scope がこの scene にマッチするか判定。"""
    if not scope:
        return False
    si = scope.get("scene_idx")
    if isinstance(si, list) and s_idx in si:
        return True
    tag = scope.get("tag")
    if tag and tag in (scene.get("tags") or []):
        return True
    return False


def _resolve_scoped_elements(screenplay: dict | None, scene: dict,
                              s_idx: int | None) -> list[str]:
    """このシーンに適用される scoped_augmentations の要素を実テキスト展開して返す。"""
    if not screenplay or s_idx is None:
        return []
    out: list[str] = []
    seen: set[str] = set()
    elements_lib = config.SCENE_ELEMENT_PRESETS
    for aug in screenplay.get("scoped_augmentations") or []:
        if not _scope_matches(aug.get("scope") or {}, scene, s_idx):
            continue
        for elem_id in aug.get("elements") or []:
            text = elements_lib.get(elem_id)
            if text and text not in seen:
                out.append(text)
                seen.add(text)
    return out


def _get_animation_prompt(scene: dict, ts_path: str | None = None,
                          s_idx: int | None = None,
                          screenplay: dict | None = None) -> str:
    """Kling 用 animation_prompt を合成する (SSOT準拠)。

    入力は SSOT のみ:
      - scene.animation_prompt (シーン固有の動作・ベース文)
      - lines[].emotion (per-line) → EMOTION_VISUAL_CUES (motion/facial/camera/tone)
      - tts_<S>_<L>.mp3 (TTS生成済みなら) → audio_dynamics

    廃止フィールド (scene.facial_expression / hand_gesture) は読まない。
    """
    explicit = scene.get("animation_prompt")
    bg_prompt = scene.get("background_prompt", "")
    base = explicit if explicit else f"gentle cinematic motion, {bg_prompt}"

    extras: list[str] = []

    motion_arc = _emotion_arc_summary(scene, "motion")
    if motion_arc:
        extras.append(f"motion arc: {motion_arc}")

    facial_arc = _emotion_arc_summary(scene, "facial")
    if facial_arc:
        extras.append(f"facial arc: {facial_arc}")

    dom_cues = _dominant_visual_cues(scene)
    if dom_cues.get("camera"):
        extras.append(f"camera: {dom_cues['camera']}")
    if dom_cues.get("tone"):
        extras.append(f"tone: {dom_cues['tone']}")
    # override で書かれることが多いカテゴリ (Kling は人物動作プロンプトなので)
    if dom_cues.get("eye_gaze"):
        extras.append(f"eye gaze: {dom_cues['eye_gaze']}")
    if dom_cues.get("body_posture"):
        extras.append(f"body posture: {dom_cues['body_posture']}")
    if dom_cues.get("hair"):
        extras.append(f"hair: {dom_cues['hair']}")

    # 横断適用ルール (scoped_augmentations) の要素注入
    scoped = _resolve_scoped_elements(screenplay, scene, s_idx)
    if scoped:
        extras.append("scene elements: " + ", ".join(scoped))

    # TTS 音響特徴 (TTS 生成済みのときだけ)
    if ts_path is not None and s_idx is not None:
        try:
            import audio_dynamics
            dyn = audio_dynamics.summarize_scene_dynamics(
                scene.get("lines") or [], ts_path, s_idx)
            if dyn:
                extras.append(dyn)
        except Exception as e:
            logger.warning("audio_dynamics サマリ失敗: %s", e)

    if extras:
        return f"{base}, " + ", ".join(extras)
    return base


def _clean_text(text: str) -> str:
    text = re.sub(r'^\d+[\.\)）]\s*', '', text)
    text = re.sub(r'[（(][^）)]*[）)]\s*', '', text)
    text = re.sub(r'[,.、。「」『』]', '', text)
    # 稀な記号を v3 が解釈しやすい一般形に正規化
    text = text.replace('⁉', '!?').replace('‼', '!!').replace('⁇', '??')
    text = text.replace('〜', 'ー').replace('~', 'ー')
    text = re.sub(r'[…―—]', '', text)
    return text.strip()


def _apply_pronunciation_hints(text: str, hints: dict | None,
                                global_dict: dict | None = None) -> str:
    """global furigana dict + line.pronunciation_hints をmergeしてテキスト置換。

    line.hints が同じkeyを持つ場合は line.hints が優先（line別オーバーライド）。
    """
    effective: dict[str, str] = {}
    if global_dict:
        effective.update(global_dict)
    if hints:
        effective.update(hints)
    if not effective:
        return text
    for src in sorted(effective.keys(), key=len, reverse=True):
        dst = effective[src]
        if src:
            text = text.replace(src, dst)
    return text


def _load_global_furigana_dict() -> dict[str, str]:
    try:
        import furigana_store
        return furigana_store.load()
    except Exception as e:
        logger.warning("furigana_store ロード失敗: %s", e)
        return {}


def _wpm_to_rate_pct(wpm: float) -> int:
    if not wpm or wpm <= 0:
        return 0
    delta = (wpm - config.WPM_BASELINE) * config.WPM_RATE_GAIN * 100
    bound = config.WPM_RATE_BOUND_PCT
    return max(-bound, min(bound, int(round(delta))))


def _resolve_voice_settings(line: dict, screenplay: dict | None = None) -> dict:
    """lineの emotion / acoustic / rate / voice_overrides を統合解決する。"""
    settings = {
        "voice_id": config.ELEVENLABS_VOICE_ID,
        "stability": config.ELEVENLABS_VOICE_STABILITY,
        "similarity_boost": config.ELEVENLABS_VOICE_SIMILARITY_BOOST,
        "style": config.ELEVENLABS_VOICE_STYLE,
        "rate_pct": 0,
    }

    emotion = line.get("emotion")
    preset = config.EMOTION_VOICE_PRESETS.get(emotion or "")
    if preset:
        for k in ("stability", "similarity_boost", "style"):
            if k in preset:
                settings[k] = preset[k]
        settings["rate_pct"] = preset.get("rate_pct", settings["rate_pct"])

    intensity = line.get("emotion_intensity") or "normal"
    intensity_mod = config.EMOTION_INTENSITY_MULTIPLIERS.get(intensity, {})
    if "stability" in intensity_mod:
        settings["stability"] = max(0.0, min(1.0,
            settings["stability"] + intensity_mod["stability"]))
    if "style" in intensity_mod:
        settings["style"] = max(0.0, min(1.0,
            settings["style"] + intensity_mod["style"]))
    if "rate_pct" in intensity_mod:
        settings["rate_pct"] = settings.get("rate_pct", 0) + intensity_mod["rate_pct"]

    acoustic = line.get("acoustic") or {}
    pitch_trend = acoustic.get("pitch_trend")
    if pitch_trend in config.PITCH_TREND_STYLE_DELTA:
        settings["style"] = max(0.0, min(1.0,
            settings["style"] + config.PITCH_TREND_STYLE_DELTA[pitch_trend]))

    rate_str = line.get("rate") or ""
    m = re.match(r'([-+]?\d+)%', rate_str)
    if m:
        settings["rate_pct"] = int(m.group(1))
    elif acoustic.get("wpm"):
        derived = _wpm_to_rate_pct(float(acoustic["wpm"]))
        if derived:
            settings["rate_pct"] = derived

    overrides = line.get("voice_overrides") or {}
    for k in ("voice_id", "stability", "similarity_boost", "style"):
        if k in overrides:
            settings[k] = overrides[k]
    if "rate_pct" in overrides:
        settings["rate_pct"] = overrides["rate_pct"]

    settings["speed"] = 1.0 + settings["rate_pct"] / 100.0
    return settings


def _collect_audio_tags(line: dict) -> list[str]:
    """emotion → audio_tag のマッピング + line.audio_tags を統合した一覧を返す。"""
    tags: list[str] = []
    if getattr(config, "EMOTION_AUDIO_TAGS_ENABLED", True):
        emotion = line.get("emotion") or ""
        tags.extend(config.EMOTION_AUDIO_TAGS.get(emotion, []))
    extra = line.get("audio_tags") or []
    for t in extra:
        t = str(t).strip()
        if t and t not in tags:
            tags.append(t)
    return tags


def _build_tts_text(line: dict, global_dict: dict | None = None) -> str:
    """eleven_v3 audio tag + delivery + 本文 を組み立てた TTS送信用テキストを返す。

    優先順位:
      1. line.tts_text があればそれを完全上書き使用 (pronunciation_hintsスキップ)
      2. それ以外は text + pronunciation_hints + clean_text
    本文の先頭に audio tags ([surprised][happy] 等) と delivery タグを付与する。
    """
    override = (line.get("tts_text") or "").strip()
    if override:
        cleaned = override
    else:
        raw = _apply_pronunciation_hints(
            line["text"], line.get("pronunciation_hints"), global_dict)
        cleaned = _clean_text(raw)

    prefix_parts: list[str] = []
    for tag in _collect_audio_tags(line):
        prefix_parts.append(f"[{tag}]")

    if config.DELIVERY_TAG_ENABLED:
        delivery = (line.get("delivery") or "").strip()
        if delivery:
            delivery = delivery.replace("[", "").replace("]", "")
            prefix_parts.append(f"[{delivery}]")

    if not prefix_parts:
        return cleaned
    return " ".join(prefix_parts) + " " + cleaned


def _rms_to_volume_db(rms_peak: float) -> float | None:
    if rms_peak is None or rms_peak <= 0:
        return None
    if rms_peak < config.RMS_VOLUME_QUIET_THRESHOLD:
        return config.RMS_VOLUME_QUIET_DB
    if rms_peak > config.RMS_VOLUME_LOUD_THRESHOLD:
        return config.RMS_VOLUME_LOUD_DB
    return None


def _neighbor_line_text(screenplay: dict | None, scene_idx: int,
                         line_idx: int, direction: str) -> str | None:
    """指定lineの前/後のline.textを取得。シーン境界を跨いで隣接シーンも探索する。

    direction: "prev" または "next"
    """
    if not screenplay:
        return None
    scenes = screenplay.get("scenes", [])
    if scene_idx >= len(scenes):
        return None
    cur_lines = scenes[scene_idx].get("lines") or []

    if direction == "prev":
        if line_idx > 0:
            return cur_lines[line_idx - 1].get("text")
        for s in range(scene_idx - 1, -1, -1):
            prev_lines = scenes[s].get("lines") or []
            if prev_lines:
                return prev_lines[-1].get("text")
        return None

    if direction == "next":
        if line_idx + 1 < len(cur_lines):
            return cur_lines[line_idx + 1].get("text")
        for s in range(scene_idx + 1, len(scenes)):
            next_lines = scenes[s].get("lines") or []
            if next_lines:
                return next_lines[0].get("text")
        return None

    return None


def _trim_internal_pauses(input_path: str, output_path: str) -> None:
    """TTS音声内部の長すぎる無音を圧縮 + 任意でatempoによる速度補正。

    silenceremove: 「stop_silence秒以下の無音は残し、それを超える無音は stop_silence に短縮」
    atempo: 1.0 以外を指定すると速度倍率 (ピッチ維持で時間軸を変える)
    """
    keep_sec = config.TTS_PAUSE_KEEP_MS / 1000.0
    filters = [
        f"silenceremove="
        f"start_periods=0:"
        f"stop_periods=-1:"
        f"stop_silence={keep_sec:.3f}:"
        f"stop_threshold={config.TTS_PAUSE_THRESHOLD_DB}dB"
    ]
    tempo = float(getattr(config, "TTS_TEMPO_MULTIPLIER", 1.0))
    if abs(tempo - 1.0) > 0.001:
        # atempoは1段で 0.5〜2.0 まで有効。それ以上なら多段に分ける必要があるが現状はOK
        filters.append(f"atempo={tempo:.3f}")

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-af", ",".join(filters),
        "-c:a", "libmp3lame", "-q:a", "4",
        output_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Internal pause trim failed: {r.stderr[-500:]}")


def _apply_volume(input_path: str, db: float, output_path: str) -> None:
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter:a", f"volume={db:+.1f}dB",
        "-c:a", "libmp3lame", "-q:a", "4",
        output_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Volume apply failed: {r.stderr[-300:]}")


def _prepare_background(bg_path: str, output_path: str) -> None:
    bg = Image.open(bg_path).convert("RGB")
    bg = bg.resize((config.VIDEO_WIDTH, config.VIDEO_HEIGHT), Image.LANCZOS)
    bg.save(output_path, "PNG")


def _resolve_character_refs(scene: dict) -> list[str]:
    """scene.character_refs (SSOT) から参照画像を解決する。

    旧 characters[].ref への fallback は廃止。validator schema が
    characters[] から ref フィールドを拒否するので存在しえない。
    """
    if "character_refs" in scene:
        names = list(scene.get("character_refs") or [])
    else:
        names = list(config.DEFAULT_CHARACTER_REFS)

    seen: set[str] = set()
    resolved: list[str] = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        ref_path = os.path.join(config.CHARACTERS_DIR, f"{name}.png")
        if os.path.exists(ref_path):
            resolved.append(ref_path)
        else:
            logger.warning("キャラクター参照画像が見つかりません: %s", ref_path)
    return resolved


def _build_background_prompt(scene: dict, screenplay: dict | None = None,
                              ts_path: str | None = None,
                              s_idx: int | None = None) -> str:
    """Imagen 用 background prompt を合成する (SSOT準拠)。

    入力は SSOT のみ:
      - scene.background_prompt (シーン固有のベース文)
      - scene.wardrobe.identifier → root.wardrobe_continuity[id] で1回だけ展開
      - lines[].emotion (per-line) → EMOTION_VISUAL_CUES (lighting/facial/tone)
      - tts_<S>_<L>.mp3 → audio_dynamics

    廃止フィールド (scene.wardrobe.{top,bottom,accessories,hair} /
    scene.facial_expression / hand_gesture / characters[].outfit) は読まない。
    """
    parts: list[str] = [scene.get("background_prompt", "")]

    # 服装: identifier から wardrobe_continuity を1度だけ参照 (SSOT)
    wardrobe = scene.get("wardrobe") or {}
    wardrobe_id = wardrobe.get("identifier")
    if wardrobe_id and screenplay:
        global_wd = (screenplay.get("wardrobe_continuity") or {}).get(wardrobe_id)
        if global_wd:
            parts.append(f"wardrobe (consistent across scenes): {global_wd}")

    # 決定論的 emotion → visual cue 派生 (override preset 適用済み)
    dom_cues = _dominant_visual_cues(scene)
    # 既定 cue + 任意の override カテゴリ (eye_gaze / hair / body_posture 等) を全部出力
    _CUE_LABEL = {
        "lighting": "lighting and color",
        "facial": "facial expression",
        "tone": "tone",
        "eye_gaze": "eye gaze",
        "hair": "hair styling",
        "body_posture": "body posture",
        "camera": "camera",
        "motion": None,  # animation_prompt 側で扱う
    }
    for cat, label in _CUE_LABEL.items():
        if not label:
            continue
        v = dom_cues.get(cat)
        if v:
            parts.append(f"{label}: {v}")

    # 横断適用ルール (scoped_augmentations) の要素注入
    scoped = _resolve_scoped_elements(screenplay, scene, s_idx)
    if scoped:
        parts.append("scene elements: " + ", ".join(scoped))

    # TTS 音響特徴 (TTS 生成済みのときだけ)
    if ts_path is not None and s_idx is not None:
        try:
            import audio_dynamics
            dyn = audio_dynamics.summarize_scene_dynamics(
                scene.get("lines") or [], ts_path, s_idx)
            if dyn:
                parts.append(dyn)
        except Exception as e:
            logger.warning("audio_dynamics サマリ失敗: %s", e)

    chars = scene.get("characters") or []
    if len(chars) > 1:
        # 多人数シーン: name と role のみ列挙 (outfit は廃止、wardrobe_continuity 経由)
        descs = []
        for c in chars:
            d = c.get("name") or "person"
            if c.get("role"):
                d += f" ({c['role']})"
            descs.append(d)
        parts.append(f"characters in scene: {'; '.join(descs)}")

    parts.append(
        "CRITICAL CONSTRAINT: single static image of one moment frozen in time. "
        "NOT a storyboard, NOT comic panels, NOT a grid of images, "
        "NOT multiple frames stacked vertically or horizontally, "
        "NEVER split into multiple panels. Generate ONE coherent single composition only"
    )

    if scene.get("_storyboard_retry_neg"):
        parts.append(scene["_storyboard_retry_neg"])

    return ". ".join(p for p in parts if p)


def _detect_storyboard_image(image_path: str) -> bool:
    """画像が縦に複数パネル（コマ割り）になっているか検出する。

    1/3, 1/2, 2/3 の境界位置で行輝度が急激に変化していたらコマ割り疑い。
    """
    try:
        import cv2
    except ImportError:
        return False

    img = cv2.imread(image_path)
    if img is None:
        return False
    h, w = img.shape[:2]
    if h < 60:
        return False

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    test_rows = [h // 3, h // 2, 2 * h // 3]
    band = max(2, h // 100)
    for y in test_rows:
        if y - band < 0 or y + band > h:
            continue
        above = float(gray[y - band : y].mean())
        below = float(gray[y : y + band].mean())
        diff = abs(above - below)
        if diff > 22:
            logger.info("storyboard detection: row=%d brightness diff=%.1f", y, diff)
            return True
    return False


def _generate_background_with_retry(scene_idx: int, scene: dict, temp_dir: str,
                                     screenplay: dict | None,
                                     max_retries: int = 2) -> tuple[str, str]:
    bg_key, path = _generate_single_background(scene_idx, scene, temp_dir, screenplay)

    attempt = 0
    while _detect_storyboard_image(path) and attempt < max_retries:
        attempt += 1
        try:
            os.remove(path)
        except OSError:
            pass
        logger.warning("シーン%d 背景画像にコマ割り検出 → retry %d/%d",
                       scene_idx + 1, attempt, max_retries)
        scene["_storyboard_retry_neg"] = (
            f"RETRY ATTEMPT {attempt}: ABSOLUTELY single image, "
            "single horizontal frame, no vertical stacking of images, "
            "NEVER multi-panel layout, ONE photograph only"
        )
        bg_key, path = _generate_single_background(scene_idx, scene, temp_dir, screenplay)

    scene.pop("_storyboard_retry_neg", None)

    if attempt >= max_retries and _detect_storyboard_image(path):
        logger.error("シーン%d 背景画像のコマ割り回避失敗。生成画像をそのまま使用", scene_idx + 1)
    return bg_key, path


def _rate_to_speed(rate: str) -> float:
    m = re.match(r'[+]?(\d+)%', rate)
    if m:
        return 1.0 + int(m.group(1)) / 100.0
    return 1.0


def _get_duration(path: str) -> float:
    result = sp.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", path],
        capture_output=True, text=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def _trim_video(input_path: str, duration: float, output_path: str) -> None:
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Video trim failed: {r.stderr[-500:]}")


def _generate_tts(text: str, output_path: str,
                  voice_settings: dict | None = None,
                  previous_text: str | None = None,
                  next_text: str | None = None) -> str | None:
    if not config.ELEVENLABS_API_KEY:
        return None

    import elevenlabs_client

    vs = voice_settings or {
        "voice_id": config.ELEVENLABS_VOICE_ID,
        "stability": config.ELEVENLABS_VOICE_STABILITY,
        "similarity_boost": config.ELEVENLABS_VOICE_SIMILARITY_BOOST,
        "style": config.ELEVENLABS_VOICE_STYLE,
        "speed": 1.0,
    }

    elevenlabs_client.generate_speech_with_timestamps(
        text=text,
        voice_id=vs["voice_id"],
        output_path=output_path,
        stability=vs["stability"],
        similarity_boost=vs["similarity_boost"],
        style=vs["style"],
        speed=vs.get("speed", 1.0),
        language=config.LANGUAGE,
        previous_text=previous_text,
        next_text=next_text,
    )
    return output_path


def _build_scene_audio(tts_paths: list[tuple[str, float]], scene_duration: float,
                       output_path: str) -> None:
    """TTS音声リスト(path, start_sec)から scene_duration 秒ぴったりの音声トラックを作る。

    各TTSは line.start 秒の位置に配置。末尾は無音パディング。
    TTSが次のlineに食い込む場合はそのまま重ねて再生（警告のみ）。
    """
    if not tts_paths:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
            "-t", f"{scene_duration:.3f}",
            "-c:a", "aac", "-b:a", "192k",
            output_path,
        ]
        r = sp.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"Silent audio generation failed: {r.stderr[-500:]}")
        return

    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    for path, _ in tts_paths:
        cmd.extend(["-i", path])

    filter_parts = []
    amix_inputs = ["[0:a]"]
    for i, (_, start_sec) in enumerate(tts_paths, start=1):
        delay_ms = int(start_sec * 1000)
        filter_parts.append(
            f"[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms}[d{i}]"
        )
        amix_inputs.append(f"[d{i}]")

    amix_str = "".join(amix_inputs)
    filter_parts.append(
        f"{amix_str}amix=inputs={len(amix_inputs)}:duration=first:normalize=0[mixed]"
    )
    filter_parts.append(f"[mixed]apad=whole_dur={scene_duration:.3f},atrim=0:{scene_duration:.3f}[out]")

    filter_complex = ";".join(filter_parts)
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "aac", "-b:a", "192k",
        output_path,
    ])
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Scene audio build failed: {r.stderr[-800:]}")


def _replace_audio(video_path: str, audio_path: str, output_path: str) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Audio replace failed: {r.stderr[-500:]}")


def _augment_animation_prompt(base_prompt: str, kling_duration: float) -> str:
    """Klingの後半が静止するよう、動作を前半に集中させる指示と、
    UI hallucination 抑止 negative 文を末尾に追加する。冪等。"""
    settle_pct = int(config.ACTION_FRONTLOAD_RATIO * 100)
    settle_at = kling_duration * config.ACTION_FRONTLOAD_RATIO
    addon = (
        f". Complete all major actions within the first {settle_pct}% of the clip "
        f"(by approximately {settle_at:.1f}s). In the remaining time, hold the final "
        f"pose with minimal movement so the clip can be cleanly trimmed at the end."
    )

    out = base_prompt
    if "Complete all major actions" not in out:
        out = out + addon

    neg = config.KLING_NEGATIVE_CONSTRAINT
    # 既に同じ negative 文があれば二重追加しない (冪等)
    if neg and neg not in out:
        out = out + ". " + neg

    return out


def _generate_kling(bg_path: str, animation_prompt: str, scene_duration: float,
                    output_path: str, scene_idx: int) -> None:
    composite_path = os.path.join(os.path.dirname(output_path),
                                  f"composite_{scene_idx:03d}.png")
    _prepare_background(bg_path, composite_path)

    augmented = _augment_animation_prompt(animation_prompt, scene_duration)
    logger.info("シーン%d Kling V3生成中 (%.1fs, prompt: %s...)",
                scene_idx + 1, scene_duration, augmented[:60])
    fal_video_client.generate_video(
        image_path=composite_path,
        prompt=augmented,
        output_path=output_path,
        audio_duration=scene_duration,
    )


def _tempo_max_for_scene(scene: dict) -> float:
    lines = scene.get("lines") or []
    total_chars = sum(len(l.get("text", "")) for l in lines)

    if not lines:
        return config.TEMPO_MAX_NO_LINES
    if len(lines) >= 3 or total_chars > config.TEMPO_TEXT_LONG_THRESHOLD:
        return config.TEMPO_MAX_LONG_TEXT
    if len(lines) >= 2 or total_chars > config.TEMPO_TEXT_MEDIUM_THRESHOLD:
        return config.TEMPO_MAX_MULTI_LINE
    return config.TEMPO_MAX_SINGLE_LINE


def _compute_target_duration(scene: dict, tts_total_end: float) -> float:
    """シーンの目標秒数を算出する。

    cut-off絶対回避を最優先 + 自然な発話を優先するため、
    シーン尺は常に「全TTSが自然な間で収まる長さ」 = floor を採用する。
    tempo_maxはwarningレベルでログ出力するのみ。
    """
    floor = max(tts_total_end, config.SCENE_MIN_DURATION)
    tempo_max = _tempo_max_for_scene(scene)
    if floor > tempo_max:
        level = "warning" if config.TEMPO_MAX_AS_WARNING_ONLY else "info"
        msg = (f"テンポ規範超過: TTS終端=%.2fs > tempo_max=%.1fs "
               f"(自然な発話優先で TTS終端 を採用)")
        if level == "warning":
            logger.warning(msg, tts_total_end, tempo_max)
        else:
            logger.info(msg, tts_total_end, tempo_max)
    return floor


def _compute_safe_final_duration(target_duration: float, kling_duration: float,
                                 action_complete: float | None,
                                 tts_total_end: float) -> float:
    """trim後の最終秒数。動作・音声どちらも絶対にcut-offしない。

    優先度:
      1. tts_total_end と SCENE_MIN_DURATION の最大値以上 (音声cut-off回避)
      2. action_complete があれば早期stopでテンポ向上
      3. それ以外は target_duration
    """
    safe_floor = max(tts_total_end, config.SCENE_MIN_DURATION)

    if action_complete is not None and action_complete >= safe_floor:
        return min(round(action_complete, 3), kling_duration)

    return min(max(safe_floor, target_duration), kling_duration)


def _generate_single_background(scene_idx: int, scene: dict, temp_dir: str,
                                screenplay: dict | None = None) -> tuple[str, str]:
    bg_key = f"bg_{scene_idx:03d}"
    path = os.path.join(temp_dir, f"{bg_key}.png")

    if not os.path.exists(path):
        enhanced = _build_background_prompt(scene, screenplay, ts_path=temp_dir,
                                              s_idx=scene_idx)
        full_prompt = f"{enhanced}. no text, no letters, vertical portrait composition"
        refs = _resolve_character_refs(scene)
        logger.info("%s 生成中 (参照キャラ: %d枚)", bg_key, len(refs))
        imagen_client.generate_image(full_prompt, path, reference_images=refs or None)
        logger.info("%s → %s", bg_key, path)

    return bg_key, path


def generate_backgrounds(screenplay: dict, temp_dir: str) -> dict[str, str]:
    scenes = screenplay["scenes"]
    bg_paths: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=BG_PARALLEL_WORKERS) as pool:
        futures = {
            pool.submit(_generate_background_with_retry, i, scene, temp_dir, screenplay): i
            for i, scene in enumerate(scenes)
        }
        for fut in as_completed(futures):
            i = futures[fut]
            bg_key, path = fut.result()
            bg_paths[bg_key] = path
            scenes[i]["_bg_key"] = bg_key

    logger.info("背景: %d枚", len(bg_paths))
    return bg_paths


def _resolve_inline_tag(line: dict, _scene: dict, _line_idx: int) -> str:
    """このlineに対する ElevenLabs V3 inline tag を解決する。

    優先順位:
      1. line.audio_tags[0] (ユーザー手動指定)
      2. line.emotion → config.EMOTION_AUDIO_TAGS の最初のタグ (自動補完)
      3. なし (タグ無し)
    """
    user_tags = line.get("audio_tags") or []
    if user_tags:
        first = str(user_tags[0]).strip()
        if first:
            return first
    emo = line.get("emotion")
    if emo and getattr(config, "EMOTION_AUDIO_TAGS_ENABLED", True):
        auto = config.EMOTION_AUDIO_TAGS.get(emo, [])
        if auto:
            first = str(auto[0]).strip()
            if first:
                return first
    return ""


def _build_screenplay_text(screenplay: dict) -> tuple[str, list[dict]]:
    """全line.text を半角スペース×2 で連結。各lineのchar offsetを line_specs に記録して返す。

    mood.tts_inline_tags / line.audio_tags があれば line.text の直前に
    "[tag] " を挿入する (ElevenLabs V3 の inline 感情タグ仕様)。
    line_specs.char_start は **発話本文 (text)** の先頭位置を指す
    (タグ部分は char_alignment 上スキップされる前提なのでマッピングに影響しない)。
    """
    line_specs: list[dict] = []
    text_parts: list[str] = []
    cursor = 0
    for s_idx, scene in enumerate(screenplay["scenes"]):
        for l_idx, line in enumerate(scene.get("lines") or []):
            t = line["text"]
            tag = _resolve_inline_tag(line, scene, l_idx)
            prefix = f"[{tag}] " if tag else ""
            if cursor > 0:
                cursor += len(SCREENPLAY_TEXT_SEPARATOR)
            # tag prefix を含めて送信文字列に乗せるが、line_specs は本文のみを指す
            text_parts.append(prefix + t)
            cursor += len(prefix)
            line_specs.append({
                "scene_idx": s_idx,
                "line_idx": l_idx,
                "char_start": cursor,
                "char_end": cursor + len(t),
            })
            cursor += len(t)
    return SCREENPLAY_TEXT_SEPARATOR.join(text_parts), line_specs


def _build_position_to_time_map(input_text: str,
                                  char_timestamps: list[dict]) -> list[dict | None]:
    """input_text の各文字位置 → {start, end} のマップを構築。

    APIが入力charの一部を返さない/順序が異なる場合に備えて、順次マッチで紐付ける。
    """
    result: list[dict | None] = [None] * len(input_text)
    cursor = 0
    for entry in char_timestamps:
        ch = entry["char"]
        while cursor < len(input_text) and input_text[cursor] != ch:
            cursor += 1
        if cursor < len(input_text):
            result[cursor] = {"start": float(entry["start"]),
                              "end": float(entry["end"])}
            cursor += 1
    return result


def _find_line_time_range(pos_to_time: list[dict | None],
                           char_start: int, char_end: int) -> tuple[float | None, float | None]:
    """[char_start, char_end) 範囲内で最初/最後の有効timestampを探す。"""
    abs_start = None
    for i in range(char_start, min(char_end, len(pos_to_time))):
        if pos_to_time[i]:
            abs_start = pos_to_time[i]["start"]
            break
    abs_end = None
    upper = min(char_end, len(pos_to_time)) - 1
    for i in range(upper, char_start - 1, -1):
        if pos_to_time[i]:
            abs_end = pos_to_time[i]["end"]
            break
    return abs_start, abs_end


def _detect_all_silences(audio_path: str, threshold_db: float = -40.0,
                          min_silence_sec: float = 0.03) -> list[tuple[float, float]]:
    """ffmpeg silencedetect で audio_path 内の全無音区間 [(start, end), ...] を返す。

    char_ts boundary snap 用に使うので min_silence_sec は短め (30ms)。
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-i", audio_path,
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_silence_sec:.3f}",
        "-f", "null", "-",
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    silences: list[tuple[float, float]] = []
    cur_start: float | None = None
    for line in r.stderr.splitlines():
        if "silence_start:" in line:
            try:
                cur_start = float(
                    line.split("silence_start:")[1].strip().split()[0])
            except (ValueError, IndexError):
                cur_start = None
        elif "silence_end:" in line and cur_start is not None:
            try:
                end_str = line.split("silence_end:")[1].strip().split()[0]
                silences.append((cur_start, float(end_str)))
            except (ValueError, IndexError):
                pass
            cur_start = None
    return silences


def _snap_line_boundaries_to_silence(
    line_times: list[dict],
    silences: list[tuple[float, float]],
    snap_tolerance_sec: float = 0.2,
    min_speech_sec: float = 0.05,
) -> list[dict]:
    """char_ts ベースの abs_start/abs_end を、最寄りの無音区間境界に snap する。

    - abs_end → 近隣 (±tolerance) の silence.start に snap (発声末尾を無音直前で切る)
    - abs_start → 近隣 (±tolerance) の silence.end に snap (子音オンセット直前から始める)
    - snap 候補が前後 line と overlap する場合は元の char_ts を保持
    - line間に検出可能な無音が無い (連続発声) 場合も char_ts のまま
    """
    if not silences or not line_times:
        return [dict(lt) for lt in line_times]
    sorted_sils = sorted(silences)

    def silence_with_start_near(t: float) -> tuple[float, float] | None:
        best: tuple[float, float] | None = None
        best_dist = snap_tolerance_sec + 1.0
        for s_start, s_end in sorted_sils:
            d = abs(s_start - t)
            if d <= snap_tolerance_sec and d < best_dist:
                best = (s_start, s_end)
                best_dist = d
            if s_start > t + snap_tolerance_sec:
                break
        return best

    def silence_with_end_near(t: float) -> tuple[float, float] | None:
        best: tuple[float, float] | None = None
        best_dist = snap_tolerance_sec + 1.0
        for s_start, s_end in sorted_sils:
            d = abs(s_end - t)
            if d <= snap_tolerance_sec and d < best_dist:
                best = (s_start, s_end)
                best_dist = d
            if s_start > t + snap_tolerance_sec:
                break
        return best

    snapped: list[dict] = []
    for lt in line_times:
        new_start = lt["abs_start"]
        new_end = lt["abs_end"]
        sil_end = silence_with_start_near(new_end)
        if sil_end and sil_end[0] > new_start + min_speech_sec:
            new_end = sil_end[0]
        sil_start = silence_with_end_near(new_start)
        if sil_start and sil_start[1] < new_end - min_speech_sec:
            new_start = sil_start[1]
        snapped.append({**lt, "abs_start": new_start, "abs_end": new_end})

    # overlap 検出 → overlap している隣接 line 対は元の char_ts に戻す
    for i in range(len(snapped) - 1):
        if snapped[i]["abs_end"] > snapped[i + 1]["abs_start"]:
            snapped[i]["abs_end"] = line_times[i]["abs_end"]
            snapped[i + 1]["abs_start"] = line_times[i + 1]["abs_start"]
    return snapped


def _extract_audio_segment(input_path: str, start_sec: float, duration: float,
                            output_path: str, codec: str = "aac",
                            bitrate: str = "192k") -> None:
    """ffmpegで input_path から指定区間を切出して output_path に保存。

    -ss を -i の後ろに置く (output seeking) ことで frame-accurate なseekを保証。
    -ss を -i の前に置くと mp3 packet 境界 (~26ms) にスナップして語頭/語尾が削れる。
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-ss", f"{start_sec:.3f}",
        "-t", f"{max(duration, 0.05):.3f}",
        "-c:a", codec, "-b:a", bitrate,
        output_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {r.stderr[-500:]}")


def _convert_to_aac(input_path: str, output_path: str,
                     bitrate: str = "192k") -> None:
    cmd = ["ffmpeg", "-y", "-i", input_path,
           "-c:a", "aac", "-b:a", bitrate, output_path]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"AAC convert failed: {r.stderr[-500:]}")


def _concat_audios_to_aac(audio_paths: list[str], output_path: str) -> None:
    """複数audioを ffmpeg で連結 → AAC m4a 出力。"""
    if not audio_paths:
        return
    if len(audio_paths) == 1:
        _convert_to_aac(audio_paths[0], output_path)
        return
    inputs: list[str] = []
    for p in audio_paths:
        inputs.extend(["-i", p])
    chain = "".join(f"[{i}:a]" for i in range(len(audio_paths)))
    filter_str = f"{chain}concat=n={len(audio_paths)}:v=0:a=1[out]"
    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_str,
        "-map", "[out]",
        "-c:a", "aac", "-b:a", "192k",
        output_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Audio concat failed: {r.stderr[-500:]}")


def _line_silence_after_sec(line: dict) -> float:
    """line.silence_after_ms または既定値 (TTS_MAX_SILENCE_MS) を秒数で返す。"""
    v = line.get("silence_after_ms")
    if v is None:
        v = config.TTS_MAX_SILENCE_MS
    return max(0.0, min(2.0, float(v) / 1000.0))


def _concat_audios_to_mp3(audio_paths: list[str], output_path: str) -> None:
    """複数audioを ffmpeg で連結 → mp3 出力 (per-line speech body + trailing用)。"""
    if not audio_paths:
        return
    if len(audio_paths) == 1:
        os.replace(audio_paths[0], output_path)
        return
    inputs: list[str] = []
    for p in audio_paths:
        inputs.extend(["-i", p])
    chain = "".join(f"[{i}:a]" for i in range(len(audio_paths)))
    filter_str = f"{chain}concat=n={len(audio_paths)}:v=0:a=1[out]"
    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_str,
        "-map", "[out]",
        "-c:a", "libmp3lame", "-q:a", "4",
        output_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"mp3 concat failed: {r.stderr[-500:]}")


def _build_audios_from_full(screenplay: dict, ts_path: str) -> None:
    """既存の tts_full.mp3 から per-line および scene audio を再構築する。

    Per-line 後処理パイプライン (timestamp drift 根絶のため全工程 line ファイル単位):
      1. [abs_start, abs_end] を speech body として切出し
      2. silenceremove を speech body にのみ適用 (mid-line の長い無音を圧縮)
      3. [abs_end, abs_end + silence_after_sec] を trailing として切出し (次line侵食しない範囲)
      4. body + trailing を concat → tts_<S>_<L>.mp3
      5. atempo を line file 全体に適用 (global_speed > native_max のとき)
    """
    full_mp3 = os.path.join(ts_path, "tts_full.mp3")
    timestamps_json = os.path.join(ts_path, "tts_full.json")
    if not os.path.exists(full_mp3) or not os.path.exists(timestamps_json):
        return

    full_text, line_specs = _build_screenplay_text(screenplay)
    with open(timestamps_json) as f:
        char_ts = json.load(f)
    pos_to_time = _build_position_to_time_map(full_text, char_ts)

    line_times: list[dict] = []
    for spec in line_specs:
        abs_start, abs_end = _find_line_time_range(
            pos_to_time, spec["char_start"], spec["char_end"])
        if abs_start is None or abs_end is None:
            continue
        line_times.append({
            "scene_idx": spec["scene_idx"],
            "line_idx": spec["line_idx"],
            "abs_start": abs_start,
            "abs_end": abs_end,
        })

    # char_ts は文字発音区間で実音声の自然な境界とは ±50-100ms ズレる。
    # tts_full.mp3 の無音区間に line 境界を snap して語尾/文頭の食込みを防ぐ。
    threshold_db = float(getattr(config, "TTS_SILENCE_THRESHOLD_DB", -40))
    silences = _detect_all_silences(full_mp3, threshold_db, min_silence_sec=0.03)
    line_times = _snap_line_boundaries_to_silence(line_times, silences)

    by_scene: dict[int, list[dict]] = {}
    for lt in line_times:
        by_scene.setdefault(lt["scene_idx"], []).append(lt)

    if not line_times:
        return

    trim_sil = bool(getattr(config, "TTS_TRIM_LONG_SILENCES", False))
    max_sil_sec = float(getattr(config, "TTS_MAX_SILENCE_MS", 250)) / 1000.0
    sil_thr = float(getattr(config, "TTS_SILENCE_THRESHOLD_DB", -40))
    _native, atempo = _split_global_speed()
    full_audio_dur = _get_duration(full_mp3)

    # Step 1: 各 line を per-line で切出し + silenceremove + trailing concat + atempo
    line_actual_silences: dict[tuple[int, int], float] = {}
    for i, lt in enumerate(line_times):
        s_idx, l_idx = lt["scene_idx"], lt["line_idx"]
        line = screenplay["scenes"][s_idx]["lines"][l_idx]
        out_path = os.path.join(ts_path, f"tts_{s_idx:03d}_{l_idx:03d}.mp3")
        if os.path.exists(out_path):
            os.remove(out_path)

        # abs_end が音声末尾を超える場合は clamp (char_ts > audio_dur のとき)
        body_end = min(lt["abs_end"], full_audio_dur)
        next_abs_start = (
            line_times[i + 1]["abs_start"] if i + 1 < len(line_times)
            else float("inf")
        )
        tail_limit = min(next_abs_start, full_audio_dur)
        desired = _line_silence_after_sec(line)
        available = max(0.0, tail_limit - body_end)
        natural_extract = max(0.0, min(desired, available))

        body_path = out_path + ".body.mp3"
        speech_dur = max(0.05, body_end - lt["abs_start"])
        _extract_audio_segment(full_mp3, lt["abs_start"], speech_dur, body_path,
                                codec="libmp3lame", bitrate="192k")
        if trim_sil:
            _apply_silenceremove_inplace(body_path, max_sil_sec, sil_thr)

        pieces = [body_path]
        if natural_extract > 0:
            tail_path = out_path + ".tail.mp3"
            _extract_audio_segment(full_mp3, body_end, natural_extract,
                                    tail_path, codec="libmp3lame", bitrate="192k")
            pieces.append(tail_path)
        _concat_audios_to_mp3(pieces, out_path)
        for p in pieces:
            if p != out_path and os.path.exists(p):
                os.remove(p)

        if abs(atempo - 1.0) > 0.001:
            _apply_atempo_inplace(out_path, atempo)

        # atempo 後の natural silence 実長 (subtitle 計算用)
        line_actual_silences[(s_idx, l_idx)] = natural_extract / max(atempo, 1e-6)

    # Step 2: scene 単位 audio_<S>.m4a を line files concat で構築
    for s_idx, scene in enumerate(screenplay["scenes"]):
        scene_lts = by_scene.get(s_idx, [])
        out_path = os.path.join(ts_path, f"audio_{s_idx:03d}.m4a")
        if os.path.exists(out_path):
            os.remove(out_path)

        if not scene_lts:
            scene["duration"] = config.SCENE_MIN_DURATION
            continue

        line_paths: list[str] = []
        cumulative = 0.0
        for lt in scene_lts:
            line = scene["lines"][lt["line_idx"]]
            line_path = os.path.join(
                ts_path, f"tts_{s_idx:03d}_{lt['line_idx']:03d}.mp3")
            file_dur = _get_duration(line_path)
            silence_in_file = line_actual_silences.get(
                (s_idx, lt["line_idx"]), 0.0)
            speech_dur = max(0.0, file_dur - silence_in_file)

            # subtitle用 line.start/end は speech 部分のみ
            line["start"] = round(cumulative, 3)
            line["end"] = round(cumulative + speech_dur, 3)
            cumulative += file_dur
            line_paths.append(line_path)

        scene["duration"] = max(
            cumulative + config.SCENE_TTS_TAIL_BUFFER,
            config.SCENE_MIN_DURATION,
        )

        _concat_audios_to_aac(line_paths, out_path)

    # Step 3: 全シーン audio_<S>.m4a を1本に concat → merged preview用
    # (per-line padding/速度を反映した「実際に聞こえる音」のプレビュー)
    merged_path = os.path.join(ts_path, "merged_preview.m4a")
    if os.path.exists(merged_path):
        os.remove(merged_path)
    scene_paths = [
        os.path.join(ts_path, f"audio_{s_idx:03d}.m4a")
        for s_idx in range(len(screenplay["scenes"]))
        if os.path.exists(os.path.join(ts_path, f"audio_{s_idx:03d}.m4a"))
    ]
    if scene_paths:
        _concat_audios_to_aac(scene_paths, merged_path)


def _clear_tts_artifacts(ts_path: str) -> None:
    """TTS生成物を全削除 (再生成前のクリーンアップ)。"""
    patterns = [
        "tts_full.mp3", "tts_full.json", "tts_full.text_meta.json",
        "tts_*.mp3", "tts_*.json",
        "audio_*.m4a",
        "merged_preview.m4a",
    ]
    for pat in patterns:
        for f in glob.glob(os.path.join(ts_path, pat)):
            try:
                os.remove(f)
            except OSError:
                pass


def _split_global_speed(target: float | None = None) -> tuple[float, float]:
    """target 速度倍率を ElevenLabs native speed と ffmpeg atempo に分解する。

    例:
      target=0.5 → native=0.7, atempo=0.714
      target=1.0 → native=1.0, atempo=1.0
      target=1.5 → native=1.2, atempo=1.25
      target=2.0 → native=1.2, atempo=1.667
    """
    speed = float(target if target is not None else config.TTS_GLOBAL_SPEED)
    speed = max(0.5, min(2.0, speed))
    native = max(config.TTS_NATIVE_SPEED_MIN,
                 min(config.TTS_NATIVE_SPEED_MAX, speed))
    atempo = speed / native
    return native, atempo


def _apply_atempo_inplace(input_path: str, atempo: float) -> None:
    """ffmpeg atempo で速度補正 (in-place)。pitch維持で時間軸のみ変化。"""
    if abs(atempo - 1.0) < 0.001:
        return
    tmp_path = input_path + ".tempo.tmp.mp3"
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-af", f"atempo={atempo:.4f}",
        "-c:a", "libmp3lame", "-q:a", "4",
        tmp_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"atempo failed: {r.stderr[-500:]}")
    os.replace(tmp_path, input_path)


def _apply_silenceremove_inplace(input_path: str, max_silence_sec: float,
                                    threshold_db: float) -> None:
    """ffmpeg silenceremove で max_silence_sec 超の無音を圧縮 (in-place)。

    per-line speech body にのみ適用 (mid-line の長い無音を圧縮する用途)。
    leading silence は start_periods=0 で保護、trailing は呼出元が body を切出した時点で除去済み。
    """
    tmp_path = input_path + ".sr.tmp.mp3"
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-af",
        f"silenceremove="
        f"start_periods=0:"
        f"stop_periods=-1:"
        f"stop_silence={max_silence_sec:.3f}:"
        f"stop_threshold={threshold_db}dB",
        "-c:a", "libmp3lame", "-q:a", "4",
        tmp_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"silenceremove failed: {r.stderr[-500:]}")
    os.replace(tmp_path, input_path)


def _full_screenplay_voice_settings() -> dict:
    """one-shot生成で使う screenplay-wide voice settings (config の既定値 + global speed)。"""
    native_speed, _atempo = _split_global_speed()
    return {
        "voice_id": config.ELEVENLABS_VOICE_ID,
        "stability": config.ELEVENLABS_VOICE_STABILITY,
        "similarity_boost": config.ELEVENLABS_VOICE_SIMILARITY_BOOST,
        "style": config.ELEVENLABS_VOICE_STYLE,
        "speed": native_speed,
    }


def generate_screenplay_tts_one_shot(screenplay: dict, ts_path: str) -> dict | None:
    """Stage 2: screenplay全体を1 ElevenLabs API call で生成し、char timestampsから:
      - 各 line の scene 内相対 start/end 秒を逆算
      - 各 scene の duration を逆算
      - tts_full.mp3 を scene/line に分割保存
    """
    if screenplay.get("audio_mode") == "silent":
        return None
    if not config.ELEVENLABS_API_KEY:
        logger.warning("ELEVENLABS_API_KEY未設定でTTSスキップ")
        return None

    full_text, line_specs = _build_screenplay_text(screenplay)
    if not full_text.strip():
        return None

    native_speed, _atempo = _split_global_speed()
    voice_id = config.ELEVENLABS_VOICE_ID
    cache_key = f"{full_text}|v={voice_id}|s={native_speed:.3f}"
    text_hash = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:12]

    full_mp3 = os.path.join(ts_path, "tts_full.mp3")
    timestamps_json = os.path.join(ts_path, "tts_full.json")
    text_meta_json = os.path.join(ts_path, "tts_full.text_meta.json")

    cached_hash = None
    if os.path.exists(text_meta_json):
        try:
            with open(text_meta_json) as f:
                cached_hash = json.load(f).get("text_hash")
        except (json.JSONDecodeError, OSError):
            pass

    need_regen = (cached_hash != text_hash
                  or not os.path.exists(full_mp3)
                  or not os.path.exists(timestamps_json))

    if need_regen:
        logger.info("[1-shot TTS] 全 %d 文字を生成中... (hash=%s, native_speed=%.2f)",
                    len(full_text), text_hash, native_speed)
        for f in [full_mp3, timestamps_json, text_meta_json]:
            if os.path.exists(f):
                os.remove(f)

        vs = _full_screenplay_voice_settings()
        elevenlabs_client.generate_speech_with_timestamps(
            text=full_text,
            voice_id=vs["voice_id"],
            output_path=full_mp3,
            stability=vs["stability"],
            similarity_boost=vs["similarity_boost"],
            style=vs["style"],
            speed=vs["speed"],
            language=config.LANGUAGE,
            keep_whitespace=True,
        )

    # per-line audio + scene audio を 既存tts_full.mp3 から再構築
    # (silenceremove + atempo + silence_after_ms はすべて per-line で適用)
    _build_audios_from_full(screenplay, ts_path)

    with open(text_meta_json, "w") as f:
        json.dump({
            "text_hash": text_hash,
            "full_text": full_text,
            "separator": SCREENPLAY_TEXT_SEPARATOR,
            "line_specs": line_specs,
        }, f, ensure_ascii=False, indent=2)

    logger.info("[1-shot TTS] 完了 (scenes=%d)",
                len(screenplay["scenes"]))
    return {"full_text": full_text}


def build_merged_tts_preview(screenplay: dict, ts_path: str) -> str | None:
    """per-line audio を全 scene 連結した merged_preview.m4a を返す。

    `_build_audios_from_full` が生成する「実際に動画に乗る音」のプレビュー。
    silence_after_ms / atempo / silenceremove 反映済み。
    無ければ生 tts_full.mp3 (パディング未反映) にフォールバック。
    """
    if screenplay.get("audio_mode") == "silent":
        return None
    merged = os.path.join(ts_path, "merged_preview.m4a")
    if os.path.exists(merged):
        return merged
    p = os.path.join(ts_path, "tts_full.mp3")
    if os.path.exists(p):
        return p
    return None


def _bg_path_for_scene(scene_idx: int, scene: dict, temp_dir: str) -> str:
    bg_key = scene.get("_bg_key", f"bg_{scene_idx:03d}")
    return os.path.join(temp_dir, f"{bg_key}.png")


def generate_tts_for_screenplay(screenplay: dict, temp_dir: str) -> dict | None:
    """Stage 2: screenplay全体を1 API call で生成 (one-shot方式)。silent ならスキップ。

    text_hashが変わらなければキャッシュ。返り値は line_times 等のメタ。
    """
    return generate_screenplay_tts_one_shot(screenplay, temp_dir)


def regen_tts_full(screenplay: dict, temp_dir: str, force: bool = True) -> None:
    """TTS全体を再生成する。

    force=True (既定): tts_full.mp3 等のキャッシュを削除して必ずElevenLabs API再呼び出し。
    force=False: キャッシュを保持し、text_hash不変ならAPI呼び出しスキップで
                 audioのみ再構築 (per-line speed/silence_after_ms 変更時に有用、無料)。
    """
    if force:
        _clear_tts_artifacts(temp_dir)
    generate_screenplay_tts_one_shot(screenplay, temp_dir)


def regen_tts_line(scene_idx: int, line_idx: int, screenplay: dict, temp_dir: str) -> None:
    """[互換] one-shot方式では line単位再生成は不可。screenplay全体再生成にリダイレクト。"""
    logger.info("regen_tts_line(s=%d,l=%d) はscreenplay全体再生成にリダイレクト",
                scene_idx, line_idx)
    regen_tts_full(screenplay, temp_dir)


def regen_tts_scene(scene_idx: int, screenplay: dict, temp_dir: str) -> None:
    """[互換] one-shot方式では scene単位再生成は不可。screenplay全体再生成にリダイレクト。"""
    logger.info("regen_tts_scene(s=%d) はscreenplay全体再生成にリダイレクト", scene_idx)
    regen_tts_full(screenplay, temp_dir)


def regen_background_scene(scene_idx: int, screenplay: dict, temp_dir: str) -> None:
    """単一シーンの背景画像を再生成。下流のkling/scene動画も無効化。

    audio_<S>.m4a は TTS 由来 (BG非依存) なので削除しない。
    """
    scene = screenplay["scenes"][scene_idx]
    for fname in [
        f"bg_{scene_idx:03d}.png",
        f"composite_{scene_idx:03d}.png",
        f"kling_{scene_idx:03d}.mp4",
        f"scene_{scene_idx:03d}.trim.mp4",
        f"scene_{scene_idx:03d}.mp4",
    ]:
        p = os.path.join(temp_dir, fname)
        if os.path.exists(p):
            os.remove(p)
    bg_key, _ = _generate_background_with_retry(scene_idx, scene, temp_dir, screenplay)
    scene["_bg_key"] = bg_key


def _scene_tts_audio_duration(scene_idx: int, ts_path: str) -> float:
    """one-shot で生成済み audio_<S>.m4a の尺を返す。なければ 0。"""
    p = os.path.join(ts_path, f"audio_{scene_idx:03d}.m4a")
    if os.path.exists(p):
        return _get_duration(p)
    return 0.0


def _kling_for_scene(scene_idx: int, scene: dict, screenplay: dict, temp_dir: str) -> None:
    """1シーン分のKling生成 + trim。one-shotで確定済みの scene.duration を採用。"""
    bg_path = _bg_path_for_scene(scene_idx, scene, temp_dir)
    if not os.path.exists(bg_path):
        raise FileNotFoundError(f"背景画像が見つかりません: {bg_path}")

    tts_end = _scene_tts_audio_duration(scene_idx, temp_dir)
    target_duration = _compute_target_duration(scene, tts_end)
    kling_duration = float(fal_video_client._pick_duration(target_duration))

    kling_raw_path = os.path.join(temp_dir, f"kling_{scene_idx:03d}.mp4")
    trimmed_path = os.path.join(temp_dir, f"scene_{scene_idx:03d}.trim.mp4")

    logger.info("シーン%d target=%.2fs kling=%.0fs (TTS尺=%.2fs)",
                scene_idx + 1, target_duration, kling_duration, tts_end)

    if not os.path.exists(kling_raw_path):
        anim_prompt = _get_animation_prompt(scene, ts_path=temp_dir,
                                              s_idx=scene_idx,
                                              screenplay=screenplay)
        _generate_kling(bg_path, anim_prompt, kling_duration,
                        kling_raw_path, scene_idx)

    raw_dur = _get_duration(kling_raw_path)
    import audio_features
    action_complete = audio_features.detect_action_complete(kling_raw_path)
    if action_complete is not None:
        logger.info("シーン%d 動作完了点 検出: t=%.2fs (kling raw=%.2fs)",
                    scene_idx + 1, action_complete, raw_dur)

    final_duration = _compute_safe_final_duration(
        target_duration=target_duration,
        kling_duration=raw_dur,
        action_complete=action_complete,
        tts_total_end=tts_end,
    )
    final_duration = max(config.SCENE_MIN_DURATION, min(final_duration, raw_dur))

    if not os.path.exists(trimmed_path):
        _trim_video(kling_raw_path, final_duration, trimmed_path)
        logger.info("シーン%d trim → %.2fs", scene_idx + 1, final_duration)

    scene["duration"] = final_duration


def generate_kling_for_screenplay(screenplay: dict, temp_dir: str) -> None:
    """Stage 4: 全シーンのKlingクリップ生成 + trim。"""
    for i, scene in enumerate(screenplay["scenes"]):
        _kling_for_scene(i, scene, screenplay, temp_dir)


def regen_kling_scene(scene_idx: int, screenplay: dict, temp_dir: str) -> None:
    """単一シーンのKlingのみ再生成。下流のscene動画も無効化。"""
    scene = screenplay["scenes"][scene_idx]
    for fname in [
        f"kling_{scene_idx:03d}.mp4",
        f"scene_{scene_idx:03d}.trim.mp4",
        f"scene_{scene_idx:03d}.mp4",
    ]:
        p = os.path.join(temp_dir, fname)
        if os.path.exists(p):
            os.remove(p)
    _kling_for_scene(scene_idx, scene, screenplay, temp_dir)


def _scene_video_for_scene(scene_idx: int, scene: dict, screenplay: dict,
                            temp_dir: str) -> str:
    """Stage 5+6 (one-shot方式): 既に audio_<S>.m4a が生成済み前提。
    trim済みKling + audio をリップシンク or 単純合成して scene_<S>.mp4 を作る。
    """
    silent = screenplay.get("audio_mode") == "silent"
    trimmed_path = os.path.join(temp_dir, f"scene_{scene_idx:03d}.trim.mp4")
    audio_path = os.path.join(temp_dir, f"audio_{scene_idx:03d}.m4a")
    final_path = os.path.join(temp_dir, f"scene_{scene_idx:03d}.mp4")

    if not os.path.exists(trimmed_path):
        raise FileNotFoundError(f"trim済み動画が見つかりません: {trimmed_path}")

    final_duration = scene.get("duration") or _get_duration(trimmed_path)
    scene["duration"] = final_duration

    if silent:
        if not os.path.exists(final_path):
            shutil.copyfile(trimmed_path, final_path)
        return final_path

    if not os.path.exists(audio_path):
        raise FileNotFoundError(
            f"audio_{scene_idx:03d}.m4a が見つかりません。Stage 2 (TTS) 未実行?")

    lipsync_enabled = (config.LIPSYNC_ENABLED
                       and scene.get("lipsync", True)
                       and bool(scene.get("lines")))

    if not os.path.exists(final_path):
        if lipsync_enabled:
            logger.info("シーン%d リップシンク処理中 (%s)",
                        scene_idx + 1, config.LIPSYNC_PROVIDER)
            lipsync_client.apply(trimmed_path, audio_path, final_path)
        else:
            _replace_audio(trimmed_path, audio_path, final_path)

    return final_path


def assemble_scene_videos(screenplay: dict, temp_dir: str) -> list[str]:
    """Stage 5+6: 各シーンのscene_xxx.mp4を作成する (one-shot生成済みaudioを使用)。"""
    scene_videos: list[str] = []
    for i, scene in enumerate(screenplay["scenes"]):
        path = _scene_video_for_scene(i, scene, screenplay, temp_dir)
        scene_videos.append(path)
    return scene_videos


def regen_scene_video(scene_idx: int, screenplay: dict, temp_dir: str) -> None:
    """単一シーンの最終動画を再生成（trim済みKling + audioを再利用してリップシンクのみ）。"""
    scene = screenplay["scenes"][scene_idx]
    final_path = os.path.join(temp_dir, f"scene_{scene_idx:03d}.mp4")
    if os.path.exists(final_path):
        os.remove(final_path)
    _scene_video_for_scene(scene_idx, scene, screenplay, temp_dir)


def collect_scene_videos(screenplay: dict, temp_dir: str) -> list[str]:
    """既に生成済みの scene_<i>.mp4 を返す。"""
    paths = []
    for i in range(len(screenplay["scenes"])):
        p = os.path.join(temp_dir, f"scene_{i:03d}.mp4")
        if not os.path.exists(p):
            raise FileNotFoundError(f"シーン動画が見つかりません: {p}")
        paths.append(p)
    return paths
