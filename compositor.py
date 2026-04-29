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
    """screenplay の scene.duration の累積で offset を計算 (= 想定値ベース)。

    slow_mo 延長や lipsync 後処理で実 scene_<S>.mp4 の尺がここから乖離する
    場合があるため、可能な限り _scene_offsets_from_videos を使うこと。
    """
    offsets = [0.0]
    for scene in scenes[:-1]:
        offsets.append(offsets[-1] + float(scene["duration"]))
    return offsets


def _scene_offsets_from_videos(scene_videos: list[str]) -> list[float]:
    """各 scene_<S>.mp4 の実尺累積で offset を計算 (= 実測値ベース)。

    overlay の base 動画は scene_<S>.mp4 を順に concat したものなので、
    字幕の絶対秒は実尺累積で計算しないと slow_mo 延長分だけズレる。
    """
    offsets = [0.0]
    for v in scene_videos[:-1]:
        offsets.append(offsets[-1] + _get_duration(v))
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


def _line_window(line: dict, next_line: dict | None,
                 scene_duration: float,
                 scene_real_duration: float | None = None) -> tuple[float, float]:
    """シーン内 line の表示開始/終了 (秒) を返す。

    scene_real_duration が指定された場合、line.start / line.end を
    scene_real / scene_sp の比率で線形リスケールする。
    シーン内で slow_mo 延長が一様にかかっている前提で、内部 line タイミングが
    動画 timeline と整合するようにする。
    """
    ratio = 1.0
    if scene_real_duration and scene_duration > 0:
        ratio = scene_real_duration / scene_duration

    start = float(line["start"]) * ratio
    if "end" in line:
        end = float(line["end"]) * ratio
    elif next_line is not None:
        end = float(next_line["start"]) * ratio
    else:
        end = scene_real_duration if scene_real_duration else scene_duration
    return start, end


_BREAK_STRONG = "、。！？!?,."
_BREAK_SPACE = "　 "
_BREAK_DOT = "・"
# 主要助詞 (1文字)
_BREAK_PARTICLES_1CHAR = set("はがをにでとやもへ")
# よく字幕末尾に来る終助詞 (これらの「直前」で切る)
_BREAK_TERMINAL = set("ねよかなさよ")


def _is_katakana(ch: str) -> bool:
    return bool(ch) and ("゠" <= ch <= "ヿ" or ch == "ー")


def _is_kanji(ch: str) -> bool:
    return bool(ch) and "一" <= ch <= "鿿"


def _is_hiragana(ch: str) -> bool:
    return bool(ch) and "぀" <= ch <= "ゟ"


def _break_score_at(text: str, i: int) -> int:
    """位置 i で text を [:i] と [i:] に分けるときのスコア。
    高いほど切るのに自然。"""
    if i <= 0 or i >= len(text):
        return 0
    left = text[i - 1]
    right = text[i]

    # ★★★ 強い改行点
    if left in _BREAK_STRONG:
        return 100
    if left in _BREAK_SPACE:
        return 95
    if left == "」" or left == "』" or left == ")" or left == "）":
        return 92
    if right == "「" or right == "『" or right == "(" or right == "(":
        return 90
    if left in _BREAK_DOT:
        return 85
    # 終助詞の直前
    if right in _BREAK_TERMINAL:
        return 70

    # ★★ 主要助詞の直後
    if left in _BREAK_PARTICLES_1CHAR:
        # 直前が「ま」「て」「し」など (= 動詞活用形末尾) の場合は降格
        # (例: 「ます」「て」が来る活用語尾は助詞ではない)
        # 簡易チェック: 直前 2 文字が活用語尾っぽければ降格
        if i >= 2 and text[i - 2] in "まてしっなき":
            return 30
        return 60

    # ★ カタカナ↔漢字/ひらがな 境界
    lk = _is_katakana(left)
    rk = _is_katakana(right)
    if lk != rk:
        return 35

    # ★ ひらがな↔漢字 境界
    lh = _is_hiragana(left)
    rh = _is_hiragana(right)
    lj = _is_kanji(left)
    rj = _is_kanji(right)
    if (lh and rj) or (lj and rh):
        return 25

    return 0


