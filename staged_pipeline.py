import hashlib
import json
import logging
import os
from datetime import datetime

import config
import progress_store
import scene_gen
from compositor import compose_video, _apply_overlays, _merge_scenes
from post_captions_gen import generate_post_captions
from screenplay_validator import validate_screenplay

logger = logging.getLogger(__name__)


def screenplay_path(name: str) -> str:
    """台本ファイルの絶対パスを返す（拡張子省略可）。"""
    p = os.path.join(config.SCREENPLAYS_DIR, name)
    if os.path.exists(p):
        return p
    if not name.endswith(".json"):
        p2 = os.path.join(config.SCREENPLAYS_DIR, name + ".json")
        if os.path.exists(p2):
            return p2
    raise FileNotFoundError(f"台本が見つかりません: {p}")


def load_screenplay(name: str) -> dict:
    with open(screenplay_path(name)) as f:
        return json.load(f)


def save_screenplay(name: str, screenplay: dict) -> None:
    """台本をscreenplays/<name>.jsonに直接書き戻す。"""
    p = screenplay_path(name) if _exists(name) else os.path.join(
        config.SCREENPLAYS_DIR, name if name.endswith(".json") else f"{name}.json")
    with open(p, "w") as f:
        json.dump(screenplay, f, ensure_ascii=False, indent=2)


def _exists(name: str) -> bool:
    try:
        screenplay_path(name)
        return True
    except FileNotFoundError:
        return False


