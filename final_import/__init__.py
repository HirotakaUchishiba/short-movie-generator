"""Stage 7 (final_import) と Stage 8 (publish) の中核ロジック。

CapCut で手動編集した動画を `temp/<TS>/final/` に取り込み、analytics と
ステージ承認を更新する。watchdog / HTTP / CLI の 3 経路から共通呼出。
"""

from .core import (
    FINAL_DIR_NAME,
    FinalVersion,
    canonical_final_path,
    delete_final_version,
    final_dir,
    ensure_final_dir,
    import_final,
    list_final_versions,
    resolve_canonical_video,
    set_canonical_final,
)

__all__ = [
    "FINAL_DIR_NAME",
    "FinalVersion",
    "canonical_final_path",
    "delete_final_version",
    "ensure_final_dir",
    "final_dir",
    "import_final",
    "list_final_versions",
    "resolve_canonical_video",
    "set_canonical_final",
]
