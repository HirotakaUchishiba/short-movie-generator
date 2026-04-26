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


def _get_animation_prompt(scene: dict) -> str:
    explicit = scene.get("animation_prompt")
    bg_prompt = scene.get("background_prompt", "")
    base = explicit if explicit else f"gentle cinematic motion, {bg_prompt}"

    extras: list[str] = []
    fe = scene.get("facial_expression")
    if fe and fe not in base:
        extras.append(f"facial expression: {fe}")
    hg = scene.get("hand_gesture")
    if hg and hg not in base:
        extras.append(f"hand gesture: {hg}")

    dominant = _dominant_emotion(scene)
    addon = config.EMOTION_MOTION_ADDONS.get(dominant or "") if dominant else None
    if addon and addon not in base:
        extras.append(addon)

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
    """character_refs (旧API) と characters[].ref (新API) の両方から参照画像を解決する。"""
    names: list[str] = []
    if "character_refs" in scene:
        names.extend(scene["character_refs"] or [])
    for c in scene.get("characters") or []:
        if c.get("ref"):
            names.append(c["ref"])
    if not names and "character_refs" not in scene:
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


def _build_background_prompt(scene: dict, screenplay: dict | None = None) -> str:
    parts: list[str] = [scene.get("background_prompt", "")]

    wardrobe = scene.get("wardrobe") or {}
    wardrobe_id = wardrobe.get("identifier")
    if wardrobe_id and screenplay:
        global_wd = (screenplay.get("wardrobe_continuity") or {}).get(wardrobe_id)
        if global_wd:
            parts.append(f"wardrobe (consistent across scenes): {global_wd}")
    wd_details = [f"{k}: {wardrobe[k]}" for k in ("top", "bottom", "accessories", "hair") if wardrobe.get(k)]
    if wd_details:
        parts.append(", ".join(wd_details))

    if scene.get("facial_expression"):
        parts.append(f"facial expression: {scene['facial_expression']}")
    if scene.get("hand_gesture"):
        parts.append(f"hand gesture: {scene['hand_gesture']}")

    chars = scene.get("characters") or []
    if len(chars) > 1:
        descs = []
        for c in chars:
            d = c.get("name") or "person"
            if c.get("role"):
                d += f" ({c['role']})"
            if c.get("outfit"):
                d += f": {c['outfit']}"
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
    """Klingの後半が静止するよう、動作を前半に集中させる指示を末尾に追加する。"""
    settle_pct = int(config.ACTION_FRONTLOAD_RATIO * 100)
    settle_at = kling_duration * config.ACTION_FRONTLOAD_RATIO
    addon = (
        f". Complete all major actions within the first {settle_pct}% of the clip "
        f"(by approximately {settle_at:.1f}s). In the remaining time, hold the final "
        f"pose with minimal movement so the clip can be cleanly trimmed at the end."
    )
    if "Complete all major actions" in base_prompt:
        return base_prompt
    return base_prompt + addon


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
        enhanced = _build_background_prompt(scene, screenplay)
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


def _build_screenplay_text(screenplay: dict) -> tuple[str, list[dict]]:
    """全line.text を半角スペース×2 で連結。各lineのchar offsetを line_specs に記録して返す。"""
    line_specs: list[dict] = []
    text_parts: list[str] = []
    cursor = 0
    for s_idx, scene in enumerate(screenplay["scenes"]):
        for l_idx, line in enumerate(scene.get("lines") or []):
            t = line["text"]
            if cursor > 0:
                cursor += len(SCREENPLAY_TEXT_SEPARATOR)
            line_specs.append({
                "scene_idx": s_idx,
                "line_idx": l_idx,
                "char_start": cursor,
                "char_end": cursor + len(t),
            })
            text_parts.append(t)
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


