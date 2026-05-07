"""Phase 2: 各 line の発話速度 (文字/分) を検査する。

Stage 2 (TTS) 完了後なら ``line.start`` / ``line.end`` (実音声長) で
実 WPM が計算できる。早口すぎる (> 600 文字/分) と聞き取れない。
"""
from __future__ import annotations

from qa.validators.base import (
    ValidationResult,
    failed_result,
    passed_result,
)

# 1 分あたりの文字数。日本語放送ナレーターは 300 字/分前後、TikTok 系の
# 早口でも 500 字/分 を超えると意味理解が落ちる。
LINE_WPM_FAIL = 600.0


def _wpm(text: str, start: float | None, end: float | None) -> float | None:
    if start is None or end is None or end <= start:
        return None
    duration = float(end) - float(start)
    if duration <= 0:
        return None
    chars = len(text or "")
    return chars / duration * 60.0


def check_story_pacing(
    ts_path: str, *, screenplay: dict | None = None, **_,
) -> list[ValidationResult]:
    out: list[ValidationResult] = []
    if not screenplay:
        return out
    for s_idx, scene in enumerate(screenplay.get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        for l_idx, line in enumerate(scene.get("lines") or []):
            if not isinstance(line, dict):
                continue
            wpm = _wpm(
                line.get("text") or "",
                line.get("start"), line.get("end"),
            )
            if wpm is None:
                # start/end が埋まっていない (= TTS 未実行) なら判断 skip。
                continue
            metrics = {"wpm": wpm}
            if wpm > LINE_WPM_FAIL:
                severity = (wpm - LINE_WPM_FAIL) / 200.0
                out.append(failed_result(
                    score=max(0.0, 1.0 - severity),
                    reason=f"wpm={wpm:.0f} > {LINE_WPM_FAIL:.0f}",
                    tag="story_pacing_off",
                    metrics=metrics,
                    scene_idx=s_idx, line_idx=l_idx,
                ))
            else:
                out.append(passed_result(
                    score=max(0.0, 1.0 - wpm / LINE_WPM_FAIL),
                    metrics=metrics,
                    scene_idx=s_idx, line_idx=l_idx,
                ))
    return out
