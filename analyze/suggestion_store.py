"""novel intent suggestion inbox の永続化レイヤ。

`analyze/intent_resolver.detect_novel_intent_candidates()` が検出した
候補を `data/intent_suggestions.json` に集約し、UI からトリアージできる
ようにする。

設計 doc: docs/plannings/2026-05-10_intent-suggestion-flow.md §2

提供する責務:
  - IntentSuggestionRecord / SuggestionStatus dataclass
  - compute_id() — proposed_id + description から決定論的に id を導出
  - load() / save() — JSON 永続化 (fcntl.LOCK_EX で同時書き込み防止)
  - upsert() — id 一致なら occurrences と updated_at を更新、新規なら append
  - update_status() — 不正遷移は ValueError、dismissed は reason 必須
  - list_by_status() — フィルタ取得 (= UI 一覧用)
  - mark_merged_against_yaml() — accepted entry の proposed_id が
    visual_intents.yaml に出現したら status=merged に遅延更新

不変条件:
  - dismissed の reason は必須 (= 後で見直すための履歴)
  - status を変えずに upsert された場合 (= 再検出) は occurrences のみ +1
  - file ロックで並行 write 衝突を防止 (= preview_server は単一 process だが念のため)
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Iterator, Literal

import config

logger = logging.getLogger(__name__)


SuggestionStatus = Literal[
    "new", "reviewing", "accepted", "dismissed", "merged"
]
_VALID_STATUSES: tuple[SuggestionStatus, ...] = (
    "new", "reviewing", "accepted", "dismissed", "merged",
)
_TERMINAL_STATUSES: frozenset[SuggestionStatus] = frozenset(
    {"dismissed", "merged"}
)
# 許される status 遷移 (= グラフ)。`merged` 遷移は `accepted` からのみ、かつ
# yaml 自動検出経由 (= mark_merged_against_yaml) のみで行う。
_ALLOWED_TRANSITIONS: dict[SuggestionStatus, frozenset[SuggestionStatus]] = {
    "new": frozenset({"reviewing", "accepted", "dismissed"}),
    "reviewing": frozenset({"accepted", "dismissed"}),
    "accepted": frozenset({"merged"}),
    "dismissed": frozenset(),
    "merged": frozenset(),
}


@dataclass
class IntentSuggestionRecord:
    """1 entry を表す inbox レコード。

    `id` は `proposed_id + description.strip()` の sha256 を 16 字に
    切り詰めた値。同じ意味の候補が再検出されたとき dedupe するための鍵。
    """

    id: str
    proposed_id: str
    description: str
    rationale: str
    scene_indices: tuple[int, ...]
    source_screenplay: str
    source_analyze_job_id: str | None
    status: SuggestionStatus
    dismissed_reason: str | None
    occurrences: int
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        # tuple は JSON で list として serialize される。読み戻し時に tuple へ復元
        d["scene_indices"] = list(self.scene_indices)
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "IntentSuggestionRecord":
        scene_indices_raw = raw.get("scene_indices") or []
        if not isinstance(scene_indices_raw, list):
            raise ValueError(
                f"scene_indices must be list, got {type(scene_indices_raw)}"
            )
        return cls(
            id=str(raw["id"]),
            proposed_id=str(raw["proposed_id"]),
            description=str(raw["description"]),
            rationale=str(raw.get("rationale") or ""),
            scene_indices=tuple(int(i) for i in scene_indices_raw),
            source_screenplay=str(raw.get("source_screenplay") or ""),
            source_analyze_job_id=(
                str(raw["source_analyze_job_id"])
                if raw.get("source_analyze_job_id") is not None
                else None
            ),
            status=_coerce_status(raw.get("status")),
            dismissed_reason=(
                str(raw["dismissed_reason"])
                if raw.get("dismissed_reason") is not None
                else None
            ),
            occurrences=int(raw.get("occurrences") or 1),
            created_at=str(raw.get("created_at") or _now_iso()),
            updated_at=str(raw.get("updated_at") or _now_iso()),
        )


@dataclass
class SuggestionInput:
    """upsert に渡す「analyze 検出時の生データ」。id は compute_id で導出。"""

    proposed_id: str
    description: str
    rationale: str
    scene_indices: tuple[int, ...]
    source_screenplay: str
    source_analyze_job_id: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


def compute_id(proposed_id: str, description: str) -> str:
    """proposed_id + description から決定論的に id を導出 (= sha256 先頭 16 字)。

    description は strip して trailing whitespace の差で別 entry になることを
    防ぐ。description の本文 (= 改行や中身) は厳密一致を要求する (= 別 rationale
    として書き分けられた entry を 1 つにまとめてしまうのを避けるため)。
    """

    h = hashlib.sha256()
    h.update(proposed_id.encode("utf-8"))
    h.update(b"\x00")
    h.update(description.strip().encode("utf-8"))
    return h.hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _coerce_status(v: object) -> SuggestionStatus:
    s = str(v or "new")
    if s not in _VALID_STATUSES:
        logger.warning("[suggestion] unknown status '%s', coercing to 'new'", s)
        return "new"
    return s  # type: ignore[return-value]


def _resolve_path(path: str | os.PathLike[str] | None) -> Path:
    return Path(path) if path is not None else Path(config.INTENT_SUGGESTIONS_PATH)


@contextlib.contextmanager
def _locked(path: Path, mode: str) -> Iterator[IO[str]]:
    """fcntl.LOCK_EX で排他ロックを取った状態でファイルを開く。

    write モードの場合は親ディレクトリを mkdir しておく。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    if "r" in mode and not path.exists():
        # 読み込み時に空ファイル相当の挙動にする (= load の初回挙動)
        path.write_text("[]", encoding="utf-8")
    f = path.open(mode, encoding="utf-8")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield f
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


