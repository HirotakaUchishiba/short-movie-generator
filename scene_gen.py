import glob
import hashlib
import json
import logging
import os
import shutil
import subprocess as sp
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image

import artifact_integrity
import atomic_assets
import composition_id as composition_id_module
import config
import elevenlabs_client
import fal_video_client
import bg_cache
import imagen_client
import kling_cache
import lipsync_client
from cost_tracking import recorder as cost_recorder

SCREENPLAY_TEXT_SEPARATOR = "  "  # 半角スペース×2: line間/scene間の区切り

# per-line audio 切出時の最小 speech duration。0 だと ffmpeg -t 0 で空 file が
# 出るので最小 50ms を保証する (= 後段の atempo / silenceremove も無音 file に
# 対しては早期 return するため 50ms あれば安全)。
MIN_SPEECH_DURATION_SEC = 0.05

# ffmpeg silence source の audio layout。tts 合成時に background 無音を生成する
# 際に複数箇所で参照されるため定数化。
FFMPEG_SILENCE_AUDIO_LAYOUT = "anullsrc=r=44100:cl=stereo"

logger = logging.getLogger(__name__)


def _project_ts(temp_dir: str) -> str:
    """``temp/<TS>/...`` 規約から TS 文字列を抽出 (cost 記録用)。"""
    return os.path.basename(temp_dir.rstrip(os.sep))

BG_PARALLEL_WORKERS = 4


class PartialBackgroundFailure(RuntimeError):
    """Stage 3 で一部のシーンが失敗したことを示す。

    成功シーンの ``tmp/bg_<S>.png`` は保持される (= UI / CLI で失敗シーンのみ
    個別再生成で復旧可能)。``failed_scene_indices`` は 0-origin。
    """

    def __init__(self, failed: list[int], total: int,
                 errors: dict[int, str] | None = None) -> None:
        self.failed_scene_indices = sorted(failed)
        self.total_scenes = total
        self.errors = errors or {}
        succeeded = total - len(self.failed_scene_indices)
        msg = (
            f"Stage 3 (BG) 部分失敗: {succeeded}/{total} シーン成功、"
            f"失敗シーン (0-origin): {self.failed_scene_indices}。"
            "成功した bg_<S>.png は temp/ に保持されているので、"
            "失敗シーンのみ個別再生成で復旧してください。"
        )
        super().__init__(msg)


class PartialKlingFailure(RuntimeError):
    """Stage 4 で一部のシーンが失敗したことを示す。

    成功シーンの ``tmp/kling_<S>.mp4`` / ``tmp/scene_<S>.trim.mp4`` は保持
    されるので、UI / CLI で失敗シーンのみ個別再生成で復旧できる。
    ``failed_scene_indices`` は 0-origin。
    """

    def __init__(self, failed: list[int], total: int,
                 errors: dict[int, str] | None = None) -> None:
        self.failed_scene_indices = sorted(failed)
        self.total_scenes = total
        self.errors = errors or {}
        succeeded = total - len(self.failed_scene_indices)
        msg = (
            f"Stage 4 (Kling) 部分失敗: {succeeded}/{total} シーン成功、"
            f"失敗シーン (0-origin): {self.failed_scene_indices}。"
            "成功した kling_<S>.mp4 / scene_<S>.trim.mp4 は temp/ に保持されている"
            "ので、UI から失敗シーンのみ個別再生成で復旧してください。"
        )
        super().__init__(msg)


def _run_bg_pool_collecting(
    submit_args: list[tuple[int, dict]],
    temp_dir: str,
    screenplay: dict,
) -> tuple[dict[str, str], dict[int, BaseException]]:
    # 1 シーンの例外で全体を止めず、成功 dict と失敗 dict に振り分けて返す。
    # raise / mark_generated / ログ集計は呼び出し側責務。
    bg_paths: dict[str, str] = {}
    errors: dict[int, BaseException] = {}
    if not submit_args:
        return bg_paths, errors
    with ThreadPoolExecutor(max_workers=BG_PARALLEL_WORKERS) as pool:
        futures = {
            pool.submit(_generate_background_with_retry, i, scene,
                        temp_dir, screenplay): i
            for i, scene in submit_args
        }
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                bg_key, path = fut.result()
            except BaseException as e:
                errors[i] = e
                logger.exception("シーン%d 背景生成失敗: %s", i + 1, e)
                continue
            bg_paths[bg_key] = path
            screenplay["scenes"][i]["_bg_key"] = bg_key
    return bg_paths, errors


# emotion 派生 helper は stages/emotion.py を SSOT とし、ここでは互換 shim。
from stages import emotion as _emotion  # noqa: E402


def _dominant_emotion(scene: dict) -> str | None:
    return _emotion.dominant_emotion(scene)


def _emotion_arc_en(scene: dict) -> str:
    return _emotion.emotion_arc_en(scene)


def _emotion_arc_summary(scene: dict, cue_key: str) -> str:
    return _emotion.emotion_arc_summary(scene, cue_key)


def _dominant_visual_cues(scene: dict) -> dict:
    return _emotion.dominant_visual_cues(scene)


_CUE_LABELS_KLING = {
    "motion": "motion",
    "facial": "facial expression",
    "tone": "tone",
    "eye_gaze": "eye gaze",
    "body_posture": "body posture",
    "camera": "camera",
}


def _get_animation_prompt(scene: dict, ts_path: str | None = None,
                          s_idx: int | None = None,
                          screenplay: dict | None = None) -> str:
    """Kling 用 animation_prompt を合成する (SSOT準拠 / 完全英文)。

    優先順位:
      0. scene._override_animation_prompt (= novel intent escape hatch)
      1. scene.animation_prompt (compose 由来 = subject speaks naturally ...)
      2. scene.action_id があれば actions/<id>.json の animation_motion (Phase X-2a)
      3. 無い場合は background_prompt をベースにフォールバック

    base に emotion arc (英訳) / Stage 4 用 dom_cues / audio_dynamics を注入。

    `_override_animation_prompt` が設定されている場合は emotion arc / dom_cues /
    audio_dynamics の追記を一切行わず文字列をそのまま base として使う (= ただし
    `_augment_animation_prompt` で frontload + negative constraint は付く)。
    compositional architecture の `clip_library` に該当 entry が無い scene を
    1 回だけ generate して promote させる経路。
    """
    override = scene.get("_override_animation_prompt")
    if isinstance(override, str) and override.strip():
        logger.info(
            "[scene-gen] _override_animation_prompt 採用 (scene %s): %r",
            s_idx if s_idx is not None else "?", override[:80],
        )
        return override.strip()

    explicit = scene.get("animation_prompt")
    base: str = ""
    if explicit:
        base = explicit
    else:
        action_id = scene.get("action_id")
        if action_id:
            try:
                action = atomic_assets.load_action(action_id)
                base = action.get("animation_motion") or ""
            except atomic_assets.AtomicAssetNotFound as e:
                logger.warning("atomic action load failed: %s", e)
    if not base:
        bg_prompt = scene.get("background_prompt", "")
        base = f"gentle cinematic motion, {bg_prompt}"

    extras: list[str] = []

    arc_en = _emotion_arc_en(scene)
    if arc_en:
        extras.append(f"emotion arc: {arc_en}")

    dom_cues = _dominant_visual_cues(scene)
    for cat in config.STAGE_CUE_CATEGORIES["kling"]:
        label = _CUE_LABELS_KLING.get(cat)
        if not label:
            continue
        v = dom_cues.get(cat)
        if v:
            extras.append(f"{label}: {v}")

    # 動的情報 (= テンポ・声量) は動画にのみ意味があるので Kling のみで注入
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


# Stage 別分割 (= stages/__init__.py 参照) の第一歩として、TTS 直前のテキスト
# 整形 helper は stages/text_utils.py を SSOT とする。ここでは shim を残す。
from stages import text_utils as _text_utils  # noqa: E402


def _clean_text(text: str) -> str:
    return _text_utils.clean_text(text)


def _apply_pronunciation_hints(text: str, hints: dict | None,
                                global_dict: dict | None = None) -> str:
    return _text_utils.apply_pronunciation_hints(text, hints, global_dict)


def _load_global_furigana_dict() -> dict[str, str]:
    """stages.text_utils.load_global_furigana_dict への shim (§3.1.1)。"""
    return _text_utils.load_global_furigana_dict()


def _neighbor_line_text(screenplay: dict | None, scene_idx: int,
                         line_idx: int, direction: str) -> str | None:
    """stages.text_utils.neighbor_line_text への shim (§3.1.1)。"""
    return _text_utils.neighbor_line_text(
        screenplay, scene_idx, line_idx, direction,
    )


from stages import audio_helpers as _audio_helpers_for_trim  # noqa: E402


def _trim_internal_pauses(input_path: str, output_path: str) -> None:
    """stages.audio_helpers.trim_internal_pauses への shim (§3.1.1-d)。"""
    _audio_helpers_for_trim.trim_internal_pauses(input_path, output_path)


from stages import ffmpeg_helpers as _ffmpeg_helpers  # noqa: E402


def _apply_volume(input_path: str, db: float, output_path: str) -> None:
    """stages.ffmpeg_helpers.apply_volume への shim (§3.1.1-c)。"""
    return _ffmpeg_helpers.apply_volume(input_path, db, output_path)


from stages import image_helpers as _image_helpers  # noqa: E402


def _prepare_background(bg_path: str, output_path: str) -> None:
    """stages.image_helpers.prepare_background への shim (§3.1.1-d)。"""
    _image_helpers.prepare_background(bg_path, output_path)


from stages import character_refs as _character_refs  # noqa: E402


def _resolve_character_refs(scene: dict) -> list[str]:
    """stages.character_refs.resolve_character_refs への shim (§3.1.1-b)。"""
    return _character_refs.resolve_character_refs(scene)


_CUE_LABELS_BG = {
    "lighting": "lighting and color",
    "facial": "facial expression",
    "tone": "tone",
}


