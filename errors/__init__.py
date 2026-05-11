"""error 分類 + 構造化 envelope。

UI で「何が原因で失敗したか」を表示するために、各 stage / phase の
失敗を 8 種 + unknown のいずれかに分類し、actionable_hint と共に保存する。
詳細は docs/plannings/2026-05-11_pipeline-failure-detail-ui.md を参照。
"""
from errors.classify import (
    ERROR_TYPES,
    build_error_detail,
    classify_error,
)

__all__ = ["ERROR_TYPES", "build_error_detail", "classify_error"]