def load(
    path: str | os.PathLike[str] | None = None,
) -> list[IntentSuggestionRecord]:
    """inbox 全件を読み込む。ファイルが無ければ空リスト。"""

    p = _resolve_path(path)
    if not p.exists():
        return []
    try:
        with _locked(p, "r") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[suggestion] inbox 読込失敗 %s: %s", p, e)
        return []
    if not isinstance(raw, list):
        logger.warning("[suggestion] inbox は list 期待 (got %s)", type(raw))
        return []
    out: list[IntentSuggestionRecord] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            out.append(IntentSuggestionRecord.from_dict(entry))
        except (KeyError, ValueError, TypeError) as e:
            logger.warning("[suggestion] entry skip: %s (%s)", e, entry)
    return out


def save(
    records: list[IntentSuggestionRecord],
    path: str | os.PathLike[str] | None = None,
) -> None:
    """inbox を上書き保存。caller が同時書き込み制御済みである前提。"""

    p = _resolve_path(path)
    with _locked(p, "w") as f:
        json.dump(
            [r.to_dict() for r in records],
            f,
            ensure_ascii=False,
            indent=2,
        )
        f.write("\n")


def upsert(
    inputs: list[SuggestionInput],
    path: str | os.PathLike[str] | None = None,
) -> list[IntentSuggestionRecord]:
    """analyze 検出結果を inbox に反映する。

    - id 一致が無ければ status='new' で新規追加
    - id 一致がある場合は occurrences を +1 し source_screenplay /
      source_analyze_job_id を最新値で上書き、updated_at を更新
    - 既存 entry の status は変更しない (= dismissed の自動再浮上を防ぐ)
    """

    if not inputs:
        return load(path)

    p = _resolve_path(path)
    # 取得 → mutate → 書き戻しを 1 ロック内で行う
    with _locked(p, "r+") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError:
            raw = []
        if not isinstance(raw, list):
            raw = []
        existing: list[IntentSuggestionRecord] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            try:
                existing.append(IntentSuggestionRecord.from_dict(entry))
            except (KeyError, ValueError, TypeError):
                pass
        by_id = {r.id: r for r in existing}
        now = _now_iso()
        for inp in inputs:
            sid = compute_id(inp.proposed_id, inp.description)
            cur = by_id.get(sid)
            if cur is None:
                rec = IntentSuggestionRecord(
                    id=sid,
                    proposed_id=inp.proposed_id,
                    description=inp.description,
                    rationale=inp.rationale,
                    scene_indices=tuple(inp.scene_indices),
                    source_screenplay=inp.source_screenplay,
                    source_analyze_job_id=inp.source_analyze_job_id,
                    status="new",
                    dismissed_reason=None,
                    occurrences=1,
                    created_at=now,
                    updated_at=now,
                )
                by_id[sid] = rec
                existing.append(rec)
            else:
                cur.occurrences += 1
                cur.source_screenplay = inp.source_screenplay
                cur.source_analyze_job_id = inp.source_analyze_job_id
                cur.scene_indices = tuple(inp.scene_indices)
                cur.rationale = inp.rationale
                cur.updated_at = now
        # 書き戻し
        f.seek(0)
        f.truncate()
        json.dump(
            [r.to_dict() for r in existing],
            f,
            ensure_ascii=False,
            indent=2,
        )
        f.write("\n")
        return existing