def _split_into_chunks(text: str, max_chars: int) -> list[str]:
    """日本語テキストを最大 max_chars 文字の chunks に分割する。

    句読点・助詞境界・文字種境界を優先 (= _break_score_at の score 順)。
    自然な break point が見つからない場合は強制位置で切って WARNING ログを出す。
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return [text] if text else []

    chunks: list[str] = []
    rest = text
    while len(rest) > max_chars:
        ideal = max_chars
        # 探索範囲: ideal - (ideal/2 程度) 〜 ideal+1
        # 8 文字制約だと探索幅は ±4 文字
        search_back = max(2, max_chars // 2)
        lo = max(1, ideal - search_back)
        hi = min(len(rest) - 1, ideal)
        best_pos: int | None = None
        best_score = 0
        for i in range(hi, lo - 1, -1):
            s = _break_score_at(rest, i)
            # ideal からの距離ペナルティ (1 文字につき 3 点)
            s -= abs(i - ideal) * 3
            if s > best_score:
                best_score = s
                best_pos = i

        if best_pos is None or best_score <= 0:
            best_pos = ideal
            logger.warning(
                "[subtitle chunks] 自然な break point が見つからず ideal=%d で強制分割: %r",
                ideal, rest[:max_chars * 2],
            )

        chunks.append(rest[:best_pos])
        rest = rest[best_pos:]

    if rest:
        chunks.append(rest)
    return chunks


def _wrap_subtitle_text(text: str, max_chars: int) -> str:
    """日本語字幕を max_chars 以内に折り返す (改行で連結)。
    内部実装は _split_into_chunks を流用 (= chunk を改行でつなぐだけ)。"""
    chunks = _split_into_chunks(text, max_chars)
    return "\n".join(chunks) if chunks else text


def _allocate_chunk_timings(
    chunks: list[str], line_start: float, line_end: float,
) -> list[tuple[float, float]]:
    """chunks に line.start - line.end を文字数比例で配分する。

    短い chunk は短く、長い chunk は長く表示される。
    末尾は浮動小数誤差を避けるため line_end に揃える。
    """
    if not chunks:
        return []
    total_chars = sum(len(c) for c in chunks)
    if total_chars <= 0:
        # フォールバック: 均等分割
        n = len(chunks)
        step = (line_end - line_start) / max(1, n)
        return [(line_start + i * step, line_start + (i + 1) * step)
                for i in range(n)]

    duration = max(0.0, line_end - line_start)
    timings: list[tuple[float, float]] = []
    cursor = line_start
    for c in chunks:
        d = duration * (len(c) / total_chars)
        timings.append((cursor, cursor + d))
        cursor += d
    if timings:
        ls, _ = timings[-1]
        timings[-1] = (ls, line_end)
    return timings


def _needs_overlay(screenplay: dict) -> bool:
    for sc in screenplay.get("scenes", []):
        if sc.get("lines"):
            return True
    return False


def _build_overlay_filter(screenplay: dict, temp_dir: str,
                            scene_videos: list[str] | None = None) -> str:
    """字幕オーバーレイ filter_complex を組み立てる。

    scene_videos が指定されたら **実 timeline ベース** で字幕の絶対時刻を
    計算する (= scene_<S>.mp4 の実尺累積で offset を決め、シーン内の
    line.start / end も scene_real / scene_sp 比でリスケール)。
    指定しない場合は scene.duration ベースで動く (後方互換)。
    """
    font = _escape_fontfile(config.FONT_PATH)
    H = config.VIDEO_HEIGHT
    scenes = screenplay.get("scenes", [])

    use_real_timeline = (
        scene_videos is not None and len(scene_videos) == len(scenes)
    )
    if use_real_timeline:
        offsets = _scene_offsets_from_videos(scene_videos)
        real_durations = [_get_duration(v) for v in scene_videos]
    else:
        offsets = _scene_offsets(scenes)
        real_durations = [None] * len(scenes)

    line_max_chars = int(getattr(config, "SUBTITLE_MAX_CHARS_PER_LINE", 17))
    chunk_enabled = bool(getattr(config, "SUBTITLE_CHUNK_ENABLED", True))
    chunk_max_chars = int(getattr(config, "SUBTITLE_CHUNK_MAX_CHARS", 8))

    filters: list[str] = []
    cur_in = "0:v"
    tag_idx = 0

    def next_tag() -> str:
        nonlocal tag_idx
        tag_idx += 1
        return f"ov{tag_idx}"

    sub_y_from_bottom = int(
        screenplay.get("subtitle_y_from_bottom")
        if screenplay.get("subtitle_y_from_bottom") is not None
        else config.SUBTITLE_Y_FROM_BOTTOM
    )
    sub_y = H - sub_y_from_bottom

    for s_idx, scene in enumerate(scenes):
        offset = offsets[s_idx]
        duration = float(scene["duration"])
        scene_real = real_durations[s_idx]

        scene_lines = scene.get("lines") or []
        for l_idx, line in enumerate(scene_lines):
            next_line = scene_lines[l_idx + 1] if l_idx + 1 < len(scene_lines) else None
            rel_start, rel_end = _line_window(line, next_line, duration, scene_real)
            abs_start = offset + rel_start
            abs_end = offset + rel_end
            text = line["text"].strip()
            if not text:
                continue

            if chunk_enabled:
                # TikTok 風: 短いテロップが次々切替わる
                chunks = _split_into_chunks(text, chunk_max_chars)
                timings = _allocate_chunk_timings(chunks, abs_start, abs_end)
            else:
                # 従来: 1 line = 1 字幕。長文は line 内で改行
                chunks = [_wrap_subtitle_text(text, line_max_chars)]
                timings = [(abs_start, abs_end)]

            for c_idx, (chunk_text, (c_start, c_end)) in enumerate(zip(chunks, timings)):
                tf = _write_textfile(
                    temp_dir,
                    f"sub_{s_idx:03d}_{l_idx:03d}_{c_idx:02d}",
                    chunk_text,
                )
                tf_esc = _escape_fontfile(tf)
                enable_chunk = f"between(t,{c_start:.3f},{c_end:.3f})"
                out = next_tag()
                filters.append(
                    f"[{cur_in}]drawtext=fontfile='{font}':textfile='{tf_esc}':"
                    f"fontsize={config.SUBTITLE_FONT_SIZE}:"
                    f"fontcolor={config.TIME_TEXT_COLOR}:"
                    f"bordercolor={config.TIME_BORDER_COLOR}:"
                    f"borderw={config.FONT_BORDER_WIDTH}:"
                    f"line_spacing={config.SUBTITLE_LINE_GAP}:text_align=C:"
                    f"x=(w-text_w)/2:y={sub_y}:enable='{enable_chunk}'[{out}]"
                )
                cur_in = out

    if not filters:
        return ""

    filters.append(f"[{cur_in}]null[vout]")
    return ";\n".join(filters)


def _apply_overlays(base_video: str, screenplay: dict, temp_dir: str,
                    output_path: str, silent: bool,
                    scene_videos: list[str] | None = None) -> None:
    """base_video に字幕を焼き込む。scene_videos が渡されたら、
    各 scene_<S>.mp4 の実尺ベースで字幕タイミングを計算する。"""
    filter_complex = _build_overlay_filter(
        screenplay, temp_dir, scene_videos=scene_videos)
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
        _apply_overlays(merged_path, screenplay, temp_dir, overlaid_tmp,
                          silent, scene_videos=scene_videos)
        bgm_db = float(screenplay.get("bgm_volume_db", config.BGM_DEFAULT_VOLUME_DB))
        _mix_bgm(overlaid_tmp, bgm_path, bgm_db, temp_dir, output_path)
    else:
        _apply_overlays(merged_path, screenplay, temp_dir, output_path,
                          silent, scene_videos=scene_videos)

    return output_path