def _build_background_prompt(scene: dict, screenplay: dict | None = None,
                              ts_path: str | None = None,
                              s_idx: int | None = None) -> str:
    """Imagen 用 background prompt を合成する (SSOT準拠 / 完全英文)。

    SSOT 入力:
      - scene.location_ref → locations/<id>.json (= ロケ詳細はここでのみ展開)
      - scene.background_prompt (compose 由来 = カメラ距離 + 人物表現)
      - lines[].emotion (per-line) → EMOTION_VISUAL_CUES の Stage 3 用カテゴリ

    衣装と人物特定は reference 画像が SSOT。動的情報 (audio_dynamics) は
    静止画には作用しないため Stage 4 (Kling) のみで使う。

    `_override_background_prompt` (= novel intent / 緊急対応用 escape hatch) が
    screenplay に設定されている場合は、location 注入や emotion cue を一切経由
    せず文字列をそのまま採用する。compositional architecture の `clip_library`
    に該当 entry が無い scene を 1 回だけ generate して promote させる経路。
    """
    override = scene.get("_override_background_prompt")
    if isinstance(override, str) and override.strip():
        logger.info(
            "[scene-gen] _override_background_prompt 採用 (scene %s): %r",
            s_idx if s_idx is not None else "?", override[:80],
        )
        return override.strip()

    from analyze import location as loc_mod

    loc_parts: list[str] = []
    loc: dict = {}
    identity = scene.get("identity") or {}
    loc_ref = identity.get("location_ref")
    if loc_ref:
        try:
            loc_obj = loc_mod.load_location(loc_ref)
            loc = loc_obj.to_dict()
        except FileNotFoundError:
            logger.warning("location '%s' が見つかりません", loc_ref)
        for label, key in [
            ("location decor (consistent across scenes)", "decor"),
            ("location lighting", "lighting"),
            ("location color palette", "color_palette"),
            ("location props", "props"),
        ]:
            v = loc.get(key)
            if v:
                loc_parts.append(f"{label}: {v}")

    bg_prompt = scene.get("background_prompt", "")
    if not bg_prompt:
        # Phase X-2a: action_id があれば atomic SSOT の subject_state を採用
        action_id = scene.get("action_id")
        if action_id:
            try:
                action = atomic_assets.load_action(action_id)
                bg_prompt = action.get("subject_state") or ""
            except atomic_assets.AtomicAssetNotFound as e:
                logger.warning("atomic action load failed: %s", e)
    parts: list[str] = loc_parts + [bg_prompt]

    # Stage 3 用 cue カテゴリのみに絞る (= hair / body_posture 等は Stage 4 担当、
    # Imagen が再解釈してキャラ崩壊するのを抑制)
    dom_cues = _dominant_visual_cues(scene)
    suppressed: set[str] = set()
    if loc.get("lighting") or loc.get("color_palette"):
        suppressed.add("lighting")
    for cat in config.STAGE_CUE_CATEGORIES["bg"]:
        label = _CUE_LABELS_BG.get(cat)
        if not label or cat in suppressed:
            continue
        v = dom_cues.get(cat)
        if v:
            parts.append(f"{label}: {v}")

    # storyboard 抑止: 通常時は最小、retry 時に詳細注入
    parts.append("single still photograph, not a storyboard or panels")
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
    # 呼び出しごとに cache 関連 hint をリセット (= UI 連携のため scene に書き戻す)
    scene.pop("_bg_cache_hit", None)
    scene.pop("_bg_cache_key", None)

    bg_key, path = _generate_single_background(scene_idx, scene, temp_dir, screenplay)

    # cache hit ならそのまま返す (= storyboard 検出済みでない画像のみ store する設計)
    if scene.get("_bg_cache_hit"):
        return bg_key, path

    attempt = 0
    while _detect_storyboard_image(path) and attempt < max_retries:
        attempt += 1
        try:
            os.remove(path)
        except OSError as e:
            logger.warning(
                "[storyboard-retry] %s 削除失敗: %s", path, e,
            )
        logger.warning("シーン%d 背景画像にコマ割り検出 → retry %d/%d",
                       scene_idx + 1, attempt, max_retries)
        scene["_storyboard_retry_neg"] = (
            f"RETRY ATTEMPT {attempt}: ABSOLUTELY single image, "
            "single horizontal frame, no vertical stacking of images, "
            "NEVER multi-panel layout, ONE photograph only"
        )
        bg_key, path = _generate_single_background(scene_idx, scene, temp_dir, screenplay)

    scene.pop("_storyboard_retry_neg", None)

    storyboard = _detect_storyboard_image(path)
    if attempt >= max_retries and storyboard:
        logger.error("シーン%d 背景画像のコマ割り回避失敗。生成画像をそのまま使用", scene_idx + 1)

    # 最終確定画像を cache に保存 (= storyboard 通過後のみ、retry 結果も含めて 1 度だけ)
    if (
        getattr(config, "BG_CACHE_ENABLED", True)
        and screenplay is not None
        and not storyboard
        and not scene.get("_bg_force_no_cache")
        and not scene.get("_bg_cache_hit")
    ):
        try:
            cache_key = bg_cache.compute_bg_cache_key(scene, screenplay)
            identity = scene.get("identity") or {}
            bg_cache.store(cache_key, path, {
                "scene_idx": scene_idx,
                "model": getattr(imagen_client, "MODEL", "unknown"),
                "location_ref": identity.get("location_ref"),
                "character_refs": list(identity.get("character_refs") or []),
            })
            scene["_bg_cache_key"] = cache_key
        except Exception as e:
            logger.warning("bg_cache store failed: %s", e)

    return bg_key, path


def _get_duration(path: str) -> float:
    """stages.ffmpeg_helpers.get_duration への shim (§3.1.1-c)。"""
    return _ffmpeg_helpers.get_duration(path)


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


def _extend_video_to_duration(input_path: str, target_duration: float,
                              output_path: str) -> None:
    """slow_mo で映像を target_duration まで引き伸ばす。音声トラックは捨てる
    (input は trim 段階で -an のため元から無音想定)。

    setpts=PTS*ratio で全フレームを等倍にスローモーション化する。
    ratio < 1.0 (= 短縮) の呼出は誤用なのでエラーにする。
    """
    cur = _get_duration(input_path)
    if cur <= 0.0:
        raise RuntimeError(f"動画尺取得に失敗: {input_path}")

    ratio = target_duration / cur
    if ratio <= 1.0 + 1e-3:
        # 既に十分長い → 単純コピーで output を作る
        shutil.copyfile(input_path, output_path)
        return

    if ratio > 2.0:
        logger.warning(
            "slow_mo ratio が大きすぎます (%.2fx)。動画 %.2fs → %.2fs に延長します",
            ratio, cur, target_duration,
        )

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter_complex", f"[0:v]setpts=PTS*{ratio:.6f}[v]",
        "-map", "[v]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Video slow_mo extension failed: {r.stderr[-500:]}")


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
            "-f", "lavfi", "-i", FFMPEG_SILENCE_AUDIO_LAYOUT,
            "-t", f"{scene_duration:.3f}",
            "-c:a", "aac", "-b:a", "192k",
            output_path,
        ]
        r = sp.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"Silent audio generation failed: {r.stderr[-500:]}")
        return

    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", FFMPEG_SILENCE_AUDIO_LAYOUT]
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


from stages import prompts as _prompts  # noqa: E402


def _augment_animation_prompt(base_prompt: str, kling_duration: float) -> str:
    """stages.prompts.augment_animation_prompt への shim (§3.1.1-a)。"""
    return _prompts.augment_animation_prompt(base_prompt, kling_duration)


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


def _generate_single_background(scene_idx: int, scene: dict, temp_dir: str,
                                screenplay: dict | None = None,
                                force_fresh: bool = False) -> tuple[str, str]:
    """1 シーン分の BG 画像を生成または cache から取得する。

    force_fresh=True: cache lookup をスキップして必ず Imagen API を呼ぶ。
    """
    bg_key = f"bg_{scene_idx:03d}"
    path = os.path.join(temp_dir, f"{bg_key}.png")

    if os.path.exists(path) and artifact_integrity.check_existing(
        path, "png", label=f"scene {scene_idx + 1} BG",
    ):
        return bg_key, path

    # cache lookup: storyboard retry 時 (= _storyboard_retry_neg ありの再呼び出し)
    # と force_no_cache / force_fresh 時はバイパス。screenplay が未渡しの古い経路もスキップ。
    use_cache = (
        getattr(config, "BG_CACHE_ENABLED", True)
        and screenplay is not None
        and not force_fresh
        and not scene.get("_storyboard_retry_neg")
        and not scene.get("_bg_force_no_cache")
        and not scene.get("bg_force_fresh")
    )
    cache_key: str | None = None
    if use_cache:
        try:
            cache_key = bg_cache.compute_bg_cache_key(scene, screenplay)
            cached_path = bg_cache.lookup(cache_key)
            if cached_path is not None:
                shutil.copyfile(str(cached_path), path)
                bg_cache.touch(cache_key)
                scene["_bg_cache_hit"] = True
                scene["_bg_cache_key"] = cache_key
                logger.info("[bg cache HIT] %s key=%s", bg_key, cache_key)
                return bg_key, path
        except Exception as e:
            logger.warning("bg_cache lookup failed: %s", e)
            cache_key = None

    enhanced = _build_background_prompt(scene, screenplay, ts_path=temp_dir,
                                          s_idx=scene_idx)
    full_prompt = f"{enhanced}. no text, no letters, vertical portrait composition"
    refs = _resolve_character_refs(scene)
    logger.info("%s 生成中 (参照キャラ: %d枚)", bg_key, len(refs))
    imagen_client.generate_image(full_prompt, path, reference_images=refs or None)
    logger.info("%s → %s", bg_key, path)
    try:
        cost_recorder.record_imagen(
            project_ts=_project_ts(temp_dir),
            model=imagen_client.MODEL,
            scene_index=scene_idx,
            operation="regenerate" if force_fresh else "generate",
        )
    except Exception:
        logger.exception("cost recording failed (bg, scene=%d)", scene_idx)
    if cache_key:
        scene["_bg_cache_hit"] = False
        scene["_bg_cache_key"] = cache_key
    return bg_key, path


def _scene_bg_inputs(scene_idx: int, scene: dict, screenplay: dict,
                     temp_dir: str) -> dict | None:
    """この scene の BG 生成入力を決定する純粋関数 (= scan/commit/fresh で共有)。

    必要な依存 (= ロケ JSON や character ref 画像) が揃わないと None を返す。
    """
    try:
        cache_key = bg_cache.compute_bg_cache_key(scene, screenplay)
    except Exception as e:
        logger.warning("bg_cache key 計算失敗 scene=%d: %s", scene_idx, e)
        return None
    enhanced = _build_background_prompt(
        scene, screenplay, ts_path=temp_dir, s_idx=scene_idx)
    return {
        "cache_key": cache_key,
        "background_prompt_resolved": enhanced,
        "model_id": getattr(imagen_client, "MODEL", "unknown"),
    }