def update_status(
    suggestion_id: str,
    new_status: SuggestionStatus,
    reason: str | None = None,
    path: str | os.PathLike[str] | None = None,
) -> IntentSuggestionRecord:
    """1 entry の status を遷移させる。

    - new_status が `dismissed` の場合は reason 必須 (= 空文字 / None で ValueError)
    - 不正遷移 (= 終端 / グラフに無い遷移) は ValueError
    - 該当 id が無ければ KeyError
    """

    if new_status not in _VALID_STATUSES:
        raise ValueError(f"unknown status: {new_status}")
    if new_status == "dismissed" and not (reason and reason.strip()):
        raise ValueError("dismissed requires non-empty reason")

    p = _resolve_path(path)
    with _locked(p, "r+") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError:
            raw = []
        if not isinstance(raw, list):
            raw = []
        records: list[IntentSuggestionRecord] = []
        target: IntentSuggestionRecord | None = None
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            try:
                rec = IntentSuggestionRecord.from_dict(entry)
            except (KeyError, ValueError, TypeError):
                continue
            if rec.id == suggestion_id:
                target = rec
            records.append(rec)
        if target is None:
            raise KeyError(f"suggestion not found: {suggestion_id}")
        if new_status not in _ALLOWED_TRANSITIONS[target.status]:
            raise ValueError(
                f"invalid transition: {target.status} -> {new_status}"
            )
        target.status = new_status
        target.updated_at = _now_iso()
        if new_status == "dismissed":
            target.dismissed_reason = (reason or "").strip()
        f.seek(0)
        f.truncate()
        json.dump(
            [r.to_dict() for r in records],
            f,
            ensure_ascii=False,
            indent=2,
        )
        f.write("\n")
        return target


def list_by_status(
    status_filter: str = "all",
    path: str | os.PathLike[str] | None = None,
) -> list[IntentSuggestionRecord]:
    """status でフィルタ取得 (= UI 一覧用)。"""

    records = load(path)
    if status_filter == "all":
        return records
    if status_filter not in _VALID_STATUSES:
        raise ValueError(f"unknown status filter: {status_filter}")
    return [r for r in records if r.status == status_filter]


def mark_merged_against_yaml(
    yaml_ids: set[str] | frozenset[str],
    path: str | os.PathLike[str] | None = None,
) -> list[str]:
    """`accepted` 中の entry のうち proposed_id が yaml に登場したものを
    `merged` に遅延更新する。返り値は更新された id のリスト。

    `yaml_ids` は呼び出し側で `part_registry_loader` 等から取得済みの
    現在 yaml の id 集合 (= dependency 注入で test 容易性確保)。
    """

    if not yaml_ids:
        return []
    p = _resolve_path(path)
    if not p.exists():
        return []
    updated: list[str] = []
    with _locked(p, "r+") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError:
            return []
        if not isinstance(raw, list):
            return []
        records: list[IntentSuggestionRecord] = []
        now = _now_iso()
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            try:
                rec = IntentSuggestionRecord.from_dict(entry)
            except (KeyError, ValueError, TypeError):
                continue
            if rec.status == "accepted" and rec.proposed_id in yaml_ids:
                rec.status = "merged"
                rec.updated_at = now
                updated.append(rec.id)
            records.append(rec)
        if updated:
            f.seek(0)
            f.truncate()
            json.dump(
                [r.to_dict() for r in records],
                f,
                ensure_ascii=False,
                indent=2,
            )
            f.write("\n")
    return updated


def counts_by_status(
    path: str | os.PathLike[str] | None = None,
) -> dict[str, int]:
    """status 別の件数を返す (= UI のフィルタバッジ用)。"""

    out: dict[str, int] = {s: 0 for s in _VALID_STATUSES}
    for r in load(path):
        out[r.status] = out.get(r.status, 0) + 1
    return out
