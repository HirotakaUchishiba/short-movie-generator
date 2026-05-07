"""Phase 2: scene 動画 (= リップシンク済み) の口の動きと音声 RMS の相関検査。

口元領域の optical flow magnitude と、同区間の音声 RMS の Pearson 相関を
計算する。相関が低いと「口は動いているが音と合っていない」または
「音が出ているのに口が動いていない」状態を検出する。

opencv-python と librosa が無ければ skip。
"""
from __future__ import annotations

import glob
import logging
import os
import re

from qa.validators.base import (
    ValidationResult,
    failed_result,
    passed_result,
    skipped_result,
)

logger = logging.getLogger(__name__)

SCENE_FILE_RE = re.compile(r"scene_(\d+)\.mp4$")
LIPSYNC_CORR_FAIL = 0.3


def _check_dependencies() -> tuple[bool, str]:
    try:
        import cv2  # noqa: F401
        import librosa  # noqa: F401
        import numpy as np  # noqa: F401
    except (ImportError, ModuleNotFoundError) as e:
        return False, f"missing dependency: {e}"
    return True, "ok"


def _compute_correlation(mp4_path: str) -> tuple[float, dict[str, float]]:
    """scene 動画 1 本の lipsync 相関を計算する。

    高負荷なので、Phase 2 の暫定実装は frame-level optical flow を粗く
    (= 1 fps サンプル + 中央 1/3 領域固定) 取り、音声 RMS の窓と Pearson
    相関を取る。U^2-Net で口元 mask を取ってから FFT で動きを取るのが
    本来の精度だが、Phase 2 ではそこまで追わない。
    """
    import cv2
    import librosa
    import numpy as np

    cap = cv2.VideoCapture(mp4_path)
    if not cap.isOpened():
        raise RuntimeError(f"open failed: {mp4_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    sample_interval_frames = max(int(round(fps)), 1)  # 1 fps サンプル

    flows: list[float] = []
    prev_gray = None
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % sample_interval_frames == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape
            mouth = gray[
                int(h * 0.5):int(h * 0.85),
                int(w * 0.33):int(w * 0.66),
            ]
            if prev_gray is not None and prev_gray.shape == mouth.shape:
                flow = cv2.calcOpticalFlowFarneback(
                    prev_gray, mouth, None,
                    0.5, 3, 15, 3, 5, 1.2, 0,
                )
                magnitude = np.linalg.norm(flow, axis=2).mean()
                flows.append(float(magnitude))
            else:
                flows.append(0.0)
            prev_gray = mouth
        idx += 1
    cap.release()

    if len(flows) < 2:
        raise RuntimeError("too few frames for correlation")

    y, sr = librosa.load(mp4_path, sr=16000, mono=True)
    win = sr  # 1 秒窓
    rms_per_sec: list[float] = []
    for start in range(0, max(len(y) - win, 1), win):
        chunk = y[start:start + win]
        rms_per_sec.append(float(np.sqrt(np.mean(chunk ** 2))))
    if len(rms_per_sec) < 2:
        raise RuntimeError("too short audio for correlation")

    n = min(len(flows), len(rms_per_sec))
    a = np.array(flows[:n], dtype=float)
    b = np.array(rms_per_sec[:n], dtype=float)
    if a.std() == 0 or b.std() == 0:
        return 0.0, {"flow_mean": float(a.mean()), "rms_mean": float(b.mean())}
    corr = float(np.corrcoef(a, b)[0, 1])
    return corr, {
        "flow_mean": float(a.mean()),
        "rms_mean": float(b.mean()),
        "samples": float(n),
    }


def check_lipsync_quality(ts_path: str, **_) -> list[ValidationResult]:
    ok, reason = _check_dependencies()
    out: list[ValidationResult] = []
    scenes = sorted(glob.glob(os.path.join(ts_path, "scene_*.mp4")))
    # scene_<S>.trim.mp4 は除外
    scenes = [p for p in scenes if ".trim." not in os.path.basename(p)]
    if not ok:
        for mp4 in scenes:
            m = SCENE_FILE_RE.search(mp4)
            if m:
                out.append(skipped_result(
                    reason=f"lipsync skipped: {reason}",
                    scene_idx=int(m.group(1)),
                ))
        return out
    for mp4 in scenes:
        m = SCENE_FILE_RE.search(mp4)
        if not m:
            continue
        s_idx = int(m.group(1))
        try:
            corr, metrics = _compute_correlation(mp4)
        except Exception as e:
            out.append(failed_result(
                score=0.0, reason=f"correlation failed: {e}",
                tag="lipsync_timing_off", scene_idx=s_idx,
            ))
            continue
        metrics_dict = dict(metrics)
        metrics_dict["correlation"] = corr
        if corr < LIPSYNC_CORR_FAIL:
            out.append(failed_result(
                score=max(0.0, corr / LIPSYNC_CORR_FAIL),
                reason=f"corr={corr:.3f} < {LIPSYNC_CORR_FAIL}",
                tag="lipsync_timing_off",
                metrics=metrics_dict, scene_idx=s_idx,
            ))
        else:
            out.append(passed_result(
                score=corr, metrics=metrics_dict, scene_idx=s_idx,
            ))
    return out
