"""Phase 2: 字幕表示窓と TTS char_ts 実発話長の乖離を検出する。

字幕タイミングの **決定** は char_ts ベース (= `docs/plannings/2026-05-26_subtitle-char-ts-timing.md`)
だが、本 validator は **検証** 側。line.start/end (= TTS stage の snap 結果) や手動
`subtitles[]` の手打ちが、char_ts の実発話と乖離していないかを per-line で測る。
検証対象は chunk 配分の出力でなく snap 結果・手打ち (= char_ts と独立な入力) なので
トートロジーにならない。

座標系: line.start/end はシーン内相対秒、char_ts は tts_full 全文連結の絶対秒。
そのため絶対時刻でなく **長さ (duration)** の比率を比べる (= 座標系非依存)。

対象は単独話者 (tts_full.json)。per-voice (複数 base) / char_ts 不在 / gap は
skip に倒す (= 安全側、`compositor._load_char_timing` と同じ思想)。しきい値は保守的な
暫定値 (= 直近 qa_failures から baseline する前提)。
"""
from __future__ import annotations

import json
import logging
import os

import config
from qa.validators.base import (
    ValidationResult,
    failed_result,
    passed_result,
    skipped_result,
)

logger = logging.getLogger(__name__)


def _load_char_ts(ts_path: str) -> list | None:
    path = os.path.join(ts_path, "tts_full.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) else None


def _line_window(line: dict) -> tuple[float, float] | None:
    s = line.get("start")
    e = line.get("end")
    if s is None or e is None:
        return None
    try:
        return float(s), float(e)
    except (TypeError, ValueError):
        return None


def _speaker_bases(screenplay: dict) -> set[str]:
    bases: set[str] = set()
    for sc in screenplay.get("scenes") or []:
        for ln in sc.get("lines") or []:
            sp = ln.get("speaker")
            if isinstance(sp, str) and sp:
                bases.add(sp.split("__")[0])
    return bases


def check_subtitle_timing(
    ts_path: str, *, screenplay: dict | None = None, **_,
) -> list[ValidationResult]:
    out: list[ValidationResult] = []
    if not screenplay:
        return out

    # per-voice (複数話者 base) は char_ts が tts_full.<base>.json に分かれるため
    # Phase 2 では対象外 (= 静かに skip)。
    if len(_speaker_bases(screenplay)) > 1:
        return out

    char_ts = _load_char_ts(ts_path)
    if char_ts is None:
        return out  # char_ts 不在は skip (= 他経路に影響しない)

    from stages.text_mapping import (
        build_position_to_time_map,
        build_screenplay_text,
        find_line_time_range,
    )

    full_text, line_specs = build_screenplay_text(screenplay)
    pos_to_time = build_position_to_time_map(full_text, char_ts)

    ratio_min = config.SUBTITLE_TIMING_DRIFT_RATIO_MIN
    ratio_max = config.SUBTITLE_TIMING_DRIFT_RATIO_MAX
    scenes = screenplay.get("scenes") or []

    for spec in line_specs:
        s_idx = spec["scene_idx"]
        l_idx = spec["line_idx"]
        try:
            line = scenes[s_idx]["lines"][l_idx]
        except (IndexError, KeyError, TypeError):
            continue
        win = _line_window(line)
        if win is None:
            continue  # start/end 未派生 (= Stage 1 抽象台本) は対象外
        win_dur = win[1] - win[0]
        abs_start, abs_end = find_line_time_range(
            pos_to_time, spec["char_start"], spec["char_end"])
        if abs_start is None or abs_end is None:
            out.append(skipped_result(
                reason="char_ts gap: no timestamp for line span",
                scene_idx=s_idx, line_idx=l_idx))
            continue
        speech_dur = abs_end - abs_start
        if speech_dur <= 0 or win_dur <= 0:
            out.append(skipped_result(
                reason="non-positive duration",
                scene_idx=s_idx, line_idx=l_idx))
            continue
        ratio = win_dur / speech_dur
        metrics = {
            "window_dur": win_dur,
            "speech_dur": speech_dur,
            "ratio": ratio,
        }
        if ratio < ratio_min or ratio > ratio_max:
            if ratio < ratio_min:
                severity = (ratio_min - ratio) / ratio_min
            else:
                severity = (ratio - ratio_max) / ratio_max
            out.append(failed_result(
                score=max(0.0, 1.0 - severity),
                reason=(f"subtitle window {win_dur:.2f}s vs speech "
                        f"{speech_dur:.2f}s (ratio={ratio:.2f}, "
                        f"allowed {ratio_min}-{ratio_max})"),
                tag="subtitle_timing_off",
                metrics=metrics,
                scene_idx=s_idx, line_idx=l_idx))
        else:
            out.append(passed_result(
                score=max(0.0, 1.0 - min(abs(1.0 - ratio), 1.0)),
                metrics=metrics,
                scene_idx=s_idx, line_idx=l_idx))
    return out
