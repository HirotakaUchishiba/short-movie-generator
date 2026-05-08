"""Phase 3: experiment_assignments.observed_value の back-fill。

`record_assignments` (= auto_loop の analyze 直前) は ``selected_value`` (= bandit
が「試したい」と言った値) を書く。一方 Haiku が事後に screenplays.<axis> に
タグ付けする値は ``observed_value`` (= 実際に Claude が出した台本がどう分類された
か)。両者を区別して記録することで、後で「directive を Claude が守ったか」「守った
ケースだけで reward を計算するとどう変わるか」を分析できる。

call points:
  - ``scripts/ingest_video.py`` で video 登録直後 (= ts → videos.id が貼られる瞬間)
  - ``scripts/ingest_screenplay.py`` で auto_tag 後 (= screenplays.<axis> が更新される瞬間)

両方 idempotent (= 同じ row への再 UPDATE は同じ値を書くだけ)。
"""
from __future__ import annotations

import logging

from analytics import db

logger = logging.getLogger(__name__)

_AXES = ("hook_type", "tone", "dominant_emotion", "theme")


def back_fill_observed_for_ts(ts: str) -> int:
    """``video_id = ts`` の experiment_assignments すべてに observed_value を書く。

    videos / screenplays の join に失敗する (= まだ ingest_video が走っていない、
    または auto_tag されていない) 軸はスキップする。

    Returns:
        UPDATE が走った row 数。
    """
    total = 0
    with db.get_connection() as conn:
        for axis in _AXES:
            cur = conn.execute(
                f"""UPDATE experiment_assignments
                   SET observed_value = (
                       SELECT s.{axis} FROM videos v
                       JOIN screenplays s ON s.id = v.screenplay_id
                       WHERE v.id = experiment_assignments.video_id
                   )
                   WHERE video_id = ?
                     AND axis = ?
                     AND EXISTS (
                       SELECT 1 FROM videos v2
                       JOIN screenplays s2 ON s2.id = v2.screenplay_id
                       WHERE v2.id = experiment_assignments.video_id
                         AND s2.{axis} IS NOT NULL
                     )""",
                (ts, axis),
            )
            total += cur.rowcount or 0
    return total


def back_fill_observed_for_screenplay(screenplay_id: str) -> int:
    """``screenplays.id = screenplay_id`` を参照する全 video 分を back-fill。

    `ingest_screenplay` で auto_tag した直後に呼ぶ用。screenplay は複数の video
    から参照されうる (= 同じ台本を再生成したケース) ので、該当 video 全部を辿る。
    """
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM videos WHERE screenplay_id = ?",
            (screenplay_id,),
        ).fetchall()
    total = 0
    for r in rows:
        total += back_fill_observed_for_ts(r["id"])
    return total
