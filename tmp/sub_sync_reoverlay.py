"""修正後の compositor で既存 merged.mp4 に字幕を焼き直す (検証用・使い捨て)。
動画/背景/TTS は再生成しない (= 課金なし)。出力を再度フレーム解析して drift を確認。
"""
import glob
import os

import compositor
import staged_pipeline

ts_dir = "temp/20260525_142154"
sp = staged_pipeline.load_project_screenplay(ts_dir)
scene_videos = sorted(
    glob.glob(os.path.join(ts_dir, "scene_[0-9][0-9][0-9].mp4")))
merged = os.path.join(ts_dir, "merged.mp4")
out = "tmp/sub_sync/overlaid_fixed.mp4"
print(f"scenes={len(sp['scenes'])} scene_videos={len(scene_videos)}")
compositor._apply_overlays(merged, sp, ts_dir, out, scene_videos=scene_videos)
print("done:", out)
