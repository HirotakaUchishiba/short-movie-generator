import json
import logging
import os
import subprocess

import config

logger = logging.getLogger(__name__)


def _get_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", path],
        capture_output=True, text=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def _write_textfile(temp_dir: str, name: str, text: str) -> str:
    path = os.path.join(temp_dir, f"drawtext_{name}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _escape_fontfile(path: str) -> str:
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _scene_offsets(scenes: list[dict]) -> list[float]:
    offsets = [0.0]
    for scene in scenes[:-1]:
        offsets.append(offsets[-1] + float(scene["duration"]))
    return offsets


def _merge_scenes(scene_videos: list[str], scene_durations: list[float],
                  temp_dir: str, silent: bool) -> str:
    n = len(scene_videos)
    if n == 1:
        return scene_videos[0]

    filter_parts = []
    for i in range(n):
        target_dur = scene_durations[i]
        vid_dur = _get_duration(scene_videos[i])
        pad = ""
        if target_dur > vid_dur + 0.05:
            pad = f",tpad=stop=-1:stop_mode=clone:stop_duration={target_dur - vid_dur:.3f}"
        filter_parts.append(
            f"[{i}:v]scale={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT},"
            f"setsar=1,fps={config.FPS}{pad}[v{i}]"
        )

    if silent:
        concat_inputs = "".join(f"[v{i}]" for i in range(n))
        filter_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=0[merged]")
        maps = ["-map", "[merged]"]
    else:
        concat_inputs = "".join(f"[v{i}][{i}:a]" for i in range(n))
        filter_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[mv][ma]")
        maps = ["-map", "[mv]", "-map", "[ma]"]

    filter_complex = ";\n".join(filter_parts)
    merged_path = os.path.join(temp_dir, "merged.mp4")

    cmd = ["ffmpeg", "-y"]
    for v in scene_videos:
        cmd.extend(["-i", v])
    cmd.extend([
        "-filter_complex", filter_complex,
        *maps,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
    ])
    if not silent:
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])
    cmd.append(merged_path)

    logger.info("シーン結合中")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        logger.error("Merge error: %s", r.stderr[-1500:])
        raise RuntimeError("Scene merge failed")
    return merged_path


def _line_window(line: dict, next_line: dict | None, scene_duration: float) -> tuple[float, float]:
    start = float(line["start"])
    if "end" in line:
        end = float(line["end"])
    elif next_line is not None:
        end = float(next_line["start"])
    else:
        end = scene_duration
    return start, end


def _needs_overlay(screenplay: dict) -> bool:
    for sc in screenplay.get("scenes", []):
        if sc.get("lines"):
            return True
    return False


def _build_overlay_filter(screenplay: dict, temp_dir: str) -> str:
    font = _escape_fontfile(config.FONT_PATH)
    H = config.VIDEO_HEIGHT
    scenes = screenplay.get("scenes", [])
    offsets = _scene_offsets(scenes)

    filters: list[str] = []
    cur_in = "0:v"
    tag_idx = 0

    def next_tag() -> str:
        nonlocal tag_idx
        tag_idx += 1
        return f"ov{tag_idx}"

    for s_idx, scene in enumerate(scenes):
        offset = offsets[s_idx]
        duration = float(scene["duration"])

        scene_lines = scene.get("lines") or []
        for l_idx, line in enumerate(scene_lines):
            next_line = scene_lines[l_idx + 1] if l_idx + 1 < len(scene_lines) else None
            rel_start, rel_end = _line_window(line, next_line, duration)
            abs_start = offset + rel_start
            abs_end = offset + rel_end
            enable_line = f"between(t,{abs_start:.3f},{abs_end:.3f})"

            text = line["text"].strip()
            tf = _write_textfile(temp_dir, f"sub_{s_idx:03d}_{l_idx:03d}", text)
            tf_esc = _escape_fontfile(tf)
            # screenplay 側に override があればそちらを優先 (UI で調整可能)
            sub_y_from_bottom = int(
                screenplay.get("subtitle_y_from_bottom")
                if screenplay.get("subtitle_y_from_bottom") is not None
                else config.SUBTITLE_Y_FROM_BOTTOM
            )
            sub_y = H - sub_y_from_bottom
            out = next_tag()
            filters.append(
                f"[{cur_in}]drawtext=fontfile='{font}':textfile='{tf_esc}':"
                f"fontsize={config.SUBTITLE_FONT_SIZE}:"
                f"fontcolor={config.TIME_TEXT_COLOR}:"
                f"bordercolor={config.TIME_BORDER_COLOR}:"
                f"borderw={config.FONT_BORDER_WIDTH}:"
                f"line_spacing={config.SUBTITLE_LINE_GAP}:text_align=C:"
                f"x=(w-text_w)/2:y={sub_y}:enable='{enable_line}'[{out}]"
            )
            cur_in = out

    if not filters:
        return ""

    filters.append(f"[{cur_in}]null[vout]")
    return ";\n".join(filters)


def _apply_overlays(base_video: str, screenplay: dict, temp_dir: str,
                    output_path: str, silent: bool) -> None:
    filter_complex = _build_overlay_filter(screenplay, temp_dir)
    if not filter_complex:
        import shutil
        shutil.copyfile(base_video, output_path)
        return

    cmd = ["ffmpeg", "-y", "-i", base_video,
           "-filter_complex", filter_complex,
           "-map", "[vout]"]
    if not silent:
        cmd.extend(["-map", "0:a?"])
    cmd.extend([
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
    ])
    if not silent:
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])
    else:
        cmd.append("-an")
    cmd.append(output_path)

    logger.info("テロップ焼き込み中")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        logger.error("Overlay error: %s", r.stderr[-1500:])
        raise RuntimeError("Overlay application failed")


def _mix_bgm(video_path: str, bgm_path: str, bgm_db: float,
             temp_dir: str, output_path: str) -> None:
    """既存video(voice音声込み)に BGM を低音量で重ねる。"""
    total_dur = _get_duration(video_path)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-stream_loop", "-1", "-i", bgm_path,
        "-filter_complex",
        f"[1:a]volume={bgm_db:+.1f}dB,atrim=0:{total_dur:.3f},asetpts=N/SR/TB[bgm];"
        f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path,
    ]
    logger.info("BGM mix中 (volume=%+0.1fdB)", bgm_db)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        logger.error("BGM mix error: %s", r.stderr[-1500:])
        raise RuntimeError("BGM mix failed")


def compose_video(
    scene_videos: list[str],
    screenplay: dict,
    temp_dir: str,
    output_path: str,
) -> str:
    silent = screenplay.get("audio_mode") == "silent"
    scenes = screenplay["scenes"]
    scene_durations = [float(s["duration"]) for s in scenes]

    merged_path = _merge_scenes(scene_videos, scene_durations, temp_dir, silent)

    bgm_path = screenplay.get("bgm_path")
    use_bgm = bool(bgm_path) and not silent and os.path.exists(bgm_path or "")

    if use_bgm:
        overlaid_tmp = os.path.join(temp_dir, "overlaid.mp4")
        _apply_overlays(merged_path, screenplay, temp_dir, overlaid_tmp, silent)
        bgm_db = float(screenplay.get("bgm_volume_db", config.BGM_DEFAULT_VOLUME_DB))
        _mix_bgm(overlaid_tmp, bgm_path, bgm_db, temp_dir, output_path)
    else:
        _apply_overlays(merged_path, screenplay, temp_dir, output_path, silent)

    return output_path
