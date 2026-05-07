"""project (= temp/<TS>) の metadata.json ヘルパー。

実際のディレクトリ構造の作成は test 側が行う前提で、ここは metadata 構造のみ。
"""

from typing import Any


def make_project_metadata(
    *,
    screenplay_sha: str = "0" * 64,
    final_versions: list[dict] | None = None,
    published_posts: list[dict] | None = None,
    **overrides: Any,
) -> dict:
    meta: dict = {
        "screenplay_sha": screenplay_sha,
        "final_versions": final_versions if final_versions is not None else [],
        "published_posts": published_posts if published_posts is not None else [],
    }
    meta.update(overrides)
    return meta
