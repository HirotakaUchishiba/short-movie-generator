"""音声からvocal/BGMを分離する。

優先順序:
  1. demucs (htdemucs_ft などstate-of-the-art) — `pip install demucs` 必要
  2. librosa HPSS (低品質フォールバック) — 既存依存のみで動く

両方失敗時はNoneを返す。
"""
import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _ensure_wav(input_path: str, target_path: str) -> str:
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-ac", "2", "-ar", "44100",
        "-vn",
        target_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {r.stderr[-500:]}")
    return target_path


def separate_with_demucs(input_audio: str, out_dir: str,
                         model: str = "htdemucs") -> dict | None:
    """demucsでvocal/BGMを分離。

    Returns:
        {"vocals": "<path>", "no_vocals": "<path>"} or None
    """
    try:
        import demucs.separate  # noqa: F401
    except ImportError:
        logger.info("demucs未インストール → HPSSフォールバックを試行")
        return None

    os.makedirs(out_dir, exist_ok=True)
    cmd = [
        "python3", "-m", "demucs.separate",
        "--two-stems=vocals",
        "-n", model,
        "-o", out_dir,
        input_audio,
    ]
    logger.info("demucs実行中 (model=%s)", model)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        logger.warning("demucs失敗: %s", r.stderr[-500:])
        return None

    stem = Path(input_audio).stem
    base = Path(out_dir) / model / stem
    vocals = base / "vocals.wav"
    no_vocals = base / "no_vocals.wav"
    if not vocals.exists() or not no_vocals.exists():
        logger.warning("demucs出力が見つからない: %s", base)
        return None
    return {"vocals": str(vocals), "no_vocals": str(no_vocals)}


def separate_with_hpss(input_audio: str, out_dir: str) -> dict | None:
    """librosa HPSSで簡易vocal/BGM分離。品質は劣るがdemucsが無い時の保険。
    保存形式は16-bit PCM WAV。
    """
    import numpy as np
    import librosa
    import soundfile as sf

    os.makedirs(out_dir, exist_ok=True)
    try:
        y, sr = librosa.load(input_audio, sr=44100, mono=False)
    except Exception as e:
        logger.warning("librosa load失敗: %s", e)
        return None

    if y.ndim == 1:
        y = np.stack([y, y])

    vocals_channels = []
    bgm_channels = []
    for ch in y:
        y_h, y_p = librosa.effects.hpss(ch, margin=(1.0, 4.0))
        vocals_channels.append(y_h)
        bgm_channels.append(y_p)
    vocals = np.stack(vocals_channels)
    bgm = np.stack(bgm_channels)

    vocals_path = os.path.join(out_dir, "vocals.wav")
    bgm_path = os.path.join(out_dir, "no_vocals.wav")
    sf.write(vocals_path, vocals.T, sr, subtype="PCM_16")
    sf.write(bgm_path, bgm.T, sr, subtype="PCM_16")
    logger.info("HPSS分離完了: %s / %s", vocals_path, bgm_path)
    return {"vocals": vocals_path, "no_vocals": bgm_path}


def separate(input_path: str, out_dir: str | None = None) -> dict | None:
    """vocal/BGMを分離。

    入力は動画/音声どちらでもOK。内部で .wav 変換する。

    Returns:
        {"vocals": "<path>", "no_vocals": "<path>", "method": "demucs"|"hpss"} or None
    """
    out_dir = out_dir or tempfile.mkdtemp(prefix="separate_")
    os.makedirs(out_dir, exist_ok=True)

    wav_path = os.path.join(out_dir, "input.wav")
    _ensure_wav(input_path, wav_path)

    result = separate_with_demucs(wav_path, out_dir)
    if result:
        result["method"] = "demucs"
        return result

    result = separate_with_hpss(wav_path, out_dir)
    if result:
        result["method"] = "hpss"
        return result

    return None
