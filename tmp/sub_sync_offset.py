"""scene 動画の実尺累積 (= 字幕の scene offset) と Whisper の発話 scene 開始を
比較し、ドリフト (字幕の絶対位置 - 実発話位置) を出す (検証用・使い捨て)。
drift>0 = 字幕が遅れ、drift<0 = 字幕が先行。
"""
import subprocess
from pathlib import Path

TMP = Path("temp/20260525_142154")


def dur(f: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(f)],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip())


# Whisper による各 scene 発話開始 (秒)
speech = [0.00, 2.86, 8.44, 14.26, 19.94, 25.20, 30.58, 36.20, 42.00]

cum = 0.0
print(f"{'scene':<6}{'vid_dur':>9}{'cum_off':>9}{'speech':>9}{'drift':>9}")
for i in range(9):
    d = dur(TMP / f"scene_{i:03d}.mp4")
    print(f"{i:<6}{d:9.2f}{cum:9.2f}{speech[i]:9.2f}{cum - speech[i]:+9.2f}")
    cum += d
print(f"total scene-video sum = {cum:.2f}  (reels duration = 47.52)")
