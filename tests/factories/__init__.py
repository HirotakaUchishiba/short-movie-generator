"""Domain object factories for test fixtures.

新規テストでは画面の dict を直接組み立てず、ここの ``make_*`` ヘルパー経由で
インスタンス化する (= ``docs/developments/testing.md`` §4 参照)。
"""

from .line import make_line
from .project import make_project_metadata
from .scene import make_scene
from .screenplay import make_screenplay

__all__ = [
    "make_line",
    "make_project_metadata",
    "make_scene",
    "make_screenplay",
]
