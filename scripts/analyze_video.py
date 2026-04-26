#!/usr/bin/env python3
"""参考動画をClaude Opus 4.7で分析し、screenplays/auto_<name>.json を生成する。

使い方:
    python3 scripts/analyze_video.py path/to/reference.mov
    python3 scripts/analyze_video.py path/to/reference.mov --output my_output.json
    python3 scripts/analyze_video.py path/to/reference.mov --fps 2.0
    python3 scripts/analyze_video.py path/to/reference.mov --no-bgm-extract
"""
import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import log_setup  # noqa: E402
import audio_separator  # noqa: E402
import furigana_store  # noqa: E402
import shot_detector  # noqa: E402
from audio_features import (  # noqa: E402
    extract_phrase_features,
    wpm_from_text,
    detect_pauses,
    detect_breath_before,
    voice_profile,
    has_background_music,
)
from video_analyzer import build_screenplay  # noqa: E402
from whisper_client import transcribe  # noqa: E402
from screenplay_validator import validate_screenplay  # noqa: E402

log_setup.setup()
logger = logging.getLogger(__name__)

DEFAULT_FPS = 2.0  # 0.5秒刻み


def _extract_frames(video_path: str, fps: float, out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    pattern = os.path.join(out_dir, "frame_%04d.jpg")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps={fps},scale=882:-1",
        "-q:v", "3",
        pattern,
    ]
    logger.info("フレーム抽出中 (fps=%.2f)", fps)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed: {r.stderr[-500:]}")
    frames = sorted(
        os.path.join(out_dir, f)
        for f in os.listdir(out_dir)
        if f.startswith("frame_") and f.endswith(".jpg")
    )
    logger.info("フレーム抽出完了: %d枚", len(frames))
    return frames


def _extract_audio(video_path: str, out_path: str) -> str:
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-ac", "1", "-ar", "16000",
        "-vn",
        out_path,
    ]
    logger.info("音声抽出中")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: {r.stderr[-500:]}")
    return out_path


def _has_audio_stream(video_path: str) -> bool:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a",
           "-show_entries", "stream=codec_type", "-of", "csv=p=0", video_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return "audio" in (r.stdout or "")


def _default_output(video_path: str) -> str:
    stem = Path(video_path).stem
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in stem)
    return str(Path(config.SCREENPLAYS_DIR) / f"auto_{safe}.json")


def _bgm_keep_path(video_path: str) -> str:
    """BGMを永続保存するパス（screenplaysと並べてアセット保管）。"""
    stem = Path(video_path).stem
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in stem)
    bgm_dir = Path(config.BASE_DIR) / "assets" / "bgm"
    bgm_dir.mkdir(parents=True, exist_ok=True)
    return str(bgm_dir / f"{safe}_bgm.wav")


