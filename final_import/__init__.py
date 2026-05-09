"""Stage 7 (final_import) と Stage 8 (publish) の中核ロジック。

Stage 6 で書き出された pipeline raw を `temp/<TS>/final/` に取り込み、
analytics とステージ承認を更新する。auto_loop の `_import_raw_as_final()`
から呼ばれる唯一の経路。
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