def write_metadata(temp_dir: str, screenplay_name: str) -> None:
    p = screenplay_path(screenplay_name)
    with open(p, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    meta = {
        "screenplay_name": os.path.basename(p),
        "screenplay_path": os.path.relpath(p, config.BASE_DIR),
        "screenplay_sha256": sha,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    os.makedirs(temp_dir, exist_ok=True)
    with open(os.path.join(temp_dir, "metadata.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def read_metadata(temp_dir: str) -> dict | None:
    p = os.path.join(temp_dir, "metadata.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _ensure_prev_approved(prev_stage: str | None, ts_path: str) -> None:
    if prev_stage and not progress_store.is_approved(ts_path, prev_stage):
        raise RuntimeError(
            f"前ステージ '{prev_stage}' が未承認のため実行できません。"
            "UIで先に承認してください。"
        )


def run_script(screenplay: dict, screenplay_name: str, ts_path: str) -> None:
    """Stage 1: 台本のバリデーション + メタデータ書き出し。"""
    validate_screenplay(screenplay)
    write_metadata(ts_path, screenplay_name)
    progress_store.mark_generated(ts_path, "script")
    logger.info("[Stage 1] 台本検証完了 — %dシーン", len(screenplay["scenes"]))


def run_tts(screenplay: dict, ts_path: str) -> None:
    """Stage 2: TTS生成。"""
    _ensure_prev_approved("script", ts_path)
    scene_gen.generate_tts_for_screenplay(screenplay, ts_path)
    progress_store.mark_generated(ts_path, "tts")
    logger.info("[Stage 2] TTS生成完了")


def run_bg(screenplay: dict, ts_path: str) -> None:
    """Stage 3: 背景画像生成。"""
    _ensure_prev_approved("tts", ts_path)
    bg_paths = scene_gen.generate_backgrounds(screenplay, ts_path)
    progress_store.mark_generated(ts_path, "bg")
    logger.info("[Stage 3] 背景生成完了 — %d枚", len(bg_paths))


def run_kling(screenplay: dict, ts_path: str) -> None:
    """Stage 4: Klingクリップ生成 + trim。"""
    _ensure_prev_approved("bg", ts_path)
    scene_gen.generate_kling_for_screenplay(screenplay, ts_path)
    progress_store.mark_generated(ts_path, "kling")
    logger.info("[Stage 4] Kling生成完了")


def run_scene(screenplay: dict, ts_path: str) -> None:
    """Stage 5+6: 音声合成 + リップシンクで scene_<i>.mp4 を作成。"""
    _ensure_prev_approved("kling", ts_path)
    paths = scene_gen.assemble_scene_videos(screenplay, ts_path)
    progress_store.mark_generated(ts_path, "scene")
    logger.info("[Stage 5+6] シーン動画完成 — %d本", len(paths))


def run_overlay(screenplay: dict, ts_path: str) -> None:
    """Stage 7: シーン連結 + 字幕焼き込み。BGM・音声は次のfinalで。"""
    _ensure_prev_approved("scene", ts_path)
    silent = screenplay.get("audio_mode") == "silent"
    scene_videos = scene_gen.collect_scene_videos(screenplay, ts_path)
    scene_durations = [float(s["duration"]) for s in screenplay["scenes"]]
    merged = _merge_scenes(scene_videos, scene_durations, ts_path, silent)
    overlaid = os.path.join(ts_path, "overlaid.mp4")
    if os.path.exists(overlaid):
        os.remove(overlaid)
    _apply_overlays(merged, screenplay, ts_path, overlaid, silent)
    progress_store.mark_generated(ts_path, "overlay")
    logger.info("[Stage 7] 字幕焼き込み完了")


def run_final(screenplay: dict, screenplay_name: str, ts_path: str) -> str:
    """最終: BGM mix + 出力配置 + キャプション + レポート。"""
    _ensure_prev_approved("overlay", ts_path)
    overlaid = os.path.join(ts_path, "overlaid.mp4")
    if not os.path.exists(overlaid):
        raise FileNotFoundError(f"overlaid.mp4が見つかりません: {overlaid}")

    ts = os.path.basename(ts_path)
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(config.OUTPUT_DIR, f"reels_{ts}.mp4")

    silent = screenplay.get("audio_mode") == "silent"
    bgm_path = screenplay.get("bgm_path")
    use_bgm = bool(bgm_path) and not silent and os.path.exists(bgm_path or "")
    if use_bgm:
        from compositor import _mix_bgm
        bgm_db = float(screenplay.get("bgm_volume_db", config.BGM_DEFAULT_VOLUME_DB))
        _mix_bgm(overlaid, bgm_path, bgm_db, ts_path, output_path)
    else:
        import shutil
        shutil.copyfile(overlaid, output_path)

    caption_path = generate_post_captions(screenplay, screenplay_name, output_path)
    progress_store.mark_generated(ts_path, "final")
    progress_store.mark_approved(ts_path, "final")
    logger.info("[最終] 完成: %s", output_path)
    logger.info("SNS投稿キャプション: %s", caption_path)
    return output_path


STAGE_RUNNERS = {
    "script": run_script,
    "tts": run_tts,
    "bg": run_bg,
    "kling": run_kling,
    "scene": run_scene,
    "overlay": run_overlay,
}


def run_next_stage(screenplay: dict, screenplay_name: str, ts_path: str) -> str | None:
    """次に実行すべきstageを1つだけ実行する。すでに最終まで完了していれば None を返す。"""
    nxt = progress_store.next_stage(ts_path)
    if nxt is None:
        if not progress_store.is_approved(ts_path, "overlay"):
            return None
        run_final(screenplay, screenplay_name, ts_path)
        return "final"

    if nxt == "final":
        run_final(screenplay, screenplay_name, ts_path)
        return "final"

    runner = STAGE_RUNNERS.get(nxt)
    if not runner:
        raise RuntimeError(f"unknown stage: {nxt}")
    if nxt == "script":
        runner(screenplay, screenplay_name, ts_path)
    else:
        runner(screenplay, ts_path)
    return nxt


def regen(stage: str, screenplay: dict, ts_path: str,
          scene_idx: int | None = None, line_idx: int | None = None,
          force: bool = True) -> None:
    """指定stage・scene・lineの単独再生成。承認をリセット。

    force=False (TTSのみ): text_hash不変ならAPIスキップでaudio再構築のみ。
    bg / kling / scene で scene_idx=None の場合は全シーン一括再生成。
    """
    n_scenes = len(screenplay.get("scenes") or [])
    if stage == "tts":
        scene_gen.regen_tts_full(screenplay, ts_path, force=force)
    elif stage == "bg":
        if scene_idx is None:
            for i in range(n_scenes):
                scene_gen.regen_background_scene(i, screenplay, ts_path)
        else:
            scene_gen.regen_background_scene(scene_idx, screenplay, ts_path)
    elif stage == "kling":
        if scene_idx is None:
            for i in range(n_scenes):
                scene_gen.regen_kling_scene(i, screenplay, ts_path)
        else:
            scene_gen.regen_kling_scene(scene_idx, screenplay, ts_path)
    elif stage == "scene":
        if scene_idx is None:
            for i in range(n_scenes):
                scene_gen.regen_scene_video(i, screenplay, ts_path)
        else:
            scene_gen.regen_scene_video(scene_idx, screenplay, ts_path)
    elif stage == "overlay":
        run_overlay(screenplay, ts_path)
    else:
        raise ValueError(f"このstageは個別再生成に対応していません: {stage}")
    progress_store.increment_regen(ts_path, stage)
