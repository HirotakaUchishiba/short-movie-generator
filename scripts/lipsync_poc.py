import os
import sys
import time

import fal_client
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

MODEL_ID = "fal-ai/sync-lipsync"


def _ensure_key() -> None:
    key = config.FAL_API_KEY
    if key:
        os.environ["FAL_KEY"] = key


def run(video_path: str, audio_path: str, output_path: str,
        sync_mode: str = "cut_off", model: str = "lipsync-1.9.0-beta") -> None:
    _ensure_key()

    print(f"[1/4] アップロード video: {video_path}")
    t0 = time.time()
    video_url = fal_client.upload_file(video_path)
    print(f"      → {video_url} ({time.time() - t0:.1f}s)")

    print(f"[2/4] アップロード audio: {audio_path}")
    t0 = time.time()
    audio_url = fal_client.upload_file(audio_path)
    print(f"      → {audio_url} ({time.time() - t0:.1f}s)")

    print(f"[3/4] sync-lipsync 実行 (model={model}, sync_mode={sync_mode})")
    t0 = time.time()
    result = fal_client.subscribe(
        MODEL_ID,
        arguments={
            "video_url": video_url,
            "audio_url": audio_url,
            "model": model,
            "sync_mode": sync_mode,
        },
        with_logs=True,
        on_queue_update=lambda update: None,
    )
    print(f"      処理時間: {time.time() - t0:.1f}s")

    result_url = result["video"]["url"]
    print(f"[4/4] 結果ダウンロード: {result_url}")
    resp = requests.get(result_url)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        f.write(resp.content)
    size_mb = len(resp.content) / 1024 / 1024
    print(f"      → {output_path} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    video = sys.argv[1] if len(sys.argv) > 1 else \
        "temp/20260424_003550/seg_000.mp4"
    audio = sys.argv[2] if len(sys.argv) > 2 else \
        "temp/20260424_003550/tts_000.mp3"
    out = sys.argv[3] if len(sys.argv) > 3 else \
        "temp/lipsync_poc_seg_000.mp4"

    run(video, audio, out)
