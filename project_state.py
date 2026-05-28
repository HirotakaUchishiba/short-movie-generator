"""project の永続化 state へのアクセス基盤。

`temp/<TS>/` 配下の metadata.json と project snapshot に対する I/O と
書き込みロックを集約する。Stage 実装層 (= scene_gen) とオーケストレータ層
(= staged_pipeline) の両方からこのモジュールを依存することで、生成・編集層
が上層 (orchestrator) を import する依存方向の違反を解消する
(= docs/developments/architecture.md §2)。
"""

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)


# project snapshot への書き込みを直列化する per-ts Lock。
# preview_server (REST patch) と scene_gen (TTS regen 後の duration 永続化) の
# 両方から取得して共有する。同時アクセスで disk 上の書き込みが混ざらないように。
_screenplay_locks: dict[str, threading.Lock] = {}
_screenplay_locks_guard = threading.Lock()


def screenplay_lock(name: str) -> threading.Lock:
    """per-key の書き込みロックを返す (テンプレ名 or ts_path どちらでも可)。"""
    with _screenplay_locks_guard:
        lk = _screenplay_locks.get(name)
        if lk is None:
            lk = threading.Lock()
            _screenplay_locks[name] = lk
        return lk


def read_metadata(temp_dir: str) -> dict | None:
    """project の `metadata.json` を読み出す。存在しない / 破損で None を返す。"""
    p = os.path.join(temp_dir, "metadata.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
