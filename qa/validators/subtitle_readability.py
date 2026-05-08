"""Phase 2: 字幕の長さが視認性を損なっていないかを検査する。

本格的には overlay 後の動画フレームから font size とコントラストを測るが、
Phase 2 では screenplay 上の text 長で代用する (= 1 chunk が長すぎると
overlay の自動チャンク分割で 3 行以上の段組になり読みにくい)。
"""
from __future__ import annotations

from qa.validators.base import (
    ValidationResult,
    failed_result,
    passed_result,
)

# 縦動画 9:16 の場合、フォント 78px / 文字幅 ≈ 78px → 1 行 ≈ 13 文字。
# Phase 2 の暫定: 1 chunk が 20 文字を超えると 2 行以上に折り返って読みにくい。
SUBTITLE_CHUNK_LEN_FAIL = 20


def _line_chunks(line: dict) -> list[str]:
    """``line.subtitles[].text`` があればそれを、無ければ ``line.text`` を使う。"""
    subs = line.get("subtitles")
    if isinstance(subs, list) and subs:
        return [str(s.get("text") or "") for s in subs if isinstance(s, dict)]
    return [str(line.get("text") or "")]


def check_subtitle_readability(
    ts_path: str, *, screenplay: dict | None = None, **_,
) -> list[ValidationResult]:
    """screenplay の各 line (or subtitles chunk) の長さを per-line で検査する。"""
    out: list[ValidationResult] = []
    if not screenplay:
        return out
    for s_idx, scene in enumerate(screenplay.get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        for l_idx, line in enumerate(scene.get("lines") or []):
            if not isinstance(line, dict):
                continue
            chunks = _line_chunks(line)
            max_len = max((len(c) for c in chunks), default=0)
            metrics = {"max_chunk_len": float(max_len)}
            if max_len > SUBTITLE_CHUNK_LEN_FAIL:
                severity = (max_len - SUBTITLE_CHUNK_LEN_FAIL) / 20.0
                out.append(failed_result(
                    score=max(0.0, 1.0 - severity),
                    reason=f"chunk_len={max_len} > {SUBTITLE_CHUNK_LEN_FAIL}",
                    tag="subtitle_too_long",
                    metrics=metrics,
                    scene_idx=s_idx, line_idx=l_idx,
                ))
            else:
                out.append(passed_result(
                    score=1.0 - (max_len / max(SUBTITLE_CHUNK_LEN_FAIL, 1)),
                    metrics=metrics,
                    scene_idx=s_idx, line_idx=l_idx,
                ))
    return out
