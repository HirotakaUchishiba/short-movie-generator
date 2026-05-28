"""project (= temp/<TS>) の metadata.json ヘルパー。

実際のディレクトリ構造の作成は test 側が行う前提で、ここは metadata 構造のみ。
"""

from typing import Any


def make_project_metadata(
    *,
    screenplay_sha: str = "0" * 64,
    **overrides: Any,
) -> dict:
    meta: dict = {
        "screenplay_sha": screenplay_sha,
    }
    meta.update(overrides)
    return meta