def main() -> int:
    parser = argparse.ArgumentParser(description="参考動画を分析して台本JSONを生成")
    parser.add_argument("video_path", help="分析する動画ファイル")
    parser.add_argument("--output", help="出力先JSONパス (既定: screenplays/auto_<名前>.json)")
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS,
                        help=f"フレーム抽出レート [既定 {DEFAULT_FPS} = 0.5秒刻み]")
    parser.add_argument("--keep-tmp", action="store_true",
                        help="一時フレーム・音声を削除しない (デバッグ用)")
    parser.add_argument("--instructions", help="Claudeに渡す追加指示（例 'TikTok UIは無視'）")
    parser.add_argument("--no-bgm-extract", action="store_true",
                        help="BGM分離をスキップ（高速化）")
    parser.add_argument("--no-shots", action="store_true",
                        help="ショット境界検出をスキップ")
    args = parser.parse_args()

    video_path = os.path.abspath(args.video_path)
    if not os.path.exists(video_path):
        logger.error("動画が見つかりません: %s", video_path)
        return 1

    output_path = args.output or _default_output(video_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    tmp_dir = tempfile.mkdtemp(prefix="analyze_")
    logger.info("作業ディレクトリ: %s", tmp_dir)

    bgm_kept_path: str | None = None
    try:
        frames_dir = os.path.join(tmp_dir, "frames")
        audio_path = os.path.join(tmp_dir, "audio.wav")

        frame_interval_sec = 1.0 / args.fps
        frame_paths = _extract_frames(video_path, args.fps, frames_dir)

        transcript: dict = {"text": "", "segments": [], "words": [], "duration": 0.0}
        phrase_features: list[dict] = []
        pauses: list[dict] = []
        vp_info: dict | None = None
        bgm_info: dict | None = None

        has_audio = _has_audio_stream(video_path)
        if has_audio:
            _extract_audio(video_path, audio_path)
            transcript = transcribe(audio_path, language=config.LANGUAGE)
            logger.info("transcript: %d segments, %d words, %.1fs",
                        len(transcript["segments"]), len(transcript["words"]),
                        transcript["duration"])

            for seg in transcript["segments"]:
                feat = extract_phrase_features(audio_path, seg["start"], seg["end"])
                feat["wpm"] = wpm_from_text(seg["text"], seg["end"] - seg["start"])
                feat["breath_before"] = detect_breath_before(audio_path, seg["start"])
                phrase_features.append(feat)

            pauses = detect_pauses(audio_path, min_pause=0.3)
            logger.info("無音区間: %d", len(pauses))

            vp_info = voice_profile(audio_path)
            logger.info("voice_profile: pitch_med=%.0fHz gender=%s age=%s",
                        vp_info.get("pitch_hz_median", 0),
                        vp_info.get("estimated_gender"),
                        vp_info.get("estimated_age_range"))

            bgm_info = has_background_music(audio_path)
            logger.info("BGM存在判定: present=%s confidence=%.2f",
                        bgm_info.get("present"), bgm_info.get("confidence", 0))
        else:
            logger.warning("動画に音声ストリームがありません。silent modeで分析します")

        shot_boundaries: list[dict] = []
        if not args.no_shots:
            shot_boundaries = shot_detector.detect_shots(video_path)
            logger.info("ショット境界: %d", len(shot_boundaries))

        if has_audio and bgm_info and bgm_info.get("present") and not args.no_bgm_extract:
            sep_dir = os.path.join(tmp_dir, "separated")
            sep = audio_separator.separate(audio_path, sep_dir)
            if sep:
                bgm_kept_path = _bgm_keep_path(video_path)
                shutil.copyfile(sep["no_vocals"], bgm_kept_path)
                logger.info("BGM分離完了 method=%s → %s", sep["method"], bgm_kept_path)
            else:
                logger.info("BGM分離スキップ（demucs/HPSS両方失敗）")

        known_furigana = furigana_store.load()
        logger.info("既知furigana辞書: %d件", len(known_furigana))

        screenplay = build_screenplay(
            frame_paths=frame_paths,
            transcript=transcript,
            phrase_features=phrase_features,
            source_video_path=video_path,
            extra_instructions=args.instructions,
            frame_interval_sec=frame_interval_sec,
            shot_boundaries=shot_boundaries,
            pauses=pauses,
            voice_profile_info=vp_info,
            bgm_info=bgm_info,
            known_furigana=known_furigana,
        )

        new_hints = furigana_store.collect_from_screenplay(screenplay)
        if new_hints:
            furigana_store.merge(new_hints)

        if vp_info:
            screenplay.setdefault("_analysis", {})["voice_profile"] = vp_info
        if bgm_kept_path:
            screenplay["bgm_path"] = bgm_kept_path
            screenplay.setdefault("bgm_volume_db", -18)

        errors = validate_screenplay(screenplay, strict=False)
        if errors:
            logger.warning("バリデーション警告:")
            for e in errors:
                logger.warning("  - %s", e)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(screenplay, f, ensure_ascii=False, indent=2)
        logger.info("台本保存: %s", output_path)
        logger.info("  scenes=%d, lines=%d, duration=%.1fs",
                    len(screenplay.get("scenes", [])),
                    sum(len(s.get("lines") or []) for s in screenplay.get("scenes", [])),
                    sum(s.get("duration", 0) for s in screenplay.get("scenes", [])))

        ana = screenplay.get("_analysis", {})
        if ana.get("input_tokens"):
            cost_usd = (ana["input_tokens"] * 15.0 / 1_000_000
                        + ana.get("output_tokens", 0) * 75.0 / 1_000_000)
            logger.info("Claude消費: input=%d output=%d ≈ $%.3f",
                        ana["input_tokens"], ana.get("output_tokens", 0), cost_usd)

        return 0
    finally:
        if not args.keep_tmp:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
