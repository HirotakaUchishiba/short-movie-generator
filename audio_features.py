import logging
import subprocess
import tempfile

logger = logging.getLogger(__name__)


def _ensure_wav(audio_path: str) -> tuple[str, bool]:
    """librosaで扱いやすい16kHz mono WAVへ変換。.wavならそのまま返す。"""
    if audio_path.lower().endswith(".wav"):
        return audio_path, False
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-ac", "1", "-ar", "16000",
        "-vn",
        tmp.name,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {r.stderr[-400:]}")
    return tmp.name, True


def extract_phrase_features(audio_path: str, start: float, end: float) -> dict:
    """指定区間の音響特徴を抽出する。

    Returns:
        {
            "pitch_hz_mean": float,
            "pitch_hz_max": float,
            "pitch_trend": "rising" | "falling" | "flat",
            "rms_peak": float,      # 0.0-1.0
            "rms_mean": float,
            "duration": float,
            "wpm": float | None,    # 呼び出し側で text長から計算
        }
    """
    import numpy as np
    import librosa

    wav_path, is_tmp = _ensure_wav(audio_path)
    try:
        duration = max(0.01, end - start)
        y, sr = librosa.load(wav_path, sr=16000, offset=start, duration=duration, mono=True)

        if len(y) < sr // 20:
            return {
                "pitch_hz_mean": 0.0,
                "pitch_hz_max": 0.0,
                "pitch_trend": "flat",
                "rms_peak": 0.0,
                "rms_mean": 0.0,
                "duration": duration,
            }

        try:
            f0 = librosa.yin(y, fmin=80, fmax=500, sr=sr,
                             frame_length=1024, hop_length=256)
            f0 = f0[~np.isnan(f0)]
        except Exception:
            f0 = np.array([])

        if len(f0) > 0:
            pitch_mean = float(np.mean(f0))
            pitch_max = float(np.max(f0))
            first_half = f0[: len(f0) // 2]
            second_half = f0[len(f0) // 2 :]
            if len(first_half) and len(second_half):
                diff = float(np.mean(second_half) - np.mean(first_half))
                if diff > 15:
                    trend = "rising"
                elif diff < -15:
                    trend = "falling"
                else:
                    trend = "flat"
            else:
                trend = "flat"
        else:
            pitch_mean = 0.0
            pitch_max = 0.0
            trend = "flat"

        rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=256)[0]
        rms_peak = float(np.max(rms)) if len(rms) else 0.0
        rms_mean = float(np.mean(rms)) if len(rms) else 0.0

        return {
            "pitch_hz_mean": round(pitch_mean, 1),
            "pitch_hz_max": round(pitch_max, 1),
            "pitch_trend": trend,
            "rms_peak": round(rms_peak, 3),
            "rms_mean": round(rms_mean, 3),
            "duration": round(duration, 3),
        }
    finally:
        if is_tmp:
            import os
            try:
                os.remove(wav_path)
            except OSError:
                pass


def wpm_from_text(text: str, duration: float) -> float:
    """日本語テキスト長とdurationからWPM相当値を計算。"""
    chars = len([c for c in text if not c.isspace()])
    if duration <= 0:
        return 0.0
    return round(chars / duration * 60.0, 1)


def detect_pauses(audio_path: str, min_pause: float = 0.3,
                  silence_db: float = -40.0) -> list[dict]:
    """音声ファイル内の無音区間（ポーズ）を検出する。

    Returns:
        [{"start": 1.23, "end": 1.78, "duration": 0.55}, ...]
    """
    import numpy as np
    import librosa

    wav_path, is_tmp = _ensure_wav(audio_path)
    try:
        y, sr = librosa.load(wav_path, sr=16000, mono=True)
        if len(y) == 0:
            return []

        intervals = librosa.effects.split(
            y, top_db=abs(silence_db),
            frame_length=2048, hop_length=512,
        )

        pauses: list[dict] = []
        prev_end_sample = 0
        for start_sample, end_sample in intervals:
            gap_start = prev_end_sample / sr
            gap_end = start_sample / sr
            gap_dur = gap_end - gap_start
            if gap_dur >= min_pause:
                pauses.append({
                    "start": round(gap_start, 3),
                    "end": round(gap_end, 3),
                    "duration": round(gap_dur, 3),
                })
            prev_end_sample = end_sample

        total_dur = len(y) / sr
        tail_gap = total_dur - prev_end_sample / sr
        if tail_gap >= min_pause:
            pauses.append({
                "start": round(prev_end_sample / sr, 3),
                "end": round(total_dur, 3),
                "duration": round(tail_gap, 3),
            })

        return pauses
    finally:
        if is_tmp:
            import os
            try:
                os.remove(wav_path)
            except OSError:
                pass


def detect_breath_before(audio_path: str, line_start: float,
                          window: float = 0.4) -> bool:
    """指定lineの開始直前に短い吸気音らしき低エネルギーバーストがあるか判定する。
    厳密な呼吸検出ではなく、間の質を区別するヒューリスティック。
    """
    import numpy as np
    import librosa

    if line_start - window < 0:
        return False

    wav_path, is_tmp = _ensure_wav(audio_path)
    try:
        y, sr = librosa.load(wav_path, sr=16000, mono=True,
                              offset=max(0, line_start - window),
                              duration=window)
        if len(y) < sr // 20:
            return False

        rms = librosa.feature.rms(y=y, frame_length=512, hop_length=128)[0]
        if len(rms) == 0:
            return False
        threshold = float(np.max(rms)) * 0.4
        active = (rms > threshold).sum()
        ratio = active / len(rms)
        return 0.05 < ratio < 0.5
    finally:
        if is_tmp:
            import os
            try:
                os.remove(wav_path)
            except OSError:
                pass


def voice_profile(audio_path: str) -> dict:
    """音声全体からpitch分布を取得して話者プロファイルを推定する。

    Returns:
        {
            "pitch_hz_median": float,
            "pitch_hz_p10": float,
            "pitch_hz_p90": float,
            "estimated_gender": "female" | "male" | "ambiguous",
            "estimated_age_range": "child" | "young_adult" | "adult" | "senior",
        }
    """
    import numpy as np
    import librosa

    wav_path, is_tmp = _ensure_wav(audio_path)
    try:
        y, sr = librosa.load(wav_path, sr=16000, mono=True)
        if len(y) < sr:
            return {
                "pitch_hz_median": 0.0,
                "pitch_hz_p10": 0.0,
                "pitch_hz_p90": 0.0,
                "estimated_gender": "ambiguous",
                "estimated_age_range": "adult",
            }

        f0 = librosa.yin(y, fmin=70, fmax=500, sr=sr,
                         frame_length=2048, hop_length=512)
        f0 = f0[~np.isnan(f0)]
        f0 = f0[(f0 > 70) & (f0 < 500)]
        if len(f0) == 0:
            return {
                "pitch_hz_median": 0.0,
                "pitch_hz_p10": 0.0,
                "pitch_hz_p90": 0.0,
                "estimated_gender": "ambiguous",
                "estimated_age_range": "adult",
            }

        median = float(np.median(f0))
        p10 = float(np.percentile(f0, 10))
        p90 = float(np.percentile(f0, 90))

        if median >= 200:
            gender = "female"
        elif median <= 145:
            gender = "male"
        else:
            gender = "ambiguous"

        if median >= 280:
            age = "young_adult"
        elif median >= 200:
            age = "adult"
        elif median >= 130:
            age = "adult"
        else:
            age = "senior"

        return {
            "pitch_hz_median": round(median, 1),
            "pitch_hz_p10": round(p10, 1),
            "pitch_hz_p90": round(p90, 1),
            "estimated_gender": gender,
            "estimated_age_range": age,
        }
    finally:
        if is_tmp:
            import os
            try:
                os.remove(wav_path)
            except OSError:
                pass


def detect_action_complete(video_path: str,
                            motion_threshold: float | None = None,
                            min_idle_duration: float | None = None) -> float | None:
    """動画のフレーム差分を解析して、動きがほぼゼロになる最初のタイムスタンプを返す。

    末尾に静止区間がある場合 → その先頭（=動作完了点）を返す。
    最後まで動き続けている場合 → None を返す（呼び出し側でクリップ末尾まで使用）。
    """
    import config

    motion_threshold = (motion_threshold if motion_threshold is not None
                        else config.ACTION_IDLE_THRESHOLD)
    min_idle_duration = (min_idle_duration if min_idle_duration is not None
                         else config.ACTION_IDLE_MIN_DURATION)

    try:
        import cv2
    except ImportError:
        logger.warning("cv2未インストール → detect_action_complete スキップ")
        return None

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    motion_per_frame: list[float] = []
    prev = None
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (160, 90))
        if prev is not None:
            diff = float(cv2.absdiff(prev, gray).mean()) / 255.0
            motion_per_frame.append(diff)
        prev = gray
    cap.release()

    if not motion_per_frame:
        return None

    window = max(1, int(min_idle_duration * fps))
    for i in range(len(motion_per_frame) - window + 1):
        if all(m < motion_threshold for m in motion_per_frame[i : i + window]):
            t = i / fps
            return round(t, 3)
    return None


