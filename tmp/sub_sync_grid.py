"""各 scene の発話開始時刻 (Whisper) の字幕帯フレームを縦に並べ、
発話開始時点で字幕が何を表示しているかを一望する (検証用・使い捨て)。
"""
from pathlib import Path

from PIL import Image, ImageDraw

BAND = Path("tmp/sub_sync/band")
scenes = [
    ("s0", 0.0), ("s1", 2.86), ("s2", 8.44), ("s3", 14.26),
    ("s4", 19.94), ("s5", 25.20), ("s6", 30.58), ("s7", 36.20),
    ("s8a", 42.0), ("s8b", 44.26),
]
imgs = []
for label, t in scenes:
    idx = round(t / 0.2) + 1
    img = Image.open(BAND / f"b_{idx:04d}.png").convert("RGB")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 360, 28], fill=(0, 0, 0))
    d.text((6, 8), f"{label} speech_onset={t}s", fill=(255, 80, 80))
    imgs.append(img)

W = imgs[0].width
H = sum(i.height for i in imgs)
combined = Image.new("RGB", (W, H), (40, 40, 40))
y = 0
for i in imgs:
    combined.paste(i, (0, y))
    y += i.height
combined.save("tmp/sub_sync/scene_onset_grid.png")
print(f"saved {W}x{H}")
