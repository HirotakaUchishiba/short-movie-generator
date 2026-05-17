"""Stage 2 TTS の per-character voice 拡張。

設計 doc: docs/plannings/2026-05-17_per-character-tts.md

n 人のキャラが登場する screenplay で「N 並列フル生成 → 切出 → マージ」を
実装する。単独話者は scene_gen.generate_screenplay_tts_one_shot に委譲。

本 module は voice 解決 (3 段 fallback) と per-voice full TTS 生成までを
担当する。line 単位の cut & merge は scene_gen.py 側で行う (= 既存
_build_audios_from_full と同じ責務範囲)。
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import artifact_integrity
import config
import elevenlabs_client
from analyze import character_meta as cmeta_mod
from cost_tracking import recorder as cost_recorder

logger = logging.getLogger(__name__)

# ElevenLabs API への同時 call 数の上限 (= レート制限 + socket 過剰防止)
MAX_PARALLEL_VOICES = 4


@dataclass
class PerVoiceResult:
    """1 voice 用の full TTS 生成結果。

    Fields:
      base: キャラ base id (e.g., "f1")
      voice_id: 実際に使われた ElevenLabs voice_id
      voice_settings: 実際に使われた settings (= stability/similarity_boost/style/speed)
      mp3_path: tts_full.<base>.mp3 の絶対パス
      char_ts_path: tts_full.<base>.json (= char-level timestamps) の絶対パス
      text_hash: cache key (cache hit 判定用)
    """

    base: str
    voice_id: str
    voice_settings: dict[str, Any]
    mp3_path: str
    char_ts_path: str
    text_hash: str


# ─── speaker collection ────────────────────────────────────────────


def collect_unique_speakers(screenplay: dict) -> list[str]:
    """screenplay の全 line.speaker から unique base id を sorted 順で返す。

    line.speaker は compose-resolved id (= "f1" or "f1__office")。
    __wardrobe は voice には影響しないので base に剥がす。
    speaker 未設定 line は無視 (= 結果リストに含めない)。

    単独話者 / 0 話者の判定にこの関数の結果長を使う:
      - 0 or 1 → 既存の one-shot path に委譲 (後方互換)
      - 2+ → per-character path で並列生成
    """

    bases: set[str] = set()
    for scene in screenplay.get("scenes") or []:
        for line in scene.get("lines") or []:
            spk = line.get("speaker")
            if isinstance(spk, str) and spk:
                base, _ = cmeta_mod.split_resolved_id(spk)
                if base:
                    bases.add(base)
    return sorted(bases)


def primary_speaker(screenplay: dict) -> str | None:
    """最も多く登場する speaker (base id) を返す。

    line 数が最大の base が primary。同数のときは sorted で alphabetical 先頭。
    speaker 未設定 line しか無い (= speaker 完全 absent) なら None。

    用途: line.speaker が空の line を当てる先 / merge 時の default voice。
    """

    counts: dict[str, int] = {}
    for scene in screenplay.get("scenes") or []:
        for line in scene.get("lines") or []:
            spk = line.get("speaker")
            if isinstance(spk, str) and spk:
                base, _ = cmeta_mod.split_resolved_id(spk)
                if base:
                    counts[base] = counts.get(base, 0) + 1
    if not counts:
        return None
    max_count = max(counts.values())
    return sorted(b for b, c in counts.items() if c == max_count)[0]


# ─── voice resolution ──────────────────────────────────────────────


def resolve_voice_for_speaker(
    base: str,
) -> tuple[str, dict[str, Any]]:
    """base id から (voice_id, voice_overrides) を 2 段 fallback で引く。

    優先順位:
      1. characters/<base>/voice.json.voice_id (= キャラ既定)
      2. config.ELEVENLABS_VOICE_ID (= グローバル既定)

    voice_overrides (= stability / similarity_boost / style) は character の
    voice_overrides をそのまま返す。読み出し失敗 (FileNotFoundError /
    JSONDecodeError) は warn して空 dict を返す (= config 既定にフォールバック)。

    note: line 単位の voice_id override は本 Phase では非対応
    (= 同 base が常に同 voice で発話する前提)。必要なら将来「virtual speaker」
    概念で拡張する。
    """

    voice_id: str | None = None
    overrides: dict[str, Any] = {}
    try:
        meta = cmeta_mod.load_character_meta(base)
        voice_id = meta.voice_id
        overrides = dict(meta.voice_overrides)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "[per-char tts] character meta 読込失敗 base=%s: %s "
            "(config 既定 voice にフォールバック)", base, e,
        )
    return (voice_id or config.ELEVENLABS_VOICE_ID, overrides)


def build_voice_settings(
    overrides: dict[str, Any],
    speed: float,
) -> dict[str, Any]:
    """ElevenLabs API に渡す voice settings を組み立てる。

    config 既定値をベースに、character の overrides が key 毎に上書きする。
    speed は引数 (= screenplay-wide な native speed) が必ず採用される。
    """

    settings: dict[str, Any] = {
        "stability": config.ELEVENLABS_VOICE_STABILITY,
        "similarity_boost": config.ELEVENLABS_VOICE_SIMILARITY_BOOST,
        "style": config.ELEVENLABS_VOICE_STYLE,
        "speed": speed,
    }
    for k in ("stability", "similarity_boost", "style"):
        if k in overrides:
            settings[k] = overrides[k]
    return settings


# ─── per-voice cache + generation ──────────────────────────────────


def compute_per_voice_cache_key(
    full_text: str,
    voice_id: str,
    settings: dict[str, Any],
) -> str:
    """per-voice TTS の cache key (= 12 hex)。

    full_text + voice_id + settings (= stability/similarity_boost/style/speed)
    のいずれかが変わると miss する。settings は key 順序を固定して比較。
    """

    settings_str = "|".join(
        f"{k}={settings[k]}" for k in sorted(settings.keys())
    )
    raw = f"{full_text}|v={voice_id}|{settings_str}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def per_voice_paths(ts_path: str, base: str) -> dict[str, str]:
    """per-voice intermediate file パス群。

    naming: tts_full.<base>.{mp3,json,text_meta.json}
      - 単独話者の tts_full.mp3 と命名衝突しない
      - glob 'tts_full.*.mp3' で per-voice ファイルだけ列挙可能
      - 既存 _clear_tts_artifacts の 'tts_full.*' パターンに含まれる
    """

    return {
        "mp3": os.path.join(ts_path, f"tts_full.{base}.mp3"),
        "char_ts": os.path.join(ts_path, f"tts_full.{base}.json"),
        "text_meta": os.path.join(ts_path, f"tts_full.{base}.text_meta.json"),
    }


def _generate_one_voice(
    *,
    base: str,
    voice_id: str,
    settings: dict[str, Any],
    full_text: str,
    ts_path: str,
    project_ts: str,
) -> PerVoiceResult:
    """1 voice 分の full TTS を生成 (= API call or cache hit)。

    既存 one-shot と同じ atomic write pattern (.tmp → rename) を使う。
    cache hit なら API 呼出をスキップ。
    """

    paths = per_voice_paths(ts_path, base)
    text_hash = compute_per_voice_cache_key(full_text, voice_id, settings)

    cached_hash: str | None = None
    if os.path.exists(paths["text_meta"]):
        try:
            with open(paths["text_meta"]) as f:
                cached_hash = json.load(f).get("text_hash")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(
                "[per-voice tts:%s] text_hash load 失敗 path=%s: %s",
                base, paths["text_meta"], e,
            )

    need_regen = (
        cached_hash != text_hash
        or not os.path.exists(paths["mp3"])
        or not os.path.exists(paths["char_ts"])
    )

    if not need_regen:
        logger.info(
            "[per-voice tts] base=%s cache hit (hash=%s)", base, text_hash,
        )
        return PerVoiceResult(
            base=base,
            voice_id=voice_id,
            voice_settings=dict(settings),
            mp3_path=paths["mp3"],
            char_ts_path=paths["char_ts"],
            text_hash=text_hash,
        )

    logger.info(
        "[per-voice tts] base=%s voice=%s 全 %d 文字 生成中 (hash=%s)",
        base, voice_id, len(full_text), text_hash,
    )

    # 既存 file の削除 + atomic write
    for p in (paths["mp3"], paths["char_ts"], paths["text_meta"]):
        if os.path.exists(p):
            os.remove(p)

    # generate_speech_with_timestamps は output_path の拡張子を切って
    # <base>.json を作るため、tmp 名も対称にする
    tmp_mp3 = os.path.join(ts_path, f"tts_full.{base}.tmp.mp3")
    tmp_json = os.path.join(ts_path, f"tts_full.{base}.tmp.json")

    try:
        elevenlabs_client.generate_speech_with_timestamps(
            text=full_text,
            voice_id=voice_id,
            output_path=tmp_mp3,
            stability=settings["stability"],
            similarity_boost=settings["similarity_boost"],
            style=settings["style"],
            speed=settings["speed"],
            language=config.LANGUAGE,
            should_keep_whitespace=True,
        )
        if not artifact_integrity.is_valid_audio(tmp_mp3):
            raise RuntimeError(
                f"per-voice TTS 出力が ffprobe 検証に通らず (base={base})"
            )
        os.replace(tmp_json, paths["char_ts"])
        os.replace(tmp_mp3, paths["mp3"])
    except Exception:
        for p in (tmp_mp3, tmp_json):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError as cleanup_err:
                logger.warning(
                    "[per-voice tts:%s] rollback %s 失敗: %s",
                    base, p, cleanup_err,
                )
        raise

    try:
        cost_recorder.record_tts(
            project_ts=project_ts,
            model=elevenlabs_client.MODEL_ID,
            characters=len(full_text),
        )
    except Exception:
        logger.exception(
            "cost recording 失敗 (per-voice TTS base=%s)", base,
        )

    with open(paths["text_meta"], "w") as f:
        json.dump({
            "text_hash": text_hash,
            "voice_id": voice_id,
            "settings": settings,
            "full_text": full_text,
        }, f, ensure_ascii=False, indent=2)

    return PerVoiceResult(
        base=base,
        voice_id=voice_id,
        voice_settings=dict(settings),
        mp3_path=paths["mp3"],
        char_ts_path=paths["char_ts"],
        text_hash=text_hash,
    )


def generate_per_voice_full_audios(
    *,
    speakers: list[str],
    full_text: str,
    ts_path: str,
    speed: float,
    project_ts: str,
) -> dict[str, PerVoiceResult]:
    """speakers の全 voice で同じ full_text を並列生成。

    各 voice の TTS は独立 (= ElevenLabs API call を ThreadPoolExecutor で
    並列実行)。1 voice の失敗は全体を fail-fast (= 部分結果を返さない)。

    Returns: {base: PerVoiceResult}
    """

    if not config.ELEVENLABS_API_KEY:
        raise RuntimeError(
            "ELEVENLABS_API_KEY 未設定で per-voice TTS は実行不能"
        )
    if not speakers:
        return {}

    # 各 speaker の voice + settings を解決 (= 並列前にすべて確定)
    resolved: list[tuple[str, str, dict[str, Any]]] = []
    for base in speakers:
        voice_id, overrides = resolve_voice_for_speaker(base)
        settings = build_voice_settings(overrides, speed)
        resolved.append((base, voice_id, settings))

    max_workers = min(len(resolved), MAX_PARALLEL_VOICES)
    results: dict[str, PerVoiceResult] = {}

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers,
    ) as ex:
        future_to_base = {
            ex.submit(
                _generate_one_voice,
                base=base,
                voice_id=voice_id,
                settings=settings,
                full_text=full_text,
                ts_path=ts_path,
                project_ts=project_ts,
            ): base
            for base, voice_id, settings in resolved
        }
        for future in concurrent.futures.as_completed(future_to_base):
            base = future_to_base[future]
            # fail-fast: 1 voice の失敗で全体を上に投げる
            results[base] = future.result()

    return results