def _build_bg_cache_meta(scene: dict, scene_idx: int, inputs: dict) -> dict:
    """store() に渡す metadata を組み立てる。"""
    identity = scene.get("identity") or {}
    location_ref = identity.get("location_ref")
    character_refs = list(identity.get("character_refs") or [])
    camera_distance = identity.get("camera_distance")
    action_id = scene.get("action_id")
    composition_version = composition_id_module.resolve_version(
        action_id=action_id,
    )
    return {
        "scene_idx": scene_idx,
        "model": inputs["model_id"],
        "model_id": inputs["model_id"],
        "background_prompt_resolved": inputs["background_prompt_resolved"],
        "location_ref": location_ref,
        "character_refs": character_refs,
        "camera_distance": camera_distance,
        "cache_version": getattr(config, "BG_CACHE_VERSION", "v1"),
        "action_id": action_id,
        "composition_id": composition_id_module.compute_composition_id(
            location_ref=location_ref,
            character_refs=character_refs,
            action_id=action_id,
            version=composition_version,
        ),
        "composition_version": composition_version,
    }


def bg_scan_cache(screenplay: dict, temp_dir: str) -> dict:
    """Stage 3a: 全シーンで cache lookup を行い、判断状態を組み立てて返す。

    API 呼び出しは行わない (= 純粋に local + cache disk のみ)。
    候補なしのシーンは "decision":"fresh" 即確定 (= ユーザ操作不要)。
    """
    decisions: dict[str, dict] = {}
    cache_enabled = getattr(config, "BG_CACHE_ENABLED", True)
    for i, scene in enumerate(screenplay.get("scenes") or []):
        rec: dict = {
            "candidates": [],
            "decision": "pending",
            "decided_key": None,
            "decided_at": None,
            "cache_key": None,
            "diagnostics": [],
        }
        try:
            inputs = _scene_bg_inputs(i, scene, screenplay, temp_dir)
        except Exception as e:
            rec["diagnostics"].append(f"input build failed: {e}")
            inputs = None
        if inputs is None:
            rec["diagnostics"].append("dependency missing (location/character)")
            decisions[str(i)] = rec
            continue
        rec["cache_key"] = inputs["cache_key"]
        if cache_enabled and not scene.get("bg_force_fresh"):
            try:
                candidates = bg_cache.lookup_all_candidates(
                    inputs["cache_key"], scene)
                rec["candidates"] = [
                    {
                        "key": c["key"],
                        "fitness": c["fitness"],
                        "warnings": c["warnings"],
                        "meta": {
                            "location_ref": c["meta"].get("location_ref"),
                            "camera_distance": c["meta"].get("camera_distance"),
                            "character_refs": c["meta"].get("character_refs"),
                            "created_at": c["meta"].get("created_at"),
                            "hit_count": c["meta"].get("hit_count"),
                            "background_prompt_resolved": c["meta"].get(
                                "background_prompt_resolved"),
                            "quality": c["meta"].get("quality"),
                        },
                    }
                    for c in candidates
                ]
            except Exception as e:
                rec["diagnostics"].append(f"lookup failed: {e}")
        if not rec["candidates"]:
            rec["decision"] = "fresh"
            rec["decided_at"] = _now_iso_seconds()
        decisions[str(i)] = rec
    return decisions


def _now_iso_seconds() -> str:
    from datetime import datetime as _dt
    return _dt.now().isoformat(timespec="seconds")


def _clear_bg_downstream(scene_idx: int, temp_dir: str) -> None:
    """BG を差し替える前に、bg / composite / kling / scene 系を削除する。"""
    for fname in [
        f"bg_{scene_idx:03d}.png",
        f"composite_{scene_idx:03d}.png",
        f"kling_{scene_idx:03d}.mp4",
        f"scene_{scene_idx:03d}.trim.mp4",
        f"scene_{scene_idx:03d}.extended.mp4",
        f"scene_{scene_idx:03d}.mp4",
    ]:
        p = os.path.join(temp_dir, fname)
        if os.path.exists(p):
            os.remove(p)


def bg_commit_cache(scene_idx: int, scene: dict, screenplay: dict,
                    temp_dir: str, cache_key: str) -> None:
    """Stage 3b: cache の PNG を bg_<S>.png に copy する。下流も削除して整合性確保。"""
    _clear_bg_downstream(scene_idx, temp_dir)
    bg_key = f"bg_{scene_idx:03d}"
    dest = os.path.join(temp_dir, f"{bg_key}.png")
    bg_cache.commit_to_project(cache_key, dest)
    scene["_bg_cache_hit"] = True
    scene["_bg_cache_key"] = cache_key
    scene["_bg_key"] = bg_key


def bg_generate_fresh(screenplay: dict, temp_dir: str,
                      scene_indices: list[int]) -> dict[str, str]:
    """Stage 3c: 指定シーンだけ Imagen で新規生成する (= retry/storyboard ロジック継承)。

    既存の `_generate_background_with_retry` を force_fresh 経由で呼ぶ。
    cache lookup はバイパス、生成成功後は cache に store される。
    """
    scenes = screenplay.get("scenes") or []
    if not scene_indices:
        return {}
    # force_fresh hint を一時的に立て、retry helper 内の _generate_single_background
    # で cache を必ず bypass させる
    for i in scene_indices:
        scenes[i]["bg_force_fresh"] = True
    try:
        submit_args = [(i, scenes[i]) for i in scene_indices]
        bg_paths, errors = _run_bg_pool_collecting(
            submit_args, temp_dir, screenplay)
    finally:
        for i in scene_indices:
            scenes[i].pop("bg_force_fresh", None)
    if errors:
        failed = list(errors.keys())
        succeeded = len(scene_indices) - len(failed)
        logger.info(
            "[背景] %d/%d シーン成功、失敗シーン: %s",
            succeeded, len(scene_indices), sorted(i + 1 for i in failed))
        raise PartialBackgroundFailure(
            failed, len(scene_indices),
            errors={i: repr(e) for i, e in errors.items()})
    return bg_paths


def generate_backgrounds(screenplay: dict, temp_dir: str,
                         scene_decisions: dict | None = None) -> dict[str, str]:
    """Stage 3 統合実行関数。

    scene_decisions が渡されたら:
      - decision="cache" のシーンは cache から copy
      - decision="fresh" / "pending" のシーンは Imagen で新規生成 (cache lookup あり)
    渡されなければ全シーン自動 (= 旧挙動、cache lookup あり)。
    """
    scenes = screenplay["scenes"]
    bg_paths: dict[str, str] = {}

    if scene_decisions:
        # 1. decision="cache" のシーンは同期 commit
        cache_indices: list[int] = []
        fresh_indices: list[int] = []
        for i, scene in enumerate(scenes):
            rec = scene_decisions.get(str(i)) or {}
            decision = rec.get("decision")
            decided_key = rec.get("decided_key")
            if decision == "cache" and decided_key:
                bg_commit_cache(i, scene, screenplay, temp_dir, decided_key)
                bg_paths[scene.get("_bg_key", f"bg_{i:03d}")] = os.path.join(
                    temp_dir, f"bg_{i:03d}.png")
                cache_indices.append(i)
            else:
                fresh_indices.append(i)
        # 2. fresh シーンは pool で並列生成 (= 失敗 1 件以上で PartialBackgroundFailure。
        #    cache 経由で commit 済みシーンの artifact はそのまま残す)
        try:
            fresh_paths = bg_generate_fresh(screenplay, temp_dir, fresh_indices)
        except PartialBackgroundFailure as e:
            logger.info(
                "[背景] cache=%d は確定済みのまま保持。fresh=%d 中 %d 失敗。",
                len(cache_indices), len(fresh_indices),
                len(e.failed_scene_indices))
            raise
        bg_paths.update(fresh_paths)
        logger.info("背景: %d枚 (cache=%d, fresh=%d)",
                    len(bg_paths), len(cache_indices), len(fresh_indices))
        return bg_paths

    # ─── legacy: 全シーン並列、cache lookup auto ───
    submit_args = list(enumerate(scenes))
    bg_paths, errors = _run_bg_pool_collecting(
        submit_args, temp_dir, screenplay)
    if errors:
        failed = list(errors.keys())
        succeeded = len(scenes) - len(failed)
        logger.info(
            "[背景] %d/%d シーン成功、失敗シーン: %s",
            succeeded, len(scenes), sorted(i + 1 for i in failed))
        raise PartialBackgroundFailure(
            failed, len(scenes),
            errors={i: repr(e) for i, e in errors.items()})

    logger.info("背景: %d枚", len(bg_paths))
    return bg_paths


from stages import text_mapping as _text_mapping  # noqa: E402


def _resolve_inline_tag(line: dict, scene: dict, line_idx: int) -> str:
    """stages.text_mapping.resolve_inline_tag への shim (§3.1.1-d)。"""
    return _text_mapping.resolve_inline_tag(line, scene, line_idx)


def _build_screenplay_text(screenplay: dict) -> tuple[str, list[dict]]:
    """stages.text_mapping.build_screenplay_text への shim。"""
    return _text_mapping.build_screenplay_text(screenplay)


def _build_position_to_time_map(
    input_text: str, char_timestamps: list[dict],
) -> list[dict | None]:
    """stages.text_mapping.build_position_to_time_map への shim。"""
    return _text_mapping.build_position_to_time_map(input_text, char_timestamps)


def _find_line_time_range(
    pos_to_time: list[dict | None], char_start: int, char_end: int,
) -> tuple[float | None, float | None]:
    """stages.text_mapping.find_line_time_range への shim。"""
    return _text_mapping.find_line_time_range(pos_to_time, char_start, char_end)


def _detect_all_silences(
    audio_path: str, threshold_db: float = -40.0,
    min_silence_sec: float = 0.03,
) -> list[tuple[float, float]]:
    """stages.audio_helpers.detect_all_silences への shim (§3.1.1-d)。"""
    from stages import audio_helpers as _ah
    return _ah.detect_all_silences(
        audio_path, threshold_db=threshold_db,
        min_silence_sec=min_silence_sec,
    )