def has_background_music(audio_path: str) -> dict:
    """音声内のBGM存在を簡易判定する。

    librosaのHPSSで harmonic / percussive 成分を分離し、
    無音区間における percussive エネルギーを観察してBGM有無を推定する。
    """
    import numpy as np
    import librosa

    wav_path, is_tmp = _ensure_wav(audio_path)
    try:
        y, sr = librosa.load(wav_path, sr=22050, mono=True)
        if len(y) < sr:
            return {"present": False, "confidence": 0.0}

        y_h, y_p = librosa.effects.hpss(y)

        rms_total = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
        rms_perc = librosa.feature.rms(y=y_p, frame_length=2048, hop_length=512)[0]

        threshold_total = float(np.percentile(rms_total, 30))
        quiet_mask = rms_total < threshold_total * 1.2

        if quiet_mask.sum() == 0:
            return {"present": False, "confidence": 0.0}

        bg_energy = float(np.mean(rms_perc[quiet_mask]))
        speech_energy = float(np.mean(rms_perc[~quiet_mask])) if (~quiet_mask).sum() else 1.0
        ratio = bg_energy / max(speech_energy, 1e-6)

        present = ratio > 0.25 and bg_energy > 0.005
        confidence = min(1.0, max(0.0, (ratio - 0.15) * 2))
        return {
            "present": bool(present),
            "confidence": round(confidence, 3),
            "bg_energy": round(bg_energy, 4),
            "ratio": round(ratio, 3),
        }
    finally:
        if is_tmp:
            import os
            try:
                os.remove(wav_path)
            except OSError:
                pass
