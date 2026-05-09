"""scene 内の line emotion から arc / 視覚 cue を導出する pure function 群。

scene_gen.py から段階分割の 2 step 目として抽出 (= stages/text_utils.py に
続く)。`config.EMOTION_EN` / `config.EMOTION_VISUAL_CUES` を参照するが、
それ以外は副作用なし。
"""
from __future__ import annotations

from collections import Counter

import config


def dominant_emotion(scene: dict) -> str | None:
    """scene の lines[].emotion で最頻の値を返す (= tie のときは先勝ち)。"""
    emotions = [
        line.get("emotion")
        for line in (scene.get("lines") or [])
        if line.get("emotion")
    ]
    if not emotions:
        return None
    return Counter(emotions).most_common(1)[0][0]


def emotion_arc_en(scene: dict) -> str:
    """lines[].emotion を英訳 EMOTION_EN で arc 化 (= "surprise → urgency → calm")。

    重複は除き、出現順を保つ。
    """
    seen: set[str] = set()
    parts: list[str] = []
    for line in scene.get("lines") or []:
        e = line.get("emotion")
        if not e or e in seen:
            continue
        seen.add(e)
        parts.append(config.EMOTION_EN.get(e, e))
    return " → ".join(parts)


def emotion_arc_summary(scene: dict, cue_key: str) -> str:
    """lines[].emotion ごとに EMOTION_VISUAL_CUES[cue_key] を引き、" → " 連結。

    例: ``["焦り", "焦り", "満足"]`` + ``"motion"`` →
        ``"rushed forward-leaning movement → rushed forward-leaning movement →
         relaxed open posture"``。連続重複は畳む。
    """
    cues: list[str] = []
    for line in scene.get("lines", []) or []:
        emo = line.get("emotion")
        if not emo:
            continue
        v = config.EMOTION_VISUAL_CUES.get(emo, {}).get(cue_key)
        if v:
            cues.append(v)
    deduped: list[str] = []
    for c in cues:
        if not deduped or deduped[-1] != c:
            deduped.append(c)
    return " → ".join(deduped)


def dominant_visual_cues(scene: dict) -> dict:
    """EMOTION_VISUAL_CUES の dominant emotion 既定 cue を返す (= 全 cue_key dict)。"""
    dom = dominant_emotion(scene)
    return dict(config.EMOTION_VISUAL_CUES.get(dom or "", {}))