def _snap_line_boundaries_to_silence(
    line_times: list[dict],
    silences: list[tuple[float, float]],
    snap_tolerance_sec: float = 0.2,
    min_speech_sec: float = MIN_SPEECH_DURATION_SEC,
) -> list[dict]:
    """stages.audio_helpers.snap_line_boundaries_to_silence への shim。"""
    from stages import audio_helpers as _ah
    return _ah.snap_line_boundaries_to_silence(
        line_times, silences,
        snap_tolerance_sec=snap_tolerance_sec,
        min_speech_sec=min_speech_sec,
    )


from stages import audio_helpers as _audio_helpers  # noqa: E402


def _extract_audio_segment(input_path: str, start_sec: float, duration: float,
                            output_path: str, codec: str = "aac",
                            bitrate: str = "192k") -> None:
    """stages.audio_helpers.extract_audio_segment への shim (§3.1.1-d)。"""
    _audio_helpers.extract_audio_segment(
        input_path, start_sec, duration, output_path,
        codec=codec, bitrate=bitrate,
    )


def _convert_to_aac(input_path: str, output_path: str,
                     bitrate: str = "192k") -> None:
    """stages.audio_helpers.convert_to_aac への shim。"""
    _audio_helpers.convert_to_aac(input_path, output_path, bitrate=bitrate)


def _concat_audios_to_aac(audio_paths: list[str], output_path: str) -> None:
    """stages.audio_helpers.concat_audios_to_aac への shim。"""
    _audio_helpers.concat_audios_to_aac(audio_paths, output_path)


def _natural_tail_silence_sec() -> float:
    """stages.audio_helpers.natural_tail_silence_sec への shim。"""
    return _audio_helpers.natural_tail_silence_sec()


def _concat_audios_to_mp3(audio_paths: list[str], output_path: str) -> None:
    """stages.audio_helpers.concat_audios_to_mp3 への shim。"""
    _audio_helpers.concat_audios_to_mp3(audio_paths, output_path)


def _extract_line_audio_segment(
    *,
    voice_mp3: str,
    voice_full_dur: float,
    abs_start: float,
    abs_end: float,
    next_abs_start_in_voice: float,
    out_path: str,
    trim_sil: bool,
    max_sil_sec: float,
    sil_thr: float,
    atempo: float,
) -> float:
    """voice の特定区間を切り出して per-line tts_<S>_<L>.mp3 を構築する共通処理。

    one-shot (full mp3 全 line) と per-voice (= voice 別 mp3) の両 path から
    使われる。body + trailing silence の構造で両者を concat した後、必要なら
    atempo を適用する。出力契約は両 path で完全に一致する。

    Returns:
        atempo 適用後の natural silence 実長 (= subtitle 計算用)。
    """
    if os.path.exists(out_path):
        os.remove(out_path)
    body_end = min(abs_end, voice_full_dur)
    speech_dur = max(MIN_SPEECH_DURATION_SEC, body_end - abs_start)
    tail_limit = min(next_abs_start_in_voice, voice_full_dur)
    desired = _natural_tail_silence_sec()
    available = max(0.0, tail_limit - body_end)
    natural_extract = max(0.0, min(desired, available))

    body_path = out_path + ".body.mp3"
    _extract_audio_segment(voice_mp3, abs_start, speech_dur, body_path,
                            codec="libmp3lame", bitrate="192k")
    if trim_sil:
        _apply_silenceremove_inplace(body_path, max_sil_sec, sil_thr)

    pieces = [body_path]
    if natural_extract > 0:
        tail_path = out_path + ".tail.mp3"
        _extract_audio_segment(voice_mp3, body_end, natural_extract, tail_path,
                                codec="libmp3lame", bitrate="192k")
        pieces.append(tail_path)
    _concat_audios_to_mp3(pieces, out_path)
    for p in pieces:
        if p != out_path and os.path.exists(p):
            os.remove(p)

    if abs(atempo - 1.0) > 0.001:
        _apply_atempo_inplace(out_path, atempo)

    return natural_extract / max(atempo, 1e-6)


def _assemble_scene_and_merged_audios(
    *,
    screenplay: dict,
    ts_path: str,
    by_scene: dict[int, list[dict]],
    line_actual_silences: dict[tuple[int, int], float],
) -> None:
    """per-line files から per-scene audio_<S>.m4a と merged_preview.m4a を構築。

    one-shot / per-voice 両 path で完全に同一の後段処理を共通化したもの。
    副作用として screenplay の scene["duration"] / line["start"] / line["end"]
    を更新する (= subtitle 計算に必要な派生値)。
    """
    for s_idx, scene in enumerate(screenplay["scenes"]):
        scene_lts = by_scene.get(s_idx, [])
        out_path = os.path.join(ts_path, f"audio_{s_idx:03d}.m4a")
        if os.path.exists(out_path):
            os.remove(out_path)
        if not scene_lts:
            scene["duration"] = 0.0
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
            line["start"] = round(cumulative, 3)
            line["end"] = round(cumulative + speech_dur, 3)
            cumulative += file_dur
            line_paths.append(line_path)
        scene["duration"] = cumulative + config.SCENE_TTS_TAIL_BUFFER
        _concat_audios_to_aac(line_paths, out_path)

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


def rebuild_audios_from_full_after_boundary_change(
    screenplay: dict, ts_path: str,
) -> None:
    """scene 境界変更後に tts_full.mp3 から per-line / per-scene を再分割する。

    staged_pipeline.apply_scene_boundaries() 等から呼ばれる public entry。
    内部実装は one-shot 経路 (= `_build_audios_from_full`) を流用する。
    per-voice 経路は scene/line 構造が変わると line_specs cache が無効化
    されるため、boundary 変更後にはフル再生成 (= Stage 2 再実行) に回す。
    """
    _build_audios_from_full(screenplay, ts_path)


def _build_audios_from_full(screenplay: dict, ts_path: str) -> None:
    """既存の tts_full.mp3 から per-line および scene audio を再構築する。

    Per-line 後処理パイプライン (timestamp drift 根絶のため全工程 line ファイル単位):
      1. [abs_start, abs_end] を speech body として切出し
      2. silenceremove を speech body にのみ適用 (mid-line の長い無音を圧縮)
      3. [abs_end, abs_end + tail_sec] を trailing として切出し (次line侵食しない範囲)
      4. body + trailing を concat → tts_<S>_<L>.mp3
      5. atempo を line file 全体に適用 (global_speed > native_max のとき)
    """
    full_mp3 = os.path.join(ts_path, "tts_full.mp3")
    timestamps_json = os.path.join(ts_path, "tts_full.json")
    if not os.path.exists(full_mp3) or not os.path.exists(timestamps_json):
        return

    # truncated tts_full.mp3 を放置すると ffprobe / silenceremove がエラーで
    # 死に、再 resume も同じ broken file を読んで詰む。事前に整合性を確認し、
    # broken なら関連ファイルごと一掃して呼び出し元に Stage 2 再実行を促す。
    if not artifact_integrity.is_valid_audio(full_mp3):
        logger.warning(
            "[整合性] tts_full.mp3 が壊れています — 削除して Stage 2 を再実行"
            "してください: %s", full_mp3,
        )
        for p in (full_mp3, timestamps_json,
                  os.path.join(ts_path, "tts_full.text_meta.json")):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError as e:
                logger.warning("[整合性] cleanup 失敗 %s: %s", p, e)
        raise RuntimeError(
            "tts_full.mp3 が破損していたため削除しました。"
            "Stage 2 (TTS) を再実行してください。"
        )

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

    # Step 1: 各 line を per-line で切出し (= 共通ヘルパー経由)
    line_actual_silences: dict[tuple[int, int], float] = {}
    for i, lt in enumerate(line_times):
        s_idx, l_idx = lt["scene_idx"], lt["line_idx"]
        out_path = os.path.join(ts_path, f"tts_{s_idx:03d}_{l_idx:03d}.mp3")
        next_abs_start = (
            line_times[i + 1]["abs_start"] if i + 1 < len(line_times)
            else float("inf")
        )
        line_actual_silences[(s_idx, l_idx)] = _extract_line_audio_segment(
            voice_mp3=full_mp3,
            voice_full_dur=full_audio_dur,
            abs_start=lt["abs_start"],
            abs_end=lt["abs_end"],
            next_abs_start_in_voice=next_abs_start,
            out_path=out_path,
            trim_sil=trim_sil,
            max_sil_sec=max_sil_sec,
            sil_thr=sil_thr,
            atempo=atempo,
        )

    # Step 2 + 3: scene 単位 audio_<S>.m4a + merged_preview を共通ヘルパーで構築
    _assemble_scene_and_merged_audios(
        screenplay=screenplay,
        ts_path=ts_path,
        by_scene=by_scene,
        line_actual_silences=line_actual_silences,
    )


def _clear_tts_artifacts(ts_path: str) -> None:
    """TTS生成物を全削除 (再生成前のクリーンアップ)。

    tts_full.<base>.{mp3,json,text_meta.json} (= per-voice intermediate)
    も `tts_full.*` glob で網羅される。
    """
    patterns = [
        "tts_full.mp3", "tts_full.json", "tts_full.text_meta.json",
        "tts_full.*",  # per-voice intermediate (= tts_full.<base>.mp3 等)
        "tts_*.mp3", "tts_*.json",
        "audio_*.m4a",
        "merged_preview.m4a",
    ]
    for pat in patterns:
        for f in glob.glob(os.path.join(ts_path, pat)):
            try:
                os.remove(f)
            except OSError as e:
                logger.warning("[tts-cleanup] %s 削除失敗: %s", f, e)


