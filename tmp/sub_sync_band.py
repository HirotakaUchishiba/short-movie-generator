"""字幕帯 (画面中央 y=900-1080) だけをクロップし、白文字ピクセルの時系列と
on/off 遷移・差分スパイクを取る (検証用・使い捨て)。下部42%でなく字幕の実位置に
絞ることで背景ノイズを減らす。
"""
import json
import statistics
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

VIDEO = "output/reels_20260525_142154.mp4"
WORK = Path("tmp/sub_sync")
BAND = WORK / "band"
BAND.mkdir(parents=True, exist_ok=True)

subprocess.run(
    ["ffmpeg", "-y", "-i", VIDEO, "-vf", "fps=5,crop=1080:180:0:900",
     str(BAND / "b_%04d.png")],
    check=True, capture_output=True,
)
frames = sorted(BAND.glob("b_*.png"))


def mask(p: Path) -> np.ndarray:
    a = np.asarray(Image.open(p).convert("L"))
    return (a > 210).astype(np.uint8)


masks = [mask(f) for f in frames]
rows = []
prev = masks[0]
for i, m in enumerate(masks):
    t = round(i * 0.2, 2)
    diff = int(np.sum(m != prev)) if i > 0 else 0
    rows.append({"t": t, "white": int(m.sum()), "diff": diff})
    prev = m
json.dump(rows, open(WORK / "band_diff.json", "w"))

med = statistics.median([r["diff"] for r in rows[1:]])
print(f"frames={len(rows)} median_diff={med:.0f}")
print("=== white-pixel timeline (band, # = 1500px) ===")
for r in rows:
    print(f"  {r['t']:6.2f}s w={r['white']:6d} d={r['diff']:6d} {'#' * (r['white'] // 1500)}")
