"""成果物動画の音声を faster-whisper で word-level transcribe する (検証用・使い捨て)。

字幕タイミング検証の「発話の真実」側を作る。出力 tmp/sub_sync/words.json は
[{start, end, word}, ...] の絶対時刻 (秒)。
"""
import json
import subprocess
from pathlib import Path

from faster_whisper import WhisperModel

VIDEO = "output/reels_20260525_142154.mp4"
WORK = Path("tmp/sub_sync")
WORK.mkdir(parents=True, exist_ok=True)

audio = WORK / "audio.wav"
subprocess.run(
    ["ffmpeg", "-y", "-i", VIDEO, "-vn", "-ar", "16000", "-ac", "1", str(audio)],
    check=True, capture_output=True,
)

# 日本語は large-v3 が最も精度が高い。int8 で CPU でも実用速度。
model = WhisperModel("large-v3", device="cpu", compute_type="int8")
segments, info = model.transcribe(
    str(audio), language="ja", word_timestamps=True,
)

words = []
for seg in segments:
    for w in (seg.words or []):
        words.append({
            "start": round(w.start, 3),
            "end": round(w.end, 3),
            "word": w.word,
        })

json.dump(words, open(WORK / "words.json", "w"), ensure_ascii=False, indent=2)
full = "".join(w["word"] for w in words)
print(f"Whisper done: {len(words)} words")
print("transcript:", full)