def _build_audios_from_per_voice(
    screenplay: dict,
    ts_path: str,
    per_voice_results: dict,
    full_text: str,
    line_specs: list[dict],
) -> None:
    """per-voice tts_full.<base>.mp3 群から per-line / per-scene / merged を構築。

    `_build_audios_from_full` の per-voice 版。各 line は line.speaker に
    対応する voice の音声から切り出される。出力契約 (= per-line
    tts_<S>_<L>.mp3 + per-scene audio_<S>.m4a + merged preview) は
    one-shot path と完全に同一なので下流 (Stage 4-6) は無変更で動く。

    Args:
      screenplay: composed screenplay
      ts_path: project temp dir
      per_voice_results: {base: PerVoiceResult} (= per_character_tts module)
      full_text: ElevenLabs に送ったテキスト (= line_specs.char_start の基準)
      line_specs: {scene_idx, line_idx, char_start, char_end}
    """

    import per_character_tts as pct
    from analyze import character_meta as cmeta_mod

    if not per_voice_results:
        return

    # 各 line に speaker base を割当 (= speaker 未設定は primary)。
    # per_voice_results に無い base は primary fallback (= analyze 漏れ等の defensive)。
    primary = pct.primary_speaker(screenplay)
    if primary is None or primary not in per_voice_results:
        # 何も speak されていない or primary も voice 未生成 → 早期 return
        return

    def _line_base(line: dict) -> str:
        spk = line.get("speaker")
        if isinstance(spk, str) and spk:
            base, _ = cmeta_mod.split_resolved_id(spk)
            if base and base in per_voice_results:
                return base
        return primary

    # ── per-voice の line_times を一度に計算 (= 各 voice の pos_to_time + snap)
    # 各 voice について「全 line」の time を計算する。実際に使うのはその voice の
    # line だけだが、silence-snap は隣接 line を考慮するため全 line を渡す必要がある。
    threshold_db = float(getattr(config, "TTS_SILENCE_THRESHOLD_DB", -40))
    snap_by_voice: dict[str, list[dict]] = {}
    for base, result in per_voice_results.items():
        if not os.path.exists(result.mp3_path):
            continue
        if not artifact_integrity.is_valid_audio(result.mp3_path):
            logger.warning(
                "[per-voice tts:%s] mp3 破損 — 当該 voice をスキップ", base,
            )
            continue
        with open(result.char_ts_path) as f:
            char_ts = json.load(f)
        pos_to_time = _build_position_to_time_map(full_text, char_ts)
        line_times: list[dict] = []
        for spec in line_specs:
            abs_start, abs_end = _find_line_time_range(
                pos_to_time, spec["char_start"], spec["char_end"],
            )
            if abs_start is None or abs_end is None:
                continue
            line_times.append({
                "scene_idx": spec["scene_idx"],
                "line_idx": spec["line_idx"],
                "abs_start": abs_start,
                "abs_end": abs_end,
            })
        silences = _detect_all_silences(
            result.mp3_path, threshold_db, min_silence_sec=0.03,
        )
        snap_by_voice[base] = _snap_line_boundaries_to_silence(
            line_times, silences,
        )

    if not snap_by_voice:
        return

    trim_sil = bool(getattr(config, "TTS_TRIM_LONG_SILENCES", False))
    max_sil_sec = float(getattr(config, "TTS_MAX_SILENCE_MS", 250)) / 1000.0
    sil_thr = float(getattr(config, "TTS_SILENCE_THRESHOLD_DB", -40))
    _native, atempo = _split_global_speed()

    # ── per-line file 構築 (= 各 line を「その speaker の voice」から共通ヘルパーで切出)
    line_actual_silences: dict[tuple[int, int], float] = {}
    by_scene: dict[int, list[dict]] = {}

    # screenplay 順に line を走査して per-line ファイルを作る
    for s_idx, scene in enumerate(screenplay["scenes"]):
        for l_idx, line in enumerate(scene.get("lines") or []):
            base = _line_base(line)
            voice_snap = snap_by_voice.get(base)
            if not voice_snap:
                continue
            lt = next(
                (t for t in voice_snap
                 if t["scene_idx"] == s_idx and t["line_idx"] == l_idx),
                None,
            )
            if lt is None:
                continue

            voice_mp3 = per_voice_results[base].mp3_path
            voice_full_dur = _get_duration(voice_mp3)

            # 同 voice 内の次 line の abs_start を tail upper bound に
            # (= 次 line が他 voice なら voice_full_dur を upper bound)
            same_voice_lines = [
                t for t in voice_snap
                if (t["scene_idx"], t["line_idx"]) > (s_idx, l_idx)
            ]
            next_abs_start = (
                min(t["abs_start"] for t in same_voice_lines)
                if same_voice_lines else float("inf")
            )

            out_path = os.path.join(
                ts_path, f"tts_{s_idx:03d}_{l_idx:03d}.mp3",
            )
            line_actual_silences[(s_idx, l_idx)] = _extract_line_audio_segment(
                voice_mp3=voice_mp3,
                voice_full_dur=voice_full_dur,
                abs_start=lt["abs_start"],
                abs_end=lt["abs_end"],
                next_abs_start_in_voice=next_abs_start,
                out_path=out_path,
                trim_sil=trim_sil,
                max_sil_sec=max_sil_sec,
                sil_thr=sil_thr,
                atempo=atempo,
            )
            by_scene.setdefault(s_idx, []).append({
                "scene_idx": s_idx,
                "line_idx": l_idx,
            })

    # ── per-scene audio_<S>.m4a + merged_preview (= 共通ヘルパー、one-shot と同計算)
    _assemble_scene_and_merged_audios(
        screenplay=screenplay,
        ts_path=ts_path,
        by_scene=by_scene,
        line_actual_silences=line_actual_silences,
    )

    # ── merged tts_full.mp3 (= 後方互換、preview と同等) を per-line から構築
    # 単独話者 path では tts_full.mp3 が API 出力そのものだが、per-voice
    # path では「最終 merge 結果」として per-line を concat する。
    line_paths_all: list[str] = []
    for s_idx, scene in enumerate(screenplay["scenes"]):
        for l_idx, _line in enumerate(scene.get("lines") or []):
            p = os.path.join(ts_path, f"tts_{s_idx:03d}_{l_idx:03d}.mp3")
            if os.path.exists(p):
                line_paths_all.append(p)
    if line_paths_all:
        merged_full = os.path.join(ts_path, "tts_full.mp3")
        if os.path.exists(merged_full):
            os.remove(merged_full)
        _concat_audios_to_mp3(line_paths_all, merged_full)


def _split_global_speed(target: float | None = None) -> tuple[float, float]:
    """stages.audio_helpers.split_global_speed への shim (§3.1.1-d)。"""
    return _audio_helpers.split_global_speed(target)


def _apply_atempo_inplace(input_path: str, atempo: float) -> None:
    """stages.audio_helpers.apply_atempo_inplace への shim (§3.1.1-d)。"""
    return _audio_helpers.apply_atempo_inplace(input_path, atempo)


def _apply_silenceremove_inplace(
    input_path: str, max_silence_sec: float, threshold_db: float,
) -> None:
    """stages.audio_helpers.apply_silenceremove_inplace への shim。"""
    return _audio_helpers.apply_silenceremove_inplace(
        input_path, max_silence_sec, threshold_db,
    )


def _full_screenplay_voice_settings() -> dict:
    """stages.audio_helpers.full_screenplay_voice_settings への shim。"""
    return _audio_helpers.full_screenplay_voice_settings()


def generate_screenplay_tts_one_shot(screenplay: dict, ts_path: str) -> dict | None:
    """Stage 2: screenplay TTS 生成 (= single-voice / per-character の dispatcher)。

    line.speaker から unique speaker base 数を数えて分岐:
      - 0 or 1 speaker → 既存の 1 ElevenLabs API call (= true "one-shot")。
        後方互換のため bit-exact で同じ挙動 / 同じ cache。
      - 2+ speakers → per-character 並列生成 (= per_character_tts module)
        + cut & merge (= _build_audios_from_per_voice)。各 line は
        該当 speaker の voice で発話された音声から切り出される。

    関数名に "one_shot" が残るのは callers (staged_pipeline / regen route)
    互換のため。実体は dispatcher。
    """

    if not config.ELEVENLABS_API_KEY:
        logger.warning("ELEVENLABS_API_KEY未設定でTTSスキップ")
        return None

    full_text, line_specs = _build_screenplay_text(screenplay)
    if not full_text.strip():
        return None

    import per_character_tts as pct
    speakers = pct.collect_unique_speakers(screenplay)
    if len(speakers) >= 2:
        return _generate_multi_voice_tts(
            screenplay, ts_path, full_text, line_specs, speakers,
        )
    return _generate_single_voice_tts(
        screenplay, ts_path, full_text, line_specs,
    )


def _generate_single_voice_tts(
    screenplay: dict, ts_path: str,
    full_text: str, line_specs: list[dict],
) -> dict | None:
    """既存の 1 ElevenLabs API call 経路 (= 単独話者 / speaker 完全 absent)。

    挙動・出力・cache 戦略は per-character 化以前と完全に同一。
    """

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
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(
                "[tts-cache] text_hash JSON load 失敗 path=%s: %s",
                text_meta_json, e,
            )

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
        # atomic write: 途中失敗で truncated tts_full.mp3 が残ると後段が詰まる
        # ので、まず .tmp に書き出して完全性を確認してから本パスに rename する。
        # generate_speech_with_timestamps は output_path から拡張子を切り捨てて
        # `<base>.json` に timestamps を書くため、tmp 名は ``.tmp.mp3`` の
        # 形にして tmp json が ``<...>.tmp.json`` に揃うようにする。
        full_mp3_tmp = os.path.join(ts_path, "tts_full.tmp.mp3")
        timestamps_tmp = os.path.join(ts_path, "tts_full.tmp.json")
        try:
            elevenlabs_client.generate_speech_with_timestamps(
                text=full_text,
                voice_id=vs["voice_id"],
                output_path=full_mp3_tmp,
                stability=vs["stability"],
                similarity_boost=vs["similarity_boost"],
                style=vs["style"],
                speed=vs["speed"],
                language=config.LANGUAGE,
                should_keep_whitespace=True,
            )
            if not artifact_integrity.is_valid_audio(full_mp3_tmp):
                raise RuntimeError(
                    "TTS 出力が ffprobe 検証を通過しませんでした (truncated?)",
                )
            os.replace(timestamps_tmp, timestamps_json)
            os.replace(full_mp3_tmp, full_mp3)
        except Exception:
            for p in (full_mp3_tmp, timestamps_tmp):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError as cleanup_err:
                    logger.warning(
                        "[tts-rollback] %s 削除失敗: %s", p, cleanup_err,
                    )
            raise
        try:
            cost_recorder.record_tts(
                project_ts=_project_ts(ts_path),
                model=elevenlabs_client.MODEL_ID,
                characters=len(full_text),
            )
        except Exception:
            logger.exception("cost recording failed (tts one-shot)")

    # per-line audio + scene audio を 既存tts_full.mp3 から再構築
    # (silenceremove + atempo は per-line で適用)
    _build_audios_from_full(screenplay, ts_path)

    with open(text_meta_json, "w") as f:
        json.dump({
            "text_hash": text_hash,
            "full_text": full_text,
            "separator": SCREENPLAY_TEXT_SEPARATOR,
            "line_specs": line_specs,
        }, f, ensure_ascii=False, indent=2)

    # _build_audios_from_full が memory 上で更新した
    # scene.duration / line.start / line.end を disk に永続化する。
    # 後段の Kling/Scene 生成が古い disk 値を読まないようにするため。
    # 並行 patch との衝突を避けるため field-level merge で書く。
    _persist_tts_derived_timings(screenplay, ts_path)

    logger.info("[1-shot TTS] 完了 (scenes=%d)",
                len(screenplay["scenes"]))
    return {"full_text": full_text}


