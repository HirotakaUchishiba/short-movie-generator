"""analyze ジョブ永続化レイヤ (= storage SSOT)。

`docs/developments/architecture.md` §2 の「analyze と analytics は orthogonal
(互いの core logic は知らない)」を満たすため、analyze 側のロジック (= job.py
runner.py 他) は本モジュール経由でだけ DB に触る。analytics モジュールを
直接 import するのは本ファイルだけに閉じる。

物理的には analyze_jobs / analyze_phases / reference_videos の 3 table が
``data/analytics.db`` 内に同居しているが、analyze 側のコードからは隠蔽
されている。将来的に analyze 専用 DB file (= ``data/analyze.db``) に
分離する場合も、本モジュールの get_connection() / ensure_schema() の
中身だけ差し替えれば良いように接続管理を集約してある。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from analytics import db as _analytics_db


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """analyze ジョブ永続化用の sqlite 接続を返す。

    現状は analytics.db と物理的に同じ DB file を共有しており、接続管理は
    ``analytics.db.get_connection`` に委譲している。analyze 側のコードは
    本関数だけを使い、analytics モジュールを直接 import しない。
    """
    with _analytics_db.get_connection() as conn:
        yield conn


def ensure_schema() -> None:
    """analyze 専用 table (= analyze_jobs / analyze_phases / reference_videos)
    が存在することを保証する。

    現状は ``analytics.db.init_db()`` が ``schema.sql`` を apply する経路に
    乗っているため、それを呼ぶ。物理分離した場合は本関数で analyze 専用
    schema を apply する想定。
    """
    _analytics_db.init_db()
