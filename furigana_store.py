"""ふりがな永続辞書の管理。

data/furigana_dict.json に蓄積。analyze_video が新たに発見した読みを
mergeして保存し、次回以降は既知扱いとなる。

scene_gen 側ではこの辞書 + 各 line.pronunciation_hints を merge して
TTS送信前のテキスト置換に使う。
"""
import json
import logging
import os
from pathlib import Path

import config

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path(config.BASE_DIR) / "data" / "furigana_dict.json"


def _path() -> Path:
    return Path(os.environ.get("FURIGANA_DICT_PATH", str(DEFAULT_PATH)))


def load() -> dict[str, str]:
    path = _path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning("%s が辞書形式でない → 空辞書を返す", path)
            return {}
        return {str(k): str(v) for k, v in data.items() if k and v}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("ふりがな辞書ロード失敗: %s", e)
        return {}


def save(d: dict[str, str]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    sorted_d = {k: d[k] for k in sorted(d.keys())}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted_d, f, ensure_ascii=False, indent=2)


def merge(new_entries: dict[str, str]) -> dict[str, str]:
    """既存辞書に new_entries を追加し、保存して返す。
    既存と異なる読みが来た場合は new_entries 側で上書き。
    """
    if not new_entries:
        return load()
    current = load()
    cleaned = {str(k).strip(): str(v).strip()
               for k, v in new_entries.items() if k and v}
    added = 0
    updated = 0
    for k, v in cleaned.items():
        if k not in current:
            added += 1
        elif current[k] != v:
            updated += 1
        current[k] = v
    save(current)
    if added or updated:
        logger.info("furigana_dict: +%d new, %d updated, total=%d",
                    added, updated, len(current))
    return current


def collect_from_screenplay(screenplay: dict) -> dict[str, str]:
    """screenplay内の全lineのpronunciation_hintsを集約して返す。"""
    out: dict[str, str] = {}
    for scene in screenplay.get("scenes", []) or []:
        for line in scene.get("lines", []) or []:
            hints = line.get("pronunciation_hints") or {}
            for k, v in hints.items():
                if k and v:
                    out[str(k)] = str(v)
    return out
