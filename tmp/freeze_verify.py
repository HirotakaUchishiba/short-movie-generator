"""SCENE_TTS_TAIL_BUFFER=0 で merged を再生成 (tpad 発動せず) し、字幕を焼いて
末尾フリーズが消えたか検証する (検証用・使い捨て)。scene 動画は cache 再利用
(= 課金なし)。
"""
import glob
import os

import compositor
import config
import staged_pipeline

print("SCENE_TTS_TAIL_BUFFER =", config.SCENE_TTS_TAIL_BUFFER)
ts_dir = "temp/20260525_142154"
sp = staged_pipeline.load_project_screenplay(ts_dir)
scene_videos = sorted(
    glob.glob(os.path.join(ts_dir, "scene_[0-9][0-9][0-9].mp4")))
# 実コード (tpad 除去 + offset 実尺) で検証。duration は metadata の値
# (tail buffer 0.3 込み) のままだが、_merge_scenes が tpad しないので merged は
# 実尺、字幕 offset も _scene_offsets_from_videos で実尺累積になり一致する。
scene_durations = [float(s["duration"]) for s in sp["scenes"]]
print("durations(metadata):", [round(d, 2) for d in scene_durations],
      "sum =", round(sum(scene_durations), 2))

merged = compositor._merge_scenes(scene_videos, scene_durations, "tmp/freeze")
print("merged:", merged, "dur =",
      round(compositor._get_duration(merged), 2))
out = "tmp/freeze/overlaid_nofreeze.mp4"
compositor._apply_overlays(merged, sp, "tmp/freeze", out,
                           scene_videos=scene_videos)
print("done:", out)
