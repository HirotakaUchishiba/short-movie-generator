"""analyze 層が analytics の core logic に依存していないことを保証する。

`docs/developments/architecture.md` §2 の orthogonal 不変条件:
analyze 配下で ``analytics`` を直接 import するのは ``analyze/store.py``
(= storage SSOT) のみ。新しいファイルが analytics に直接依存し始めた
場合に CI で fail させる。
"""
from __future__ import annotations

import re
from pathlib import Path

ANALYZE_DIR = Path(__file__).resolve().parent.parent / "analyze"
ALLOWED_FILE = ANALYZE_DIR / "store.py"
_IMPORT_PATTERN = re.compile(
    r"^\s*(from\s+analytics(?:\.[a-zA-Z_][\w.]*)?\s+import|import\s+analytics(?:\s|$|\.))",
    re.MULTILINE,
)


def test_only_store_imports_analytics():
    """analyze 配下で analytics を直接 import するのは store.py のみ。"""
    violators: list[Path] = []
    for path in sorted(ANALYZE_DIR.rglob("*.py")):
        if path == ALLOWED_FILE:
            continue
        text = path.read_text(encoding="utf-8")
        if _IMPORT_PATTERN.search(text):
            violators.append(path)
    rels = [str(p.relative_to(ANALYZE_DIR.parent)) for p in violators]
    assert violators == [], (
        f"analyze 配下で analytics を直接 import (= orthogonal 違反): {rels}"
    )


def test_store_imports_analytics_db():
    """逆方向の保険: store.py 自体は analytics.db を import している。

    新しい contributor が「orthogonal を守るため」と称して store.py から
    analytics 依存を削除すると schema 適用経路 (= ensure_schema) が壊れる。
    本 test は store.py の依存が **意図的** であることを示すアンカー。
    """
    text = ALLOWED_FILE.read_text(encoding="utf-8")
    assert _IMPORT_PATTERN.search(text), (
        "analyze/store.py は analytics.db を import する設計 "
        "(= analyze 配下で analytics を知る唯一の場所)。 "
        "削除する場合は orthogonal 不変条件全体の見直しが必要。"
    )