def _generate_multi_voice_tts(
    screenplay: dict, ts_path: str,
    full_text: str, line_specs: list[dict],
    speakers: list[str],
) -> dict | None:
    """per-character voice 経路 (= 複数話者)。

    各 speaker の voice で screenplay 全文を並列生成 → line 順に該当 voice
    から切出して merged tts_full.mp3 + per-line + per-scene を構築する。

    各 voice の TTS は独立にキャッシュされる (= tts_full.<base>.text_meta.json)
    ため、speaker 1 人だけ voice_id を変えても他 voice は再呼出されない。
    """

    import per_character_tts as pct

    native_speed, _atempo = _split_global_speed()
    project_ts = _project_ts(ts_path)

    # 単独 voice 経路の cache file は競合避けて削除
    # (= 次に単独話者 screenplay に戻った時に正しく cache miss させる)
    for stale in ("tts_full.text_meta.json", "tts_full.json"):
        p = os.path.join(ts_path, stale)
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError as e:
                logger.warning("[multi-voice TTS] %s 削除失敗: %s", p, e)

    # ── per-voice 並列 TTS 生成 (= ElevenLabs N 並列 API call)
    per_voice_results = pct.generate_per_voice_full_audios(
        speakers=speakers,
        full_text=full_text,
        ts_path=ts_path,
        speed=native_speed,
        project_ts=project_ts,
    )

    # ── cut & merge (= per-line / per-scene / merged tts_full.mp3 を構築)
    _build_audios_from_per_voice(
        screenplay, ts_path, per_voice_results, full_text, line_specs,
    )

    # ── multi-voice marker (= 次回 single 化したら cache miss する形式)
    # 単独 voice path の text_hash field を含まないので、_generate_single_voice_tts
    # が次回読んでも cache hit せず再生成される。
    marker_path = os.path.join(ts_path, "tts_full.text_meta.json")
    with open(marker_path, "w") as f:
        json.dump({
            "mode": "multivoice",
            "speakers": speakers,
            "voice_ids": {
                base: r.voice_id for base, r in per_voice_results.items()
            },
            "per_voice_hashes": {
                base: r.text_hash for base, r in per_voice_results.items()
            },
            "full_text": full_text,
        }, f, ensure_ascii=False, indent=2)

    _persist_tts_derived_timings(screenplay, ts_path)

    logger.info(
        "[multi-voice TTS] 完了 (scenes=%d, voices=%d: %s)",
        len(screenplay["scenes"]), len(speakers), ",".join(speakers),
    )
    return {"full_text": full_text, "speakers": speakers}


def _persist_tts_derived_timings(screenplay: dict, ts_path: str) -> None:
    """TTS regen 後の scene.duration / line.start / line.end を
    tts_meta.json に書き出す (= snapshot は abstract のまま、SSOT 分離)。

    並行する patchLine / patchScene 等との衝突を避けるため、
    staged_pipeline.screenplay_lock を取得した上で書き込む。

    snapshot 側 (= screenplay.json) は完全 abstract に保たれるため、
    UI 編集の caption / emotion / speaker 等とは独立に timing を永続化できる。
    Stage 3 以降は load_project_screenplay 経由で hydrate された値を読む。
    """
    import project_state
    import staged_pipeline
    meta = project_state.read_metadata(ts_path)
    if not meta:
        return
    ts_key = os.path.basename(ts_path.rstrip(os.sep))

    with project_state.screenplay_lock(ts_key):
        meta_scenes: list[dict] = []
        for scene in screenplay.get("scenes") or []:
            scene_meta: dict = {}
            if "duration" in scene:
                scene_meta["duration"] = scene["duration"]
            line_metas: list[dict] = []
            for line in scene.get("lines") or []:
                lm: dict = {}
                if "start" in line:
                    lm["start"] = line["start"]
                if "end" in line:
                    lm["end"] = line["end"]
                line_metas.append(lm)
            scene_meta["lines"] = line_metas
            meta_scenes.append(scene_meta)
        staged_pipeline.save_tts_meta(ts_path, {"scenes": meta_scenes})
        logger.info(
            "[1-shot TTS] tts_meta.json に timing を書き出し: %s",
            staged_pipeline.tts_meta_path(ts_path),
        )


def build_merged_tts_preview(screenplay: dict, ts_path: str) -> str | None:
    """per-line audio を全 scene 連結した merged_preview.m4a を返す。

    `_build_audios_from_full` が生成する「実際に動画に乗る音」のプレビュー。
    atempo / silenceremove 反映済み。
    無ければ生 tts_full.mp3 (パディング未反映) にフォールバック。
    """
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
    """Stage 2: screenplay全体を1 API call で生成 (one-shot方式)。

    text_hashが変わらなければキャッシュ。返り値は line_times 等のメタ。
    """
    return generate_screenplay_tts_one_shot(screenplay, temp_dir)


def regen_tts_full(screenplay: dict, temp_dir: str, force: bool = True) -> None:
    """TTS全体を再生成する。

    force=True (既定): tts_full.mp3 等のキャッシュを削除して必ずElevenLabs API再呼び出し。
    force=False: キャッシュを保持し、text_hash不変ならAPI呼び出しスキップで
                 audioのみ再構築 (per-line speed 変更時に有用、無料)。
    """
    if force:
        _clear_tts_artifacts(temp_dir)
    generate_screenplay_tts_one_shot(screenplay, temp_dir)


def regen_tts_line(scene_idx: int, line_idx: int, screenplay: dict, temp_dir: str) -> None:
    """one-shot 方式では line 単位再生成は不可。screenplay 全体再生成にリダイレクト。"""
    logger.info("regen_tts_line(s=%d,l=%d) はscreenplay全体再生成にリダイレクト",
                scene_idx, line_idx)
    regen_tts_full(screenplay, temp_dir)


def regen_tts_scene(scene_idx: int, screenplay: dict, temp_dir: str) -> None:
    """one-shot 方式では scene 単位再生成は不可。screenplay 全体再生成にリダイレクト。"""
    logger.info("regen_tts_scene(s=%d) はscreenplay全体再生成にリダイレクト", scene_idx)
    regen_tts_full(screenplay, temp_dir)


def regen_background_scene(scene_idx: int, screenplay: dict, temp_dir: str,
                            force_fresh: bool = False) -> None:
    """単一シーンの背景画像を再生成。下流のkling/scene動画も無効化。

    audio_<S>.m4a は TTS 由来 (BG非依存) なので削除しない。
    force_fresh=True: cache lookup をバイパスして必ず Imagen を呼ぶ。
    既存の `force_no_cache` フラグ (= scene["_bg_force_no_cache"]) も同様に効く。
    """
    scene = screenplay["scenes"][scene_idx]
    _clear_bg_downstream(scene_idx, temp_dir)
    set_force = force_fresh and not scene.get("bg_force_fresh")
    if set_force:
        scene["bg_force_fresh"] = True
    try:
        bg_key, _ = _generate_background_with_retry(
            scene_idx, scene, temp_dir, screenplay)
    finally:
        if set_force:
            scene.pop("bg_force_fresh", None)
    scene["_bg_key"] = bg_key


def _scene_tts_audio_duration(scene_idx: int, ts_path: str) -> float:
    """one-shot で生成済み audio_<S>.m4a の尺を返す。なければ 0。"""
    p = os.path.join(ts_path, f"audio_{scene_idx:03d}.m4a")
    if os.path.exists(p):
        return _get_duration(p)
    return 0.0


def _scene_kling_inputs(
    scene_idx: int, scene: dict, screenplay: dict, temp_dir: str,
) -> dict | None:
    """この scene の Kling 生成入力を決定する純粋関数。

    cache key 計算 (= scan phase) と実生成 (= commit/fresh phase) で
    同じ入力を共有させるためのヘルパ。bg / TTS が揃っていない
    シーン (= 早すぎる scan) は None を返す。

    Returns:
        {"bg_path": str, "final_duration": float, "kling_duration": int,
         "anim_prompt": str, "augmented_prompt": str, "bg_image_sha": str,
         "model_id": str, "cache_key": str} or None
    """
    bg_path = _bg_path_for_scene(scene_idx, scene, temp_dir)
    if not os.path.exists(bg_path):
        return None

    final_duration = float(scene.get("duration") or 0.0)
    if final_duration <= 0:
        final_duration = _scene_tts_audio_duration(scene_idx, temp_dir)
    if final_duration <= 0:
        return None

    kling_duration = int(fal_video_client._pick_duration(final_duration))
    anim_prompt = _get_animation_prompt(
        scene, ts_path=temp_dir, s_idx=scene_idx, screenplay=screenplay)
    augmented = _augment_animation_prompt(anim_prompt, float(kling_duration))
    bg_image_sha = kling_cache._file_sha256(bg_path)
    model_id = fal_video_client.MODEL_ID
    cache_key = kling_cache.build_cache_key(
        augmented_animation_prompt=augmented,
        kling_duration=kling_duration,
        bg_image_sha=bg_image_sha,
        model_id=model_id,
    )
    return {
        "bg_path": bg_path,
        "final_duration": final_duration,
        "kling_duration": kling_duration,
        "anim_prompt": anim_prompt,
        "augmented_prompt": augmented,
        "bg_image_sha": bg_image_sha,
        "model_id": model_id,
        "cache_key": cache_key,
    }


def _build_kling_cache_meta(scene: dict, inputs: dict) -> dict:
    """store() に渡す metadata を組み立てる。"""
    identity = scene.get("identity") or {}
    location_ref = identity.get("location_ref")
    character_refs = list(identity.get("character_refs") or [])
    camera_distance = identity.get("camera_distance")
    action_id = scene.get("action_id")
    composition_version = composition_id_module.resolve_version(
        action_id=action_id,
    )
    return {
        "augmented_animation_prompt": inputs["augmented_prompt"],
        "kling_duration": int(inputs["kling_duration"]),
        "bg_image_sha": inputs["bg_image_sha"],
        "model_id": inputs["model_id"],
        "aspect_ratio": "9:16",
        "cache_version": getattr(config, "KLING_CACHE_VERSION", "v1"),
        "frontload_ratio": float(config.ACTION_FRONTLOAD_RATIO),
        "original_audio_duration": float(inputs["final_duration"]),
        "camera_distance": camera_distance,
        "location_ref": location_ref,
        "character_refs": character_refs,
        "action_id": action_id,
        "composition_id": composition_id_module.compute_composition_id(
            location_ref=location_ref,
            character_refs=character_refs,
            action_id=action_id,
            version=composition_version,
        ),
        "composition_version": composition_version,
    }


