"""tail buffer 0 (tpad なし) で再生成した overlaid_nofreeze.mp4 の静止区間を
検出し、フリーズが消えたか検証する (検証用・使い捨て)。
"""
import statistics
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

VIDEO = "tmp/freeze/overlaid_nofreeze.mp4"
WORK = Path("tmp/freeze")
FRAMES = WORK / "full_nf"
FRAMES.mkdir(parents=True, exist_ok=True)
subprocess.run(
    ["ffmpeg", "-y", "-i", VIDEO, "-vf", "fps=5,scale=270:480",
     str(FRAMES / "f_%04d.png")],
    check=True, capture_output=True,
)
frames = sorted(FRAMES.glob("f_*.png"))
arrs = [np.asarray(Image.open(f).convert("L"), dtype=np.int16) for f in frames]

# tpad 除去後の scene 境界 = scene 動画実尺累積
sp_offsets = [0.0, 2.93, 8.15, 13.61, 18.99, 23.99, 29.16, 34.58, 40.0]
diffs = []
for i in range(1, len(arrs)):
    d = float(np.mean(np.abs(arrs[i] - arrs[i - 1])))
    diffs.append((round(i * 0.2, 2), d))
med = statistics.median([d for _, d in diffs])
thr = med * 0.12
print(f"frames={len(arrs)} median={med:.2f} still_thr={thr:.2f}")
print("=== still(S) / scene boundary(B) ===")
for t, d in diffs:
    flags = ""
    if d < thr:
        flags += "S"
    if any(abs(t - b) < 0.11 for b in sp_offsets):
        flags += "B"
    if flags:
        print(f"  {t:6.2f}s diff={d:7.2f}  {flags}")
