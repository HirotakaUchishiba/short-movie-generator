"""stage 別 artifact パスの解決ロジック (= reject / regenerate / auto-loop の共通入口)。

`temp/<TS>/` 直下の生成物 (= tts_*.mp3 / bg_*.png / kling_*.mp4 / scene_*.mp4
/ overlaid.mp4) を stage と局所化情報 (scene_idx / line_idx) から逆引きする。

このモジュールは Phase 0 の reject API + regenerate アーカイブ、
Phase 1 の auto_loop validator + retry archive、両方から使う。
"""
from __future__ import annotations

import glob
import os


def stage_artifact_paths(ts_path: str, stage: str,
                         scene_idx: int | None,
                         line_idx: int | None) -> list[str]:
    """指定 stage の reject / regenerate 対象の artifact パスを返す。

    存在しないファイルは呼び出し側 (= ``qa.recorder.record_failure``) が
    skip するので、ここでは ``os.path.exists`` チェックを省く。

    ``script`` stage は screenplay.json 自体が artifact だが、recorder が
    snapshot として別途コピーするので空 list を返す (= 二重保存を避ける)。
    """
    paths: list[str] = []
    if stage == "tts":
        if scene_idx is not None and line_idx is not None:
            paths.append(os.path.join(ts_path, f"tts_{scene_idx}_{line_idx}.mp3"))
        elif scene_idx is not None:
            paths.extend(sorted(glob.glob(
                os.path.join(ts_path, f"tts_{scene_idx}_*.mp3"))))
        else:
            paths.append(os.path.join(ts_path, "tts_full.mp3"))
            paths.extend(sorted(glob.glob(
                os.path.join(ts_path, "tts_*_*.mp3"))))
    elif stage == "bg" and scene_idx is not None:
        paths.append(os.path.join(ts_path, f"bg_{scene_idx}.png"))
    elif stage == "kling" and scene_idx is not None:
        paths.append(os.path.join(ts_path, f"kling_{scene_idx}.mp4"))
        paths.append(os.path.join(ts_path, f"scene_{scene_idx}.trim.mp4"))
    elif stage == "scene" and scene_idx is not None:
        paths.append(os.path.join(ts_path, f"scene_{scene_idx}.mp4"))
    elif stage == "overlay":
        paths.append(os.path.join(ts_path, "overlaid.mp4"))
    return paths