def _trim_and_finalize_kling(
    scene_idx: int, scene: dict, kling_raw_path: str, final_duration: float,
    temp_dir: str,
) -> None:
    """共通の trim + slow_mo 警告ロジック。cache hit でも fresh でも同じ。"""
    trimmed_path = os.path.join(temp_dir, f"scene_{scene_idx:03d}.trim.mp4")
    raw_dur = _get_duration(kling_raw_path)
    trim_at = min(final_duration, raw_dur)
    trimmed_skip_ok = (
        os.path.exists(trimmed_path)
        and artifact_integrity.check_existing(
            trimmed_path, "mp4", label=f"scene {scene_idx + 1} trim",
        )
    )
    if not trimmed_skip_ok:
        _trim_video(kling_raw_path, trim_at, trimmed_path)
        logger.info("シーン%d trim → %.2fs (final=%.2fs, raw=%.2fs)",
                    scene_idx + 1, trim_at, final_duration, raw_dur)
    if final_duration > raw_dur + 0.05:
        logger.warning(
            "シーン%d: TTS要求尺 %.2fs > Kling raw %.2fs。"
            "後段で slow_mo 延長します",
            scene_idx + 1, final_duration, raw_dur,
        )
    scene["duration"] = final_duration


def _kling_for_scene(scene_idx: int, scene: dict, screenplay: dict, temp_dir: str,
                     force_fresh: bool = False) -> None:
    """1シーン分のKling生成 + trim。Stage 2 (TTS) で確定した scene.duration が SSOT。

    force_fresh=False (= 既定): cache lookup → hit すれば copy、miss なら FAL 呼出
    force_fresh=True: cache を無視して必ず FAL 呼出。
    """
    bg_path = _bg_path_for_scene(scene_idx, scene, temp_dir)
    if not os.path.exists(bg_path):
        raise FileNotFoundError(f"背景画像が見つかりません: {bg_path}")

    final_duration = float(scene.get("duration") or 0.0)
    if final_duration <= 0:
        final_duration = _scene_tts_audio_duration(scene_idx, temp_dir)
    kling_duration = float(fal_video_client._pick_duration(final_duration))

    kling_raw_path = os.path.join(temp_dir, f"kling_{scene_idx:03d}.mp4")

    logger.info("シーン%d final=%.2fs kling=%.0fs",
                scene_idx + 1, final_duration, kling_duration)

    kling_raw_skip_ok = (
        os.path.exists(kling_raw_path)
        and artifact_integrity.check_existing(
            kling_raw_path, "mp4", label=f"scene {scene_idx + 1} Kling raw",
        )
    )
    if not kling_raw_skip_ok:
        is_cache_used = False
        cache_enabled = (
            getattr(config, "KLING_CACHE_ENABLED", True)
            and not force_fresh
            and not scene.get("kling_force_fresh")
        )
        if cache_enabled:
            try:
                inputs = _scene_kling_inputs(
                    scene_idx, scene, screenplay, temp_dir)
                if inputs:
                    identity = scene.get("identity") or {}
                    candidates = kling_cache.lookup_all_candidates(
                        inputs["cache_key"], final_duration,
                        identity.get("camera_distance"))
                    if candidates:
                        kling_cache.commit_to_project(
                            candidates[0]["key"], kling_raw_path)
                        scene["_kling_cache_hit"] = True
                        scene["_kling_cache_key"] = candidates[0]["key"]
                        is_cache_used = True
            except Exception as e:
                logger.warning("kling_cache lookup failed: %s", e)
        if not is_cache_used:
            anim_prompt = _get_animation_prompt(scene, ts_path=temp_dir,
                                                  s_idx=scene_idx,
                                                  screenplay=screenplay)
            _generate_kling(bg_path, anim_prompt, kling_duration,
                            kling_raw_path, scene_idx)
            scene["_kling_cache_hit"] = False
            try:
                cost_recorder.record_kling(
                    project_ts=_project_ts(temp_dir),
                    model=fal_video_client.MODEL_ID,
                    duration_sec=kling_duration,
                    scene_index=scene_idx,
                    operation="regenerate" if force_fresh else "generate",
                )
            except Exception:
                logger.exception("cost recording failed (kling, scene=%d)", scene_idx)
            # 生成に成功したら cache に store する (idempotent)
            try:
                inputs = _scene_kling_inputs(
                    scene_idx, scene, screenplay, temp_dir)
                if inputs:
                    kling_cache.store(
                        inputs["cache_key"], kling_raw_path,
                        _build_kling_cache_meta(scene, inputs))
                    scene["_kling_cache_key"] = inputs["cache_key"]
            except Exception as e:
                logger.warning("kling_cache store failed: %s", e)

    _trim_and_finalize_kling(
        scene_idx, scene, kling_raw_path, final_duration, temp_dir)


def kling_scan_cache(screenplay: dict, temp_dir: str) -> dict:
    """Stage 4a: 全シーンで cache lookup を行い、判断状態を組み立てて返す。

    API 呼び出しは行わない (= 純粋に local + cache disk のみ)。
    bg が未生成 / TTS 未実行のシーンは "decision":"pending" + 候補なしになる。

    Returns:
        scene_decisions dict ({"<scene_idx>": {...}, ...})
    """
    decisions: dict[str, dict] = {}
    cache_enabled = getattr(config, "KLING_CACHE_ENABLED", True)
    for i, scene in enumerate(screenplay.get("scenes") or []):
        rec: dict = {
            "candidates": [],
            "decision": "pending",
            "decided_key": None,
            "decided_at": None,
            "kling_duration": None,
            "final_duration": None,
            "cache_key": None,
            "diagnostics": [],
        }
        try:
            inputs = _scene_kling_inputs(i, scene, screenplay, temp_dir)
        except Exception as e:
            rec["diagnostics"].append(f"input build failed: {e}")
            inputs = None
        if inputs is None:
            rec["diagnostics"].append("bg or TTS not ready")
            decisions[str(i)] = rec
            continue
        rec["kling_duration"] = inputs["kling_duration"]
        rec["final_duration"] = inputs["final_duration"]
        rec["cache_key"] = inputs["cache_key"]
        if cache_enabled and not scene.get("kling_force_fresh"):
            try:
                identity = scene.get("identity") or {}
                candidates = kling_cache.lookup_all_candidates(
                    inputs["cache_key"], inputs["final_duration"],
                    identity.get("camera_distance"))
                rec["candidates"] = [
                    {
                        "key": c["key"],
                        "fitness": c["fitness"],
                        "warnings": c["warnings"],
                        "meta": {
                            "kling_duration": c["meta"].get("kling_duration"),
                            "original_audio_duration": c["meta"].get("original_audio_duration"),
                            "location_ref": c["meta"].get("location_ref"),
                            "camera_distance": c["meta"].get("camera_distance"),
                            "created_at": c["meta"].get("created_at"),
                            "hit_count": c["meta"].get("hit_count"),
                            "quality": c["meta"].get("quality"),
                        },
                    }
                    for c in candidates
                ]
            except Exception as e:
                rec["diagnostics"].append(f"lookup failed: {e}")
        if not rec["candidates"]:
            # 候補なしは即 fresh 確定 (= ユーザ操作不要)
            rec["decision"] = "fresh"
            rec["decided_at"] = _now_iso()
        decisions[str(i)] = rec
    return decisions


def _now_iso() -> str:
    from datetime import datetime as _dt
    return _dt.now().isoformat(timespec="seconds")


def _clear_kling_downstream(scene_idx: int, temp_dir: str) -> None:
    """Kling を差し替える前に、kling / scene 系を削除する (= BG は保持)。"""
    for fname in [
        f"kling_{scene_idx:03d}.mp4",
        f"scene_{scene_idx:03d}.trim.mp4",
        f"scene_{scene_idx:03d}.extended.mp4",
        f"scene_{scene_idx:03d}.mp4",
    ]:
        p = os.path.join(temp_dir, fname)
        if os.path.exists(p):
            os.remove(p)


def kling_commit_cache(scene_idx: int, scene: dict, screenplay: dict,
                       temp_dir: str, cache_key: str) -> None:
    """Stage 4b: cache の raw mp4 を project に copy し、trim まで完了させる。

    既存の kling_<S>.mp4 / scene_<S>.trim.mp4 / scene_<S>.extended.mp4 /
    scene_<S>.mp4 を削除してから commit。trim/slow_mo はその場で同期実行。
    """
    _clear_kling_downstream(scene_idx, temp_dir)

    kling_raw_path = os.path.join(temp_dir, f"kling_{scene_idx:03d}.mp4")
    kling_cache.commit_to_project(cache_key, kling_raw_path)
    scene["_kling_cache_hit"] = True
    scene["_kling_cache_key"] = cache_key

    final_duration = float(scene.get("duration") or 0.0)
    if final_duration <= 0:
        final_duration = _scene_tts_audio_duration(scene_idx, temp_dir)
    _trim_and_finalize_kling(
        scene_idx, scene, kling_raw_path, final_duration, temp_dir)


def kling_generate_fresh(screenplay: dict, temp_dir: str,
                         scene_indices: list[int]) -> None:
    """Stage 4c: 指定シーンだけ FAL Kling を呼んで生成する。

    既存の kling_<S>.mp4 等は事前にクリーンしておくこと (caller 責務)。
    cache lookup はバイパス (= 既に scan phase で fresh queue と確定したものを実行)。
    """
    for i in scene_indices:
        scene = screenplay["scenes"][i]
        _kling_for_scene(i, scene, screenplay, temp_dir, force_fresh=True)