def _build_audios_from_full(screenplay: dict, ts_path: str) -> None:
    """既存の tts_full.mp3 から per-line および scene audio を再構築する。

    旧仕様 (連続抽出): scene audio は scene_start から scene_end までを
    tts_full.mp3 から **連続切り出し** で生成。per-line concat は使わない。
    line.speed / silence_after_ms 等の per-line調整は使わない。
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

    by_scene: dict[int, list[dict]] = {}
    for lt in line_times:
        by_scene.setdefault(lt["scene_idx"], []).append(lt)

    # scene.duration / line.start/end (scene-relative) を確定
    for s_idx, scene in enumerate(screenplay["scenes"]):
        scene_lts = by_scene.get(s_idx)
        if not scene_lts:
            scene["duration"] = config.SCENE_MIN_DURATION
            continue
        scene_start = scene_lts[0]["abs_start"]
        scene_end = scene_lts[-1]["abs_end"]
        scene["duration"] = max(
            scene_end - scene_start + config.SCENE_TTS_TAIL_BUFFER,
            config.SCENE_MIN_DURATION,
        )
        for lt in scene_lts:
            line = scene["lines"][lt["line_idx"]]
            line["start"] = round(lt["abs_start"] - scene_start, 3)
            line["end"] = round(lt["abs_end"] - scene_start, 3)

    # scene 単位 audio_<S>.m4a を tts_full.mp3 から **連続切り出し**
    for s_idx, scene in enumerate(screenplay["scenes"]):
        scene_lts = by_scene.get(s_idx)
        if not scene_lts:
            continue
        scene_start = scene_lts[0]["abs_start"]
        scene_dur = scene["duration"]
        out_path = os.path.join(ts_path, f"audio_{s_idx:03d}.m4a")
        if os.path.exists(out_path):
            os.remove(out_path)
        _extract_audio_segment(full_mp3, scene_start, scene_dur, out_path)

    # line 単位 mp3 (UI試聴用) を切り出し
    for lt in line_times:
        s_idx = lt["scene_idx"]
        l_idx = lt["line_idx"]
        line_dur = lt["abs_end"] - lt["abs_start"]
        out_path = os.path.join(ts_path, f"tts_{s_idx:03d}_{l_idx:03d}.mp3")
        if os.path.exists(out_path):
            os.remove(out_path)
        _extract_audio_segment(full_mp3, lt["abs_start"], line_dur, out_path,
                                codec="libmp3lame", bitrate="192k")


def _clear_tts_artifacts(ts_path: str) -> None:
    """TTS生成物を全削除 (再生成前のクリーンアップ)。"""
    patterns = [
        "tts_full.mp3", "tts_full.json", "tts_full.text_meta.json",
        "tts_*.mp3", "tts_*.json",
        "audio_*.m4a",
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


def _detect_silences(audio_path: str, threshold_db: float,
                       min_silence_sec: float) -> list[tuple[float, float]]:
    """ffmpeg silencedetect で無音区間を検出し [(start, end), ...] を返す。"""
    cmd = [
        "ffmpeg", "-hide_banner", "-i", audio_path,
        "-af",
        f"silencedetect=noise={threshold_db}dB:d={min_silence_sec:.3f}",
        "-f", "null", "-",
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    silences: list[tuple[float, float]] = []
    cur_start: float | None = None
    for line in r.stderr.splitlines():
        if "silence_start:" in line:
            try:
                cur_start = float(line.split("silence_start:")[1].strip().split()[0])
            except (ValueError, IndexError):
                cur_start = None
        elif "silence_end:" in line and cur_start is not None:
            try:
                end_str = line.split("silence_end:")[1].strip().split()[0]
                end = float(end_str)
                silences.append((cur_start, end))
            except (ValueError, IndexError):
                pass
            cur_start = None
    return silences


def _apply_silenceremove_inplace(input_path: str, max_silence_sec: float,
                                    threshold_db: float) -> None:
    """ffmpeg silenceremove で max_silence_sec 超の無音を圧縮 (in-place)。"""
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


def _adjust_timestamps_for_silence_trim(char_ts: list[dict],
                                          silences: list[tuple[float, float]],
                                          max_silence_sec: float) -> None:
    """char timestamps を、長い無音を max_silence_sec まで圧縮した後の時刻に補正する (in-place)。

    各時刻 t に対し、t より前にある無音区間の超過分の合計を引く。
    """
    if not silences:
        return
    sorted_silences = sorted(silences)

    def removed_before(t: float) -> float:
        """時刻 t より前にカットされた合計秒数。"""
        total = 0.0
        for s_start, s_end in sorted_silences:
            if s_end <= t:
                dur = s_end - s_start
                if dur > max_silence_sec:
                    total += dur - max_silence_sec
            elif s_start < t < s_end:
                # t が無音区間内: 超過カット分のうち start からの相対分だけ
                offset_in_silence = t - s_start
                if offset_in_silence > max_silence_sec:
                    total += offset_in_silence - max_silence_sec
                break
            else:
                break
        return total

    for entry in char_ts:
        t_start = float(entry["start"])
        t_end = float(entry["end"])
        entry["start"] = max(0.0, t_start - removed_before(t_start))
        entry["end"] = max(0.0, t_end - removed_before(t_end))


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

    native_speed, atempo = _split_global_speed()
    voice_id = config.ELEVENLABS_VOICE_ID
    trim_sil = bool(getattr(config, "TTS_TRIM_LONG_SILENCES", False))
    max_sil_ms = float(getattr(config, "TTS_MAX_SILENCE_MS", 250))
    sil_thr = float(getattr(config, "TTS_SILENCE_THRESHOLD_DB", -40))
    cache_key = (
        f"{full_text}|v={voice_id}|s={native_speed:.3f}|a={atempo:.3f}"
        f"|trim={int(trim_sil)}|maxsil={max_sil_ms:.0f}|thr={sil_thr:.1f}"
    )
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
        logger.info("[1-shot TTS] 全 %d 文字を生成中... (hash=%s, "
                    "native_speed=%.2f, atempo=%.2f)",
                    len(full_text), text_hash, native_speed, atempo)
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

        if trim_sil:
            max_sec = max_sil_ms / 1000.0
            # 検出最小尺は max_sec より少し大きい無音を狙う
            detect_min = max(0.05, max_sec * 0.8)
            silences = _detect_silences(full_mp3, sil_thr, detect_min)
            if silences:
                logger.info(
                    "[1-shot TTS] 無音 %d 区間検出 (>= %.0fms) → %.0fms に圧縮",
                    len(silences), detect_min * 1000, max_sil_ms,
                )
                _apply_silenceremove_inplace(full_mp3, max_sec, sil_thr)
                with open(timestamps_json) as f:
                    raw_char_ts = json.load(f)
                _adjust_timestamps_for_silence_trim(
                    raw_char_ts, silences, max_sec)
                with open(timestamps_json, "w") as f:
                    json.dump(raw_char_ts, f)

        if abs(atempo - 1.0) > 0.001:
            logger.info("[1-shot TTS] atempo=%.3f で速度補正中...", atempo)
            _apply_atempo_inplace(full_mp3, atempo)

    if need_regen and abs(atempo - 1.0) > 0.001:
        # APIが atempoを掛けた直後 → timestamps_json も保存し直す (atempo分割引)
        with open(timestamps_json) as f:
            raw = json.load(f)
        for entry in raw:
            entry["start"] = float(entry["start"]) / atempo
            entry["end"] = float(entry["end"]) / atempo
        with open(timestamps_json, "w") as f:
            json.dump(raw, f)

    # per-line audio + scene audio を 既存tts_full.mp3 から再構築
    # (per-line speed / silence_after_ms を反映)
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
    """tts_full.mp3 (one-shot生成) を返す。"""
    if screenplay.get("audio_mode") == "silent":
        return None
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
    """単一シーンの背景画像を再生成。下流のkling/scene動画も無効化。"""
    scene = screenplay["scenes"][scene_idx]
    for fname in [
        f"bg_{scene_idx:03d}.png",
        f"composite_{scene_idx:03d}.png",
        f"kling_{scene_idx:03d}.mp4",
        f"scene_{scene_idx:03d}.trim.mp4",
        f"audio_{scene_idx:03d}.m4a",
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
        anim_prompt = _get_animation_prompt(scene)
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
