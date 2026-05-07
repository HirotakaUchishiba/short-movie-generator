"""QA 不良サンプル記録 facade。

reject API (= 人手) / 自動 validator (= Phase 1+) / regenerate 暗黙アーカイブ
の 3 経路から共通で使う。役割は:

  1. data/qa_failures/<TS>_<stage>_<n>/ に artifact + screenplay snapshot をコピー
  2. meta.json (タグ / source / scene_idx / line_idx / note 等) を書き出す
  3. analytics.qa_failures に 1 行追加して id を返す

呼出側は artifact のパスと screenplay snapshot のパスを渡すだけで済む。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime
from typing import Iterable

import config
from analytics import db
from qa.categories import validate_source, validate_tags

logger = logging.getLogger(__name__)


def qa_failures_root() -> str:
    """``data/qa_failures/`` の絶対パスを返す。"""
    return os.path.join(config.BASE_DIR, "data", "qa_failures")


def _next_seq(ts: str, stage: str) -> int:
    """同 ts/stage の中で連番を返す (= 衝突回避)。"""
    root = qa_failures_root()
    if not os.path.isdir(root):
        return 0
    prefix = f"{ts}_{stage}_"
    existing = [
        n for n in os.listdir(root)
        if n.startswith(prefix) and os.path.isdir(os.path.join(root, n))
    ]
    return len(existing)


def record_failure(
    *,
    ts: str,
    stage: str,
    source: str,
    tags: Iterable[str] | None = None,
    note: str | None = None,
    scene_idx: int | None = None,
    line_idx: int | None = None,
    artifact_paths: Iterable[str] | None = None,
    screenplay_snapshot_path: str | None = None,
) -> tuple[int, str]:
    """qa_failures に記録 + artifact をコピー。

    Args:
        ts: project の TS (= temp/<TS> のディレクトリ名)
        stage: progress_store.STAGES のいずれか
        source: qa.categories.QA_FAILURE_SOURCES のいずれか
        tags: qa.categories.QA_FAILURE_TAGS のうちの list (空 list 可)
        note: 自由記述 1 行 note
        scene_idx / line_idx: 不良の局所化情報 (任意)
        artifact_paths: コピー対象の artifact 絶対パス群 (= 存在しないものは無視)
        screenplay_snapshot_path: project の screenplay.json (= 存在すれば
            ``screenplay.json`` という名前でコピー)

    Returns:
        ``(failure_id, archive_dir)``。``archive_dir`` は ``data/qa_failures/<TS>_<stage>_<n>``。

    Raises:
        ValueError: source / tags が enum 範囲外の場合。
    """
    validate_source(source)
    tag_list = list(tags or [])
    validate_tags(tag_list)

    seq = _next_seq(ts, stage)
    archive_dir = os.path.join(qa_failures_root(), f"{ts}_{stage}_{seq}")
    os.makedirs(archive_dir, exist_ok=True)

    copied_artifact: str | None = None
    for p in artifact_paths or ():
        if not p or not os.path.exists(p):
            continue
        dst = os.path.join(archive_dir, os.path.basename(p))
        try:
            shutil.copy2(p, dst)
        except OSError as e:
            logger.warning("qa archive: artifact copy failed %s: %s", p, e)
            continue
        if copied_artifact is None:
            copied_artifact = dst

    copied_snapshot: str | None = None
    if screenplay_snapshot_path and os.path.exists(screenplay_snapshot_path):
        copied_snapshot = os.path.join(archive_dir, "screenplay.json")
        try:
            shutil.copy2(screenplay_snapshot_path, copied_snapshot)
        except OSError as e:
            logger.warning("qa archive: snapshot copy failed: %s", e)
            copied_snapshot = None

    meta = {
        "ts": ts,
        "stage": stage,
        "source": source,
        "tags": tag_list,
        "note": note,
        "scene_idx": scene_idx,
        "line_idx": line_idx,
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(os.path.join(archive_dir, "meta.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    failure_id = db.insert_qa_failure(
        ts=ts, stage=stage, source=source,
        tags=tag_list, note=note,
        scene_idx=scene_idx, line_idx=line_idx,
        artifact_path=copied_artifact,
        screenplay_snapshot_path=copied_snapshot,
    )
    logger.info(
        "qa_failure recorded: id=%d ts=%s stage=%s source=%s tags=%s dir=%s",
        failure_id, ts, stage, source, tag_list, archive_dir,
    )
    return failure_id, archive_dir
