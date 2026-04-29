"""content-addressed cache for analyze pipeline phases.

各フェーズの入力 sha256 をキーに結果を保存し、再分析時に再計算をスキップする。
キャッシュ対象は決定論的に再現できるフェーズのみ:
    - transcript (Whisper)        : audio_sha
    - acoustic (librosa segments) : audio_sha + segments_sig
    - bgm_detect                  : audio_sha
    - shots (PySceneDetect)       : video_sha
    - frames (ffmpeg)             : video_sha + fps

audio 抽出と bgm_separate (demucs/HPSS) はキャッシュしない:
    - audio 抽出は ffmpeg で十分高速
    - bgm_separate は assets/bgm/<stem>_bgm.wav に永続化されるため別経路

ディレクトリ構造:
    output/analyze/cache/
        transcript/<audio_sha>.json
        acoustic/<audio_sha>_<segments_sig>.json
        bgm/<audio_sha>.json
        shots/<video_sha>.json
        frames/<video_sha>_fps<fps>.tar
"""
import hashlib
import json
import logging
import os
import tarfile
from pathlib import Path

import config

logger = logging.getLogger(__name__)


CACHE_ROOT = Path(config.BASE_DIR) / "output" / "analyze" / "cache"
KINDS = ("transcript", "acoustic", "bgm", "shots", "frames")


def _cache_dir(kind: str) -> Path:
    if kind not in KINDS:
        raise ValueError(f"unknown cache kind: {kind}")
    d = CACHE_ROOT / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def file_sha256(path: str | Path) -> str:
    """ファイルの sha256 を計算する (8KB チャンク)。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def segments_signature(transcript: dict) -> str:
    """transcript の segments を 16 文字 hash に潰す (acoustic cache 鍵用)。"""
    payload = json.dumps(transcript.get("segments", []), sort_keys=True,
                          ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _fps_label(fps: float) -> str:
    return f"{fps:.2f}".replace(".", "_")


# ─── JSON-based caches (transcript / acoustic / bgm / shots) ────


def _json_path(kind: str, key: str) -> Path:
    return _cache_dir(kind) / f"{key}.json"


def get_json(kind: str, key: str) -> dict | None:
    """Cache hit なら dict、miss なら None。"""
    p = _json_path(kind, key)
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("cache read failed (%s/%s): %s", kind, key, e)
        return None


def put_json(kind: str, key: str, value: dict) -> None:
    p = _json_path(kind, key)
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    tmp.replace(p)


def acoustic_key(audio_sha: str, transcript: dict) -> str:
    """acoustic キャッシュ鍵 = audio_sha + segments_signature。"""
    return f"{audio_sha[:32]}_{segments_signature(transcript)}"


# ─── Frames cache (tar) ─────────────────────────────────────────


def _frames_tar_path(video_sha: str, fps: float) -> Path:
    return _cache_dir("frames") / f"{video_sha}_fps{_fps_label(fps)}.tar"


def has_frames(video_sha: str, fps: float) -> bool:
    return _frames_tar_path(video_sha, fps).exists()


def restore_frames(video_sha: str, fps: float, dest_dir: str) -> list[str] | None:
    """キャッシュから frames を dest_dir に展開し、ファイルパス配列を返す。

    キャッシュがなければ None。
    """
    tar_path = _frames_tar_path(video_sha, fps)
    if not tar_path.exists():
        return None
    os.makedirs(dest_dir, exist_ok=True)
    with tarfile.open(tar_path, "r") as tar:
        tar.extractall(dest_dir, filter="data")
    return sorted(
        os.path.join(dest_dir, f)
        for f in os.listdir(dest_dir)
        if f.startswith("frame_") and f.endswith(".jpg")
    )


def store_frames(video_sha: str, fps: float, frames_dir: str) -> None:
    """frames_dir に展開された frame_*.jpg を tar で永続化。

    frames_dir が存在しない / フレームファイルが無い場合は何もしない
    (mock テストや cancel 後の中途半端な呼び出しに対する安全弁)。
    """
    if not os.path.isdir(frames_dir):
        return
    files = [f for f in sorted(os.listdir(frames_dir))
             if f.startswith("frame_") and f.endswith(".jpg")]
    if not files:
        return
    tar_path = _frames_tar_path(video_sha, fps)
    tmp = tar_path.with_suffix(".tar.tmp")
    with tarfile.open(tmp, "w") as tar:
        for f in files:
            tar.add(os.path.join(frames_dir, f), arcname=f)
    tmp.replace(tar_path)


# ─── 管理ユーティリティ ─────────────────────────────────────────


def clear(kind: str | None = None) -> int:
    """指定 kind (or 全部) のキャッシュをクリア。削除した件数を返す。"""
    targets = [_cache_dir(kind)] if kind else [_cache_dir(k) for k in KINDS]
    n = 0
    for d in targets:
        if not d.exists():
            continue
        for p in d.iterdir():
            if p.is_file():
                p.unlink()
                n += 1
    return n


def stats() -> dict[str, int]:
    """各 kind のキャッシュ件数を返す。"""
    out: dict[str, int] = {}
    for k in KINDS:
        d = CACHE_ROOT / k
        if d.exists():
            out[k] = sum(1 for p in d.iterdir() if p.is_file())
        else:
            out[k] = 0
    return out
