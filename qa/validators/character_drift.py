"""Phase 2: Kling 動画の代表フレームと reference 画像の埋め込み距離検査。

CLIP image embedding を使ってシーン代表フレーム ↔ ``character_refs``
画像の cosine 距離を測る。距離 > 閾値で「キャラ崩壊」とみなす。

CLIP モデル / sentence_transformers が利用できない環境では
``skipped_result`` を返して auto_loop は通す。Phase 3 / 4 で本番運用に
する場合は ML 依存を整える前提。

しきい値は Phase 0 の正常データ (= human approved) から baseline する想定。
"""
from __future__ import annotations

import glob
import logging
import os
import re

from qa.validators.base import (
    ValidationResult,
    failed_result,
    passed_result,
    skipped_result,
)

logger = logging.getLogger(__name__)

KLING_FILE_RE = re.compile(r"kling_(\d+)\.mp4$")
CHAR_DRIFT_DISTANCE_FAIL = 0.35  # cosine 距離 (= 1 - similarity) がこれを超えると fail
# 代表フレームを取り出す秒数。Kling は 5s / 10s 出力なので 1.0s なら必ず安全圏で
# かつ初動 (= subject の動きが完了していない静止状態) を避けられる。
_REPRESENTATIVE_FRAME_SEC = 1.0

# CLIP モデルは module-level cache する (= auto_loop の retry ループで毎回
# 数百 MB のロードを起こさない)。ロード成否を 1 度だけ評価し、以後は同じ結果を返す。
_CLIP_MODEL: object | None = None
_CLIP_LOAD_ATTEMPTED = False


def _load_clip_model():
    """sentence_transformers の CLIP を lazy load (= module-level cache)。失敗で None。

    cache 実装上、test 等で再評価したい場合は ``_CLIP_MODEL`` /
    ``_CLIP_LOAD_ATTEMPTED`` を直接 reset するか、関数自体を ``patch.object`` で
    すり替える。
    """
    global _CLIP_MODEL, _CLIP_LOAD_ATTEMPTED
    if _CLIP_LOAD_ATTEMPTED:
        return _CLIP_MODEL
    _CLIP_LOAD_ATTEMPTED = True
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        _CLIP_MODEL = SentenceTransformer("clip-ViT-B-32")
    except (ImportError, ModuleNotFoundError):
        _CLIP_MODEL = None
    except Exception as e:  # pragma: no cover
        logger.warning("[character_drift] CLIP load failed: %s", e)
        _CLIP_MODEL = None
    return _CLIP_MODEL


def _extract_representative_frame(mp4_path: str, frame_path: str) -> bool:
    """中間付近のフレームを png に抜き出す。

    最初のフレームは Kling 動画の "動き出し" 直前 (= 静止状態に近い) のことが
    多く、character_refs の参照画像も静止全身 std なので両者が無相関になりやすい。
    1.0s 地点を取れば subject の動作が乗った状態と参照画像を比較できる。動画長
    が 1s 未満で seek 失敗した場合は最初のフレームへフォールバックする。
    """
    import subprocess
    for ss in (f"00:00:0{_REPRESENTATIVE_FRAME_SEC:.1f}", "00:00:00"):
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-y",
             "-ss", ss, "-i", mp4_path,
             "-vframes", "1", frame_path],
            capture_output=True, text=True, check=False, timeout=30,
        )
        if proc.returncode == 0 and os.path.exists(frame_path):
            return True
    return False


def _resolve_character_ref_paths(refs: list[str]) -> list[str]:
    """``character_refs`` から実ファイルパス候補を返す。"""
    import config
    out: list[str] = []
    for ref in refs:
        if not ref:
            continue
        if "__" in ref:
            base, wardrobe = ref.split("__", 1)
            p = os.path.join(config.CHARACTERS_DIR, base, f"{wardrobe}.png")
        else:
            p = os.path.join(config.CHARACTERS_DIR, ref, "base.png")
        if os.path.exists(p):
            out.append(p)
            continue
        flat = os.path.join(config.CHARACTERS_DIR, f"{ref}.png")
        if os.path.exists(flat):
            out.append(flat)
    return out


def check_character_drift(
    ts_path: str, *, screenplay: dict | None = None, **_,
) -> list[ValidationResult]:
    """各 ``kling_<S>.mp4`` の代表フレームと scene の character_refs の距離を計算。"""
    model = _load_clip_model()
    out: list[ValidationResult] = []
    klings = sorted(glob.glob(os.path.join(ts_path, "kling_*.mp4")))
    if not klings:
        return out
    if model is None:
        for mp4 in klings:
            m = KLING_FILE_RE.search(mp4)
            if m:
                out.append(skipped_result(
                    reason="CLIP model unavailable (= sentence_transformers not installed)",
                    scene_idx=int(m.group(1)),
                ))
        return out

    scenes = (screenplay or {}).get("scenes") or []
    import tempfile
    from PIL import Image

    with tempfile.TemporaryDirectory() as tmp:
        for mp4 in klings:
            m = KLING_FILE_RE.search(mp4)
            if not m:
                continue
            s_idx = int(m.group(1))
            scene = scenes[s_idx] if s_idx < len(scenes) else None
            refs = (scene or {}).get("character_refs") or []
            ref_paths = _resolve_character_ref_paths(refs)
            if not ref_paths:
                # キャラ無しシーンは判定 skip (= 背景のみ)
                continue
            frame_path = os.path.join(tmp, f"frame_{s_idx}.png")
            if not _extract_representative_frame(mp4, frame_path):
                out.append(failed_result(
                    score=0.0, reason="frame extraction failed",
                    tag="character_drift", scene_idx=s_idx,
                ))
                continue
            try:
                emb_frame = model.encode([Image.open(frame_path)],
                                         normalize_embeddings=True)
                emb_refs = model.encode(
                    [Image.open(p) for p in ref_paths],
                    normalize_embeddings=True,
                )
            except Exception as e:
                out.append(failed_result(
                    score=0.0, reason=f"CLIP encode failed: {e}",
                    tag="character_drift", scene_idx=s_idx,
                ))
                continue
            # 最も近い ref への cosine 距離 (= 1 - sim)
            sims = (emb_frame @ emb_refs.T).flatten()
            best_sim = float(sims.max())
            distance = 1.0 - best_sim
            metrics = {"clip_distance": distance, "best_similarity": best_sim}
            if distance > CHAR_DRIFT_DISTANCE_FAIL:
                out.append(failed_result(
                    score=max(0.0, 1.0 - distance),
                    reason=f"clip_distance={distance:.3f} > {CHAR_DRIFT_DISTANCE_FAIL}",
                    tag="character_drift",
                    metrics=metrics, scene_idx=s_idx,
                ))
            else:
                out.append(passed_result(
                    score=1.0 - distance, metrics=metrics, scene_idx=s_idx,
                ))
    return out
