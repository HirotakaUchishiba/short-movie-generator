"""Phase 2: 完成動画 (overlaid.mp4) の TTS 音声を Whisper で再文字起こしし、
焼き込み字幕テキストと突き合わせる **出口実測** validator。

char_ts validator (`subtitle_timing`) が TTS パイプライン内部の整合を見るのに対し、
本 validator はパイプラインから独立した出口の実測。char_ts 自体のズレや字幕焼き込みの
テキスト不整合 (= 誤読 / 別テキスト発話) を検出する。

指標は「字幕テキストが Whisper transcript にどれだけ含まれるか」の **ref カバレッジ**
(= マッチ文字数 / 字幕文字数、非対称)。対称な ``difflib.ratio()`` だと transcript が
hidden 行発話やナレーションで長いだけで字幕が完全発話でも低下するため使わない
(= cross-critique 指摘の回帰防止)。

重い (= Whisper 推論 / API 課金可能性) ため既定 blacklist (OFF)。明示有効化で実行。
依存 / 成果物が無ければ skip。第一版は動画全体の単一スコア (= 局所化なし)。line 単位の
局所化は将来 Phase。
"""
from __future__ import annotations

import logging
import os
import re

import config
from qa.validators.base import (
    ValidationResult,
    failed_result,
    passed_result,
    skipped_result,
)

logger = logging.getLogger(__name__)

_PUNCT_RE = re.compile(r"[\s、。!?！？「」『』,.\-—…・]+")


def _normalize(text: str) -> str:
    return _PUNCT_RE.sub("", text)


def _collect_subtitle_text(screenplay: dict) -> str:
    parts: list[str] = []
    for sc in screenplay.get("scenes") or []:
        for ln in sc.get("lines") or []:
            if ln.get("hidden"):
                continue
            subs = ln.get("subtitles")
            if isinstance(subs, list) and subs:
                for s in subs:
                    if isinstance(s, dict):
                        parts.append(str(s.get("text") or ""))
            else:
                parts.append(str(ln.get("text") or ""))
    return "".join(parts)


def _coverage_ratio(ref: str, hyp: str) -> float:
    """ref の文字が hyp にどれだけ含まれるか (= 非対称 coverage = マッチ数 / len(ref))。

    対称な ``SequenceMatcher.ratio()`` (= 2M/(len_ref+len_hyp)) は hyp が長いだけで
    低下するため使わない。字幕が完全に発話されていれば transcript が長くても高スコア。
    """
    from difflib import SequenceMatcher
    if not ref:
        return 1.0
    sm = SequenceMatcher(None, ref, hyp, autojunk=False)
    matched = sum(block.size for block in sm.get_matching_blocks())
    return matched / len(ref)


def check_subtitle_audio_sync(
    ts_path: str, *, screenplay: dict | None = None, **_,
) -> list[ValidationResult]:
    if not screenplay:
        return []
    mp4 = os.path.join(ts_path, "overlaid.mp4")
    if not os.path.exists(mp4):
        return []
    ref = _normalize(_collect_subtitle_text(screenplay))
    if not ref:
        return []
    try:
        from whisper_client import transcribe
    except ImportError as e:
        return [skipped_result(reason=f"whisper_client unavailable: {e}")]
    try:
        result = transcribe(mp4)
    except Exception as e:  # noqa: BLE001  (Whisper / IO の広い失敗を skip 扱い)
        logger.warning("[subtitle_audio_sync] whisper failed: %s", e)
        return [skipped_result(reason=f"whisper failed: {e}")]
    if not isinstance(result, dict):
        return [skipped_result(reason="whisper returned non-dict result")]

    hyp = _normalize(str(result.get("text") or ""))
    coverage = _coverage_ratio(ref, hyp)
    threshold = config.SUBTITLE_AUDIO_SYNC_MATCH_MIN
    metrics = {
        "coverage": coverage,
        "ref_len": float(len(ref)),
        "hyp_len": float(len(hyp)),
    }
    if coverage < threshold:
        return [failed_result(
            score=coverage,
            reason=(f"subtitle coverage in audio transcript {coverage:.0%} "
                    f"< {threshold:.0%} (誤読 / 焼き込みテキスト不整合の疑い)"),
            tag="audio_mispronounce", metrics=metrics)]
    return [passed_result(score=coverage, metrics=metrics)]