def generate_kling_for_screenplay(screenplay: dict, temp_dir: str,
                                   scene_decisions: dict | None = None) -> None:
    """Stage 4 統合実行関数 (= CLI / legacy パス用)。

    scene_decisions が渡されたら:
      - decision="cache" のシーンは cache から copy
      - decision="fresh" / "pending" のシーンは FAL で新規生成 (cache lookup あり)
    渡されなければ全シーン自動 (= cache lookup あり、CLI / 旧 UI 互換)。

    1 シーンの失敗で stage 全体を諦めず、最後にまとめて
    :class:`PartialKlingFailure` を raise する。成功シーンの kling/trim
    ファイルは disk に残るので、UI から失敗シーンのみ regen 可能。
    """
    scenes = screenplay.get("scenes") or []
    errors: dict[int, BaseException] = {}
    for i, scene in enumerate(scenes):
        decision = None
        decided_key = None
        if scene_decisions:
            rec = scene_decisions.get(str(i)) or {}
            decision = rec.get("decision")
            decided_key = rec.get("decided_key")
        try:
            if decision == "cache" and decided_key:
                kling_commit_cache(i, scene, screenplay, temp_dir, decided_key)
            else:
                _kling_for_scene(i, scene, screenplay, temp_dir, force_fresh=False)
        except BaseException as e:
            errors[i] = e
            logger.exception("シーン%d Kling生成失敗: %s", i + 1, e)
    if errors:
        failed = list(errors.keys())
        succeeded = len(scenes) - len(failed)
        logger.info(
            "[Kling] %d/%d シーン成功、失敗シーン: %s",
            succeeded, len(scenes), sorted(i + 1 for i in failed),
        )
        raise PartialKlingFailure(
            failed, len(scenes),
            errors={i: repr(e) for i, e in errors.items()},
        )


def regen_kling_scene(scene_idx: int, screenplay: dict, temp_dir: str,
                      force_fresh: bool = True) -> None:
    """単一シーンのKlingのみ再生成。下流のscene動画も無効化。

    force_fresh=True (= 既定): ユーザが「再生成」と言った以上 cache hit したら
        意図と矛盾するので必ず FAL 新規呼び出し。
    force_fresh=False: cache lookup を許可 (= 「キャッシュも使って良い」 opt-in)。
    """
    scene = screenplay["scenes"][scene_idx]
    for fname in [
        f"kling_{scene_idx:03d}.mp4",
        f"scene_{scene_idx:03d}.trim.mp4",
        f"scene_{scene_idx:03d}.extended.mp4",
        f"scene_{scene_idx:03d}.mp4",
    ]:
        p = os.path.join(temp_dir, fname)
        if os.path.exists(p):
            os.remove(p)
    _kling_for_scene(scene_idx, scene, screenplay, temp_dir,
                     force_fresh=force_fresh)


def _scene_video_for_scene(scene_idx: int, scene: dict, screenplay: dict,
                            temp_dir: str) -> str:
    """Stage 5 (one-shot方式): 既に audio_<S>.m4a が生成済み前提。
    trim済みKling + audio をリップシンク or 単純合成して scene_<S>.mp4 を作る。

    trimmed の実尺が scene.duration / TTS audio に届かない場合は
    slow_mo で延長してからリップシンクする (Kling の 5/10s 上限対策)。
    """
    trimmed_path = os.path.join(temp_dir, f"scene_{scene_idx:03d}.trim.mp4")
    audio_path = os.path.join(temp_dir, f"audio_{scene_idx:03d}.m4a")
    final_path = os.path.join(temp_dir, f"scene_{scene_idx:03d}.mp4")

    if not os.path.exists(trimmed_path):
        raise FileNotFoundError(f"trim済み動画が見つかりません: {trimmed_path}")

    final_duration = scene.get("duration") or _get_duration(trimmed_path)
    scene["duration"] = final_duration

    if not os.path.exists(audio_path):
        raise FileNotFoundError(
            f"audio_{scene_idx:03d}.m4a が見つかりません。Stage 2 (TTS) 未実行?")

    audio_dur = _get_duration(audio_path)
    target = max(final_duration, audio_dur)
    video_path = _maybe_extend_video(trimmed_path, target, scene_idx, temp_dir)

    lipsync_enabled = (config.LIPSYNC_ENABLED
                       and scene.get("lipsync", True)
                       and bool(scene.get("lines")))

    final_skip_ok = (
        os.path.exists(final_path)
        and artifact_integrity.check_existing(
            final_path, "mp4", label=f"scene {scene_idx + 1} final",
        )
    )
    if not final_skip_ok:
        if lipsync_enabled:
            logger.info("シーン%d リップシンク処理中 (Sync.so)", scene_idx + 1)
            try:
                lipsync_client.apply(video_path, audio_path, final_path)
            except Exception:
                # provider が partial-fail で truncated mp4 を残すと
                # `os.path.exists` + header validation を通過してしまうため、
                # 出力を削除してから再 raise する。
                try:
                    if os.path.exists(final_path):
                        os.remove(final_path)
                except OSError as cleanup_err:
                    logger.warning(
                        "[lipsync-rollback] %s 削除失敗: %s",
                        final_path, cleanup_err,
                    )
                raise
            # 出力の audio stream + duration を検証。lipsync provider が
            # silent stream / truncated mp4 を返したらここで弾く。
            if not _validate_lipsynced_scene(final_path, audio_dur):
                try:
                    os.remove(final_path)
                except OSError as cleanup_err:
                    logger.warning(
                        "[lipsync-rollback] %s 削除失敗: %s",
                        final_path, cleanup_err,
                    )
                raise RuntimeError(
                    f"シーン {scene_idx + 1}: lipsync 出力が検証を通過しませんでした "
                    f"(audio stream 欠落 / duration 不整合の可能性) — "
                    f"再生成してください",
                )
            try:
                cost_recorder.record_lipsync(
                    project_ts=_project_ts(temp_dir),
                    model=config.SYNCSO_LIPSYNC_MODEL,
                    duration_sec=audio_dur,
                    scene_index=scene_idx,
                )
            except Exception:
                logger.exception(
                    "cost recording failed (lipsync, scene=%d)", scene_idx)
        else:
            _replace_audio(video_path, audio_path, final_path)

    return final_path


def _validate_lipsynced_scene(path: str, expected_audio_duration: float) -> bool:
    """lipsync 後の mp4 が:
      - ffprobe で読める正の duration
      - audio stream が 1 本以上
      - duration が expected_audio_duration ±0.5s
    を満たすかを確認する。

    Sync.so が partial-fail で audio 無し or truncated mp4
    を返した時に検出する。誤検知を避けるため tolerance は緩め。
    """
    try:
        r = sp.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, check=False, timeout=15,
        )
    except (sp.TimeoutExpired, OSError):
        return False
    if r.returncode != 0:
        return False
    try:
        data = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return False
    fmt = data.get("format") or {}
    try:
        dur = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        return False
    if dur <= 0:
        return False
    streams = data.get("streams") or []
    has_audio = any((s.get("codec_type") == "audio") for s in streams)
    if not has_audio:
        logger.warning(
            "[lipsync-verify] audio stream が無い: %s (dur=%.2f)", path, dur,
        )
        return False
    if expected_audio_duration > 0 and abs(dur - expected_audio_duration) > 0.5:
        logger.warning(
            "[lipsync-verify] duration mismatch: out=%.2fs, expected≈%.2fs (%s)",
            dur, expected_audio_duration, path,
        )
        return False
    return True


def _maybe_extend_video(trimmed_path: str, target_duration: float,
                        scene_idx: int, temp_dir: str) -> str:
    """trimmed の実尺が target_duration に満たない場合のみ slow_mo して
    scene_<S>.extended.mp4 を作る。十分な尺があれば trimmed_path をそのまま返す。
    """
    cur = _get_duration(trimmed_path)
    # 0.05s 以下の差は誤差として無視 (ffprobe の浮動小数誤差吸収)
    if cur + 0.05 >= target_duration:
        return trimmed_path

    extended_path = os.path.join(temp_dir, f"scene_{scene_idx:03d}.extended.mp4")
    if os.path.exists(extended_path):
        ext_dur = _get_duration(extended_path)
        if abs(ext_dur - target_duration) < 0.1:
            return extended_path
        os.remove(extended_path)

    logger.info(
        "シーン%d slow_mo 延長: %.2fs → %.2fs (ratio=%.2fx)",
        scene_idx + 1, cur, target_duration, target_duration / cur,
    )
    _extend_video_to_duration(trimmed_path, target_duration, extended_path)
    return extended_path


def assemble_scene_videos(screenplay: dict, temp_dir: str) -> list[str]:
    """Stage 5: 各シーンのscene_xxx.mp4を作成する (one-shot生成済みaudioを使用)。"""
    scene_videos: list[str] = []
    for i, scene in enumerate(screenplay["scenes"]):
        path = _scene_video_for_scene(i, scene, screenplay, temp_dir)
        scene_videos.append(path)
    return scene_videos


def regen_scene_video(scene_idx: int, screenplay: dict, temp_dir: str) -> None:
    """単一シーンの最終動画を再生成（trim済みKling + audioを再利用してリップシンクのみ）。"""
    scene = screenplay["scenes"][scene_idx]
    for fname in [
        f"scene_{scene_idx:03d}.mp4",
        f"scene_{scene_idx:03d}.extended.mp4",
    ]:
        p = os.path.join(temp_dir, fname)
        if os.path.exists(p):
            os.remove(p)
    _scene_video_for_scene(scene_idx, scene, screenplay, temp_dir)


def collect_scene_videos(screenplay: dict, temp_dir: str) -> list[str]:
    """既に生成済みの scene_<i>.mp4 を返す。

    存在チェックに加え ffprobe で moov atom + duration を直接検証する。
    `artifact_integrity.check_existing` は AUTO_DELETE off なら破損時も
    True を返す (= 課金済み API 出力を温存) 設計だが、Stage 6 直前では
    truncated mp4 を merge に流すと壊れた最終動画になるので、ここでは
    破損検出 = 即停止 + ユーザに再生成を促す方針を取る。
    """
    paths = []
    for i in range(len(screenplay["scenes"])):
        p = os.path.join(temp_dir, f"scene_{i:03d}.mp4")
        if not os.path.exists(p):
            raise FileNotFoundError(f"シーン動画が見つかりません: {p}")
        if (artifact_integrity.is_enabled()
                and not artifact_integrity.is_valid_mp4(p)):
            raise RuntimeError(
                f"シーン動画が破損しています: {p} — 該当シーンを再生成してください "
                f"(scene 再生成ボタン or `regen scene {i}`)"
            )
        paths.append(p)
    return paths
