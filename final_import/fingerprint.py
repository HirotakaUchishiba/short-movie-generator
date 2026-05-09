"""TTS 音声と CapCut 出力の音声指紋マッチング。

CapCut で編集された動画にも TTS セリフ部分は残っているはずなので、
project の `tts_<S>_<L>.mp3` を reference にして candidate の audio から
見つかるかをスコア化する。BGM / SE が乗っていてもスピーチ MFCC のスライディング
NCC で部分マッチが取れる。
"""

import glob
import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SR = 16000
DEFAULT_N_MFCC = 13
MIN_LINE_DURATION = 0.15  # これ未満の chunk はスコア計算から除外


def compute_match_score(ts_path: str, candidate_video: Path | str) -> float:
    """candidate の audio に project の TTS 音声が含まれている度合いを [0, 1] で返す。

    1.0 = TTS 全ライン完全一致、0.0 = まったく一致しない。
    各 line の duration で重み付けした NCC スコアの平均。
    """
    candidate_video = Path(candidate_video)
    tts_files = sorted(glob.glob(os.path.join(ts_path, "tts_*_*.mp3")))
    if not tts_files:
        logger.warning("TTS files が無いので match score は 0 として扱います: %s", ts_path)
        return 0.0

    import numpy as np
    import librosa

    cand_wav = _extract_audio_to_wav(candidate_video)
    try:
        y_cand, _ = librosa.load(cand_wav, sr=DEFAULT_SR, mono=True)
        if len(y_cand) < DEFAULT_SR * MIN_LINE_DURATION:
            return 0.0
        cand_mfcc = librosa.feature.mfcc(
            y=y_cand, sr=DEFAULT_SR, n_mfcc=DEFAULT_N_MFCC,
        )
    finally:
        try:
            os.unlink(cand_wav)
        except OSError:
            pass

    scores: list[float] = []
    weights: list[float] = []
    for f in tts_files:
        y_ref, _ = librosa.load(f, sr=DEFAULT_SR, mono=True)
        dur = len(y_ref) / DEFAULT_SR
        if dur < MIN_LINE_DURATION:
            continue
        ref_mfcc = librosa.feature.mfcc(
            y=y_ref, sr=DEFAULT_SR, n_mfcc=DEFAULT_N_MFCC,
        )
        s = _best_match_correlation(np.asarray(ref_mfcc), np.asarray(cand_mfcc))
        scores.append(max(0.0, s))
        weights.append(dur)

    if not scores:
        return 0.0
    total = sum(weights)
    if total <= 0:
        return 0.0
    return float(sum(s * w for s, w in zip(scores, weights)) / total)


def _extract_audio_to_wav(video: Path) -> str:
    """ffmpeg で動画から mono 16kHz wav を抽出し、tempfile path を返す。
    呼出側で unlink する責任を持つ。
    """
    fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="ffp_")
    os.close(fd)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(video), "-vn",
        "-ac", "1", "-ar", str(DEFAULT_SR),
        "-c:a", "pcm_s16le", tmp,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return tmp


def _best_match_correlation(ref_mfcc, cand_mfcc) -> float:
    """ref_mfcc を cand_mfcc 上でスライドさせ、最大 NCC を返す。"""
    n_ref = ref_mfcc.shape[1]
    n_cand = cand_mfcc.shape[1]
    if n_ref == 0 or n_cand == 0:
        return 0.0
    if n_ref >= n_cand:
        m = min(n_ref, n_cand)
        return _ncc(ref_mfcc[:, :m], cand_mfcc[:, :m])

    step = max(1, n_ref // 50)
    best = -1.0
    for offset in range(0, n_cand - n_ref + 1, step):
        window = cand_mfcc[:, offset:offset + n_ref]
        c = _ncc(ref_mfcc, window)
        if c > best:
            best = c
    return best


def _ncc(a, b) -> float:
    """正規化相互相関 (a と b は同 shape の MFCC 行列)。"""
    import numpy as np
    af = np.asarray(a, dtype=np.float64).flatten()
    bf = np.asarray(b, dtype=np.float64).flatten()
    if af.size == 0 or bf.size == 0:
        return 0.0
    af = af - af.mean()
    bf = bf - bf.mean()
    denom = float(np.linalg.norm(af) * np.linalg.norm(bf))
    if denom == 0.0:
        return 0.0
    return float(np.dot(af, bf) / denom)
