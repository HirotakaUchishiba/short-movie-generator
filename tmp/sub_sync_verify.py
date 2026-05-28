"""修正後 overlaid_fixed.mp4 を字幕帯クロップし、各 scene 発話開始時刻の字幕を
縦に並べて drift 解消を確認する (検証用・使い捨て)。前回 grid と同じ時刻で比較。
"""
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

VIDEO = "tmp/sub_sync/overlaid_fixed.mp4"
WORK = Path("tmp/sub_sync")
BAND2 = WORK / "band_fixed"
BAND2.mkdir(parents=True, exist_ok=True)

subprocess.run(
    ["ffmpeg", "-y", "-i", VIDEO, "-vf", "fps=5,crop=1080:180:0:900",
     str(BAND2 / "b_%04d.png")],
    check=True, capture_output=True,
)

# 発話開始 +0.6s のフレーム (字幕は発話直後に出るはずなので、ここで該当 scene の
# 字幕が表示されていれば同期、前 scene のものや空白なら遅れ/先行)
scenes = [
    ("s0", 0.6), ("s1", 3.5), ("s2", 9.0), ("s3", 14.9),
    ("s4", 20.5), ("s5", 25.8), ("s6", 31.2), ("s7", 36.8),
    ("s8a", 42.6), ("s8b", 44.9),
]
imgs = []
for label, t in scenes:
    idx = round(t / 0.2) + 1
    img = Image.open(BAND2 / f"b_{idx:04d}.png").convert("RGB")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 360, 28], fill=(0, 0, 0))
    d.text((6, 8), f"{label} speech_onset={t}s", fill=(80, 255, 80))
    imgs.append(img)

W = imgs[0].width
H = sum(i.height for i in imgs)
combined = Image.new("RGB", (W, H), (40, 40, 40))
y = 0
for i in imgs:
    combined.paste(i, (0, y))
    y += i.height
combined.save("tmp/sub_sync/scene_onset_grid_fixed.png")
print(f"saved {W}x{H}")
