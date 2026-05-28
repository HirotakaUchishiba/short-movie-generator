"""字幕オーバーレイ済み動画を 0.2s ごとに切り出し、連続フレーム差分で
「末尾の一瞬停止 (= 静止区間)」を検出する (検証用・使い捨て)。
scene 境界 (duration 累積) と照合し、各 scene 末尾の静止長を測る。
"""
import statistics
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

VIDEO = "tmp/sub_sync/overlaid_fixed.mp4"
WORK = Path("tmp/freeze")
FRAMES = WORK / "full"
FRAMES.mkdir(parents=True, exist_ok=True)

subprocess.run(
    ["ffmpeg", "-y", "-i", VIDEO, "-vf", "fps=5,scale=270:480",
     str(FRAMES / "f_%04d.png")],
    check=True, capture_output=True,
)
frames = sorted(FRAMES.glob("f_*.png"))
arrs = [np.asarray(Image.open(f).convert("L"), dtype=np.int16) for f in frames]

# scene 境界 (= scene.duration 累積 = merged の tpad 後位置)
sp_offsets = [0.0, 3.21, 8.72, 14.47, 20.12, 25.39, 30.85, 36.51, 42.18]
# scene 動画の素の実尺累積 (= tpad 前。ここから境界までが tpad 静止のはず)
vid_cum = [0.0, 2.93, 8.15, 13.61, 18.98, 23.98, 29.15, 34.57, 39.98]

diffs = []
for i in range(1, len(arrs)):
    d = float(np.mean(np.abs(arrs[i] - arrs[i - 1])))
    diffs.append((round(i * 0.2, 2), d))

med = statistics.median([d for _, d in diffs])
thr = med * 0.12
print(f"frames={len(arrs)} median_diff={med:.2f} still_threshold={thr:.2f}")
print("=== timeline (S=still, B=scene boundary, V=video-end before tpad) ===")
for t, d in diffs:
    flags = ""
    if d < thr:
        flags += "S"
    if any(abs(t - b) < 0.11 for b in sp_offsets):
        flags += "B"
    if any(abs(t - v) < 0.11 for v in vid_cum):
        flags += "V"
    if flags:
        print(f"  {t:6.2f}s diff={d:7.2f}  {flags}")
