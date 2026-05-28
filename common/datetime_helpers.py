"""project 内で重複していた datetime helper を 1 箇所に集約 (= §3.1.5)。

- ``now_iso_local_seconds()`` — local time, second precision の ISO 8601。
  bg/kling cache decisions の ``decided_at`` 等、人間可読の audit 用途に
  使う tz-naive 文字列。

別 semantics の helper は意図的にここに集約しない:
- ``clip_library._now_iso()`` は UTC + ms (= 競合解決に細粒度が必要)
- ``analyze.suggestion_store._now_iso()`` は UTC + ``Z`` suffix (= JSON 互換)
"""

from __future__ import annotations

from datetime import datetime


def now_iso_local_seconds() -> str:
    """ISO 8601 (local time, second precision) の現在時刻文字列。

    例: ``2026-05-19T07:34:21``
    """
    return datetime.now().isoformat(timespec="seconds")
