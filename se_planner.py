"""SE 配置の自動導出 (Stage se の中核)。完成 screenplay の既存メタ
(emotion / visual_intent / scene 境界) から「いつ・どの SE を載せるか」を導く。

特定台本へのハードコードはせず、config の mapping (EMOTION_SE_MAP /
VISUAL_INTENT_SE_MAP / SE_TRANSITION_CATEGORY) と catalog の category だけで
汎用化する。絶対時刻は字幕・発話と同じ `_scene_offsets_from_videos` (実尺累積) を
基準にするので SE が発話とズレない。詳細は
docs/plannings/2026-05-27_se-overlay-stage.md。
"""
from __future__ import annotations

import logging

import config
import se_library

logger = logging.getLogger(__name__)


def plan_se(screenplay: dict, scene_offsets: list[float]) -> list[dict]:
    """完成 screenplay + 各 scene の絶対開始秒から SE 配置案を導出する。

    `scene_offsets[i]` は scene i の動画先頭からの絶対開始秒
    (= compositor._scene_offsets_from_videos の出力)。返り値は
    ``[{time, se_id, volume, source, reason}]`` (time は絶対秒)。

    導出ルール (Phase 1):
    - scene 境界 (i>=1) → ``SE_TRANSITION_CATEGORY`` を scene 開始秒に
    - ``scene.annotation.visual_intent_id`` ∈ VISUAL_INTENT_SE_MAP → その category を scene 開始秒に
    - ``line.emotion`` ∈ EMOTION_SE_MAP → その category を line の絶対開始秒に

    category → 具体 se_id は catalog を category で引いた先頭 (実ファイル存在のみ)。
    同 (time, se_id) は dedup、1 scene あたり ``SE_MAX_PER_SCENE`` 個まで (鳴りすぎ防止)。
    """
    scenes = screenplay.get("scenes") or []
    out: list[dict] = []

    for s, scene in enumerate(scenes):
        offset = scene_offsets[s] if s < len(scene_offsets) else 0.0
        cands: list[tuple[float, str, str]] = []  # (time, category, reason)

        if s >= 1:
            cands.append((offset, config.SE_TRANSITION_CATEGORY,
                          f"transition:scene{s + 1}"))

        intent = (scene.get("annotation") or {}).get("visual_intent_id")
        if intent in config.VISUAL_INTENT_SE_MAP:
            cands.append((offset, config.VISUAL_INTENT_SE_MAP[intent],
                          f"intent:{intent}"))

        for line in scene.get("lines") or []:
            emo = line.get("emotion")
            if emo in config.EMOTION_SE_MAP:
                t = offset + float(line.get("start") or 0.0)
                cands.append((t, config.EMOTION_SE_MAP[emo], f"emotion:{emo}"))

        seen: set[tuple[float, str]] = set()
        placed = 0
        for time, category, reason in sorted(cands, key=lambda c: c[0]):
            tracks = se_library.se_by_category(category)
            if not tracks:
                continue
            se_id = tracks[0].id
            key = (round(time, 2), se_id)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "time": round(time, 3),
                "se_id": se_id,
                "volume": config.SE_DEFAULT_VOLUME,
                "source": "auto",
                "reason": reason,
            })
            placed += 1
            if placed >= config.SE_MAX_PER_SCENE:
                break

    logger.info("[se] 自動配置: %d 個 (%d scenes)", len(out), len(scenes))
    return out
