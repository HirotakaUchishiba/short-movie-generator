"""成果物動画を 0.2s ごとにフレーム抽出 + 下部クロップ + tesseract jpn OCR で
各時刻の字幕テキストを読み、字幕が変わる時刻 (= chunk 表示タイミング) を検出する
(検証用・使い捨て)。OCR は袋文字字幕で誤りが出るため、内容の正確さより
「テキストが切り替わる時刻」を見るのに使う。
"""
import json
import re
import subprocess
from pathlib import Path

VIDEO = "output/reels_20260525_142154.mp4"
WORK = Path("tmp/sub_sync")
FRAMES = WORK / "frames"
FRAMES.mkdir(parents=True, exist_ok=True)

W, H = 1080, 1920
crop_h = int(H * 0.42)          # 下部 42% に字幕領域が収まる
crop_y = H - crop_h

subprocess.run([
    "ffmpeg", "-y", "-i", VIDEO,
    "-vf", f"fps=5,crop={W}:{crop_h}:0:{crop_y}",
    str(FRAMES / "f_%04d.png"),
], check=True, capture_output=True)

frames = sorted(FRAMES.glob("f_*.png"))
print(f"{len(frames)} frames extracted (0.2s step)")


def ocr(path: Path) -> str:
    r = subprocess.run(
        ["tesseract", str(path), "stdout", "-l", "jpn", "--psm", "6"],
        capture_output=True, text=True,
    )
    return re.sub(r"\s+", "", r.stdout)


results = []
for i, f in enumerate(frames):
    t = i * 0.2
    results.append({"t": round(t, 2), "text": ocr(f)})

json.dump(results, open(WORK / "ocr.json", "w"), ensure_ascii=False, indent=2)
print("=== raw subtitle changes (OCR) ===")
prev = None
for r in results:
    if r["text"] != prev:
        print(f"  {r['t']:6.2f}s  {r['text']!r}")
        prev = r["text"]
