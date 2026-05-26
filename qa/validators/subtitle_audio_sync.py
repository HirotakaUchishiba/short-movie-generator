"""Phase 2: 完成動画 (overlaid.mp4) の TTS 音声を Whisper で再文字起こしし、
焼き込み字幕テキストと突き合わせる **出口実測** validator。

char_ts validator (`subtitle_timing`) が TTS パイプライン内部の整合を見るのに対し、
本 validator はパイプラインから独立した出口の実測。char_ts 自体のズレや字幕焼き込みの
テキスト不整合 (= 誤読 / 別テキスト発話) を検出する。

第一版は「字幕テキスト連結 vs Whisper transcript の文字一致率」を主指標にする
(= 句読点・空白を除去した difflib 類似度)。line 単位の精密な時刻アライメントは
将来 Phase (= scene offset 累積と word timestamp の対応付けが要るため)。

重い (= Whisper 推論 / API 課金可能性) ため既定 blacklist (OFF)。明示有効化で実行。
依存 / 成果物が無ければ skip。
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


def _char_match_ratio(ref: str, hyp: str) -> float:
    from difflib import SequenceMatcher
    if not ref:
        return 1.0
    return SequenceMatcher(None, ref, hyp).ratio()


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

    hyp = _normalize(str(result.get("text") or ""))
    ratio = _char_match_ratio(ref, hyp)
    threshold = config.SUBTITLE_AUDIO_SYNC_MATCH_MIN
    metrics = {
        "match_ratio": ratio,
        "ref_len": float(len(ref)),
        "hyp_len": float(len(hyp)),
    }
    if ratio < threshold:
        return [failed_result(
            score=ratio,
            reason=(f"subtitle vs audio transcript match {ratio:.0%} "
                    f"< {threshold:.0%} (誤読 / 焼き込みテキスト不整合の疑い)"),
            tag="subtitle_timing_off", metrics=metrics)]
    return [passed_result(score=ratio, metrics=metrics)]
