"""scene_gen.py から audio 編集 helper を切り出した module。

extract / concat 系 + silence 検出系 + tempo 補正系を一括で持つ。
scene_gen 側は private shim を残して既存 callsite を破壊しない。

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.1.1
"""

from __future__ import annotations

import os
import subprocess as sp

import config

# extract_audio_segment が duration を下限 clamp する閾値。
# scene_gen 側の MIN_SPEECH_DURATION_SEC と同値で運用する (= 1 箇所に集約)。
MIN_SPEECH_DURATION_SEC = 0.05


def natural_tail_silence_sec() -> float:
    """audio 末尾の自然な余白秒数 (= 全 line 共通、config.TTS_MAX_SILENCE_MS 由来)。

    上限 2.0 秒 / 下限 0.0 秒で clamp する (= TTS_MAX_SILENCE_MS が極端な値で
    上書きされても安全側に倒す)。
    """
    return max(0.0, min(2.0, float(config.TTS_MAX_SILENCE_MS) / 1000.0))


def apply_atempo_inplace(input_path: str, atempo: float) -> None:
    """ffmpeg atempo で速度補正 (in-place)。pitch 維持で時間軸のみ変化。

    atempo が 1.0 ± 0.001 以内なら何もしない (= 浮動小数誤差吸収)。
    """
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


def extract_audio_segment(
    input_path: str, start_sec: float, duration: float,
    output_path: str, codec: str = "aac", bitrate: str = "192k",
) -> None:
    """ffmpeg で input_path から指定区間を切出して output_path に保存。

    -ss を -i の後ろに置く (output seeking) ことで frame-accurate なseekを保証。
    -ss を -i の前に置くと mp3 packet 境界 (~26ms) にスナップして語頭/語尾が削れる。
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-ss", f"{start_sec:.3f}",
        "-t", f"{max(duration, MIN_SPEECH_DURATION_SEC):.3f}",
        "-c:a", codec, "-b:a", bitrate,
        output_path,
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {r.stderr[-500:]}")


def convert_to_aac(input_path: str, output_path: str,
                   bitrate: str = "192k") -> None:
    cmd = ["ffmpeg", "-y", "-i", input_path,
           "-c:a", "aac", "-b:a", bitrate, output_path]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"AAC convert failed: {r.stderr[-500:]}")


def concat_audios_to_aac(audio_paths: list[str], output_path: str) -> None:
    """複数 audio を ffmpeg で連結 → AAC m4a 出力。"""
    if not audio_paths:
        return
    if len(audio_paths) == 1:
        convert_to_aac(audio_paths[0], output_path)
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


def concat_audios_to_mp3(audio_paths: list[str], output_path: str) -> None:
    """複数 audio を ffmpeg で連結 → mp3 出力 (per-line speech body + trailing用)。"""
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


def detect_all_silences(
    audio_path: str, threshold_db: float = -40.0,
    min_silence_sec: float = 0.03,
) -> list[tuple[float, float]]:
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


def snap_line_boundaries_to_silence(
    line_times: list[dict],
    silences: list[tuple[float, float]],
    snap_tolerance_sec: float = 0.2,
    min_speech_sec: float = MIN_SPEECH_DURATION_SEC,
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
        # abs_start の snap 専用。char_ts より「前」で終わる無音だけを候補にする
        # (= 子音オンセット直前から始める)。char_ts より後ろの無音終了に snap
        # すると発声の頭が削れて頭切れになるため、前進方向は候補にしない。
        best: tuple[float, float] | None = None
        best_dist = snap_tolerance_sec + 1.0
        for s_start, s_end in sorted_sils:
            if s_end <= t:
                d = t - s_end
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


def split_global_speed(target: float | None = None) -> tuple[float, float]:
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


def full_screenplay_voice_settings() -> dict:
    """one-shot 生成で使う screenplay-wide voice settings。

    config 既定値 + global speed (= native speed への投影) を 1 dict にまとめる。
    """
    native_speed, _atempo = split_global_speed()
    return {
        "voice_id": config.ELEVENLABS_VOICE_ID,
        "stability": config.ELEVENLABS_VOICE_STABILITY,
        "similarity_boost": config.ELEVENLABS_VOICE_SIMILARITY_BOOST,
        "style": config.ELEVENLABS_VOICE_STYLE,
        "speed": native_speed,
    }


def trim_internal_pauses(input_path: str, output_path: str) -> None:
    """TTS 音声内部の長すぎる無音を圧縮 + 任意で atempo による速度補正。

    silenceremove: 「stop_silence 秒以下の無音は残し、それを超える無音は
    stop_silence に短縮」。
    atempo: 1.0 以外を指定すると速度倍率 (ピッチ維持で時間軸を変える)。
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
        # atempo は 1 段で 0.5〜2.0 まで有効。それ以上なら多段に分ける必要が
        # あるが現状はOK
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


def apply_silenceremove_inplace(
    input_path: str, max_silence_sec: float, threshold_db: float,
) -> None:
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
