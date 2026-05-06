import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("librosa")
pytest.importorskip("numpy")


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


pytestmark = pytest.mark.skipif(
    not _ffmpeg_available(), reason="ffmpeg/ffprobe required",
)


def _make_speech_like_mp3(path: Path, freq: float, duration: float) -> None:
    """TTS 音声を模した sin 波 mp3 (周波数を変えれば line ごとに別の特徴を持つ)。"""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi",
        "-i", f"sine=frequency={freq}:duration={duration}:sample_rate=16000",
        "-c:a", "libmp3lame", "-b:a", "32k", str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _make_video_from_audio(audio_files: list[Path], dst: Path,
                          extra_silence: float = 0.0) -> None:
    """audio_files を順に連結 (+ silence padding) して 黒画面の mp4 にする (= CapCut 出力 simulation)。"""
    concat_list = dst.parent / "list.txt"
    parts = []
    if extra_silence > 0:
        sil = dst.parent / "sil.wav"
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi",
            "-i", f"anullsrc=cl=mono:r=16000:d={extra_silence}",
            "-c:a", "pcm_s16le", str(sil),
        ], check=True, capture_output=True)
        parts.append(sil)
    parts.extend(audio_files)
    if extra_silence > 0:
        parts.append(parts[0].parent / "sil.wav")

    concat_list.write_text("\n".join(f"file '{p.resolve()}'" for p in parts))

    audio_concat = dst.parent / "concat.wav"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", str(audio_concat),
    ], check=True, capture_output=True)

    duration_proc = subprocess.run([
        "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(audio_concat),
    ], check=True, capture_output=True, text=True)
    total = float(duration_proc.stdout.strip())

    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=black:s=64x64:d={total}",
        "-i", str(audio_concat),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(dst),
    ], check=True, capture_output=True)


def test_fingerprint_matches_when_tts_present(tmp_path):
    from final_import.fingerprint import compute_match_score

    ts_path = tmp_path / "ts"
    ts_path.mkdir()
    tts1 = ts_path / "tts_0_0.mp3"
    tts2 = ts_path / "tts_0_1.mp3"
    _make_speech_like_mp3(tts1, freq=440, duration=1.0)
    _make_speech_like_mp3(tts2, freq=660, duration=1.0)

    video = tmp_path / "capcut.mp4"
    _make_video_from_audio([tts1, tts2], video, extra_silence=0.5)

    score = compute_match_score(str(ts_path), video)
    assert score > 0.7, f"matching audio should score high, got {score}"


def test_fingerprint_low_when_audio_unrelated(tmp_path):
    from final_import.fingerprint import compute_match_score

    ts_path = tmp_path / "ts"
    ts_path.mkdir()
    tts1 = ts_path / "tts_0_0.mp3"
    _make_speech_like_mp3(tts1, freq=440, duration=1.0)

    video = tmp_path / "unrelated.mp4"
    different = tmp_path / "noise.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi",
        "-i", "anoisesrc=color=white:duration=2:sample_rate=16000:amplitude=0.2",
        "-c:a", "libmp3lame", "-b:a", "32k", str(different),
    ], check=True, capture_output=True)
    _make_video_from_audio([different], video)

    score = compute_match_score(str(ts_path), video)
    assert score < 0.5, f"unrelated audio should score low, got {score}"


def test_fingerprint_returns_zero_when_no_tts(tmp_path):
    from final_import.fingerprint import compute_match_score

    ts_path = tmp_path / "ts"
    ts_path.mkdir()

    video = tmp_path / "any.mp4"
    audio = tmp_path / "a.mp3"
    _make_speech_like_mp3(audio, freq=440, duration=1.0)
    _make_video_from_audio([audio], video)

    assert compute_match_score(str(ts_path), video) == 0.0
