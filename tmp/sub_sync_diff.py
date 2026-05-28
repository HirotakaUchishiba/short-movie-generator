"""字幕領域の白文字マスクのフレーム差分で「字幕が切り替わる時刻」を検出する
(検証用・使い捨て)。OCR が袋文字を読めないため、テキスト内容ではなく
白文字 (高輝度) ピクセルの変化タイミングだけを取り出す。
"""
import json
import statistics
from pathlib import Path

import numpy as np
from PIL import Image

WORK = Path("tmp/sub_sync")
FRAMES = sorted((WORK / "frames").glob("f_*.png"))


def text_mask(path: Path) -> np.ndarray:
    a = np.asarray(Image.open(path).convert("L"))
    return (a > 200).astype(np.uint8)   # 白文字 = 高輝度


masks = [text_mask(f) for f in FRAMES]
rows = []
prev = masks[0]
for i, m in enumerate(masks):
    t = round(i * 0.2, 2)
    diff = int(np.sum(m != prev)) if i > 0 else 0
    rows.append({"t": t, "white": int(m.sum()), "diff": diff})
    prev = m

json.dump(rows, open(WORK / "diff.json", "w"))

diffs = [r["diff"] for r in rows[1:]]
med = statistics.median(diffs)
thr = max(2500, med * 3)
print(f"frames={len(rows)} median_diff={med:.0f} threshold={thr:.0f}")
print("=== subtitle change candidates (diff spike) ===")
for r in rows:
    if r["diff"] > thr:
        print(f"  {r['t']:6.2f}s  white={r['white']:6d}  diff={r['diff']:6d}")
