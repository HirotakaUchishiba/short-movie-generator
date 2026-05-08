"""Phase X-2a: actions/ hooks/ arcs/ の atomic SSOT ローダー。

各集合は手書き JSON ファイルで構成された絞られた集合 (= SSOT)。
compose / scene_gen / analyze pipeline から id 経由で参照される。

X-2a では id が明示された scene でのみ atomic 経路が動き、無い scene は
既存の free-form 経路 (= scene.background_prompt / scene.animation_prompt
の自由テキスト) で動作する (= 互換維持)。
X-2b で analyze pipeline を id 選択方式に切り替えると、すべての scene が
atomic 経路に乗り、auto_loop でも cache 完全一致が構造的に発生する。

`docs/plannings/2026-05-08_composition-cache-design.md` の Layer 1 (=
Atomic Assets) を実装する。location / character は既存の `analyze.location`
/ `characters/` ディレクトリで扱われており、本モジュールはそれと並走する形で
**新規 3 集合 (action / hook / arc)** のロードのみ責務を持つ。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ACTIONS_DIR = ROOT / "actions"
HOOKS_DIR = ROOT / "hooks"
ARCS_DIR = ROOT / "arcs"


class AtomicAssetNotFound(KeyError):
    """指定された id の atomic asset が存在しないとき。"""


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_or_raise(directory: Path, asset_id: str, kind: str) -> dict:
    path = directory / f"{asset_id}.json"
    if not path.exists():
        raise AtomicAssetNotFound(
            f"{kind} '{asset_id}' not found at {path}",
        )
    return _load_json(path)


def _list_ids(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))


def load_action(action_id: str) -> dict:
    """``actions/<action_id>.json`` を読んで dict で返す。"""
    return _load_or_raise(ACTIONS_DIR, action_id, "action")


def load_hook(hook_id: str) -> dict:
    """``hooks/<hook_id>.json`` を読んで dict で返す。"""
    return _load_or_raise(HOOKS_DIR, hook_id, "hook")


def load_arc(arc_id: str) -> dict:
    """``arcs/<arc_id>.json`` を読んで dict で返す。"""
    return _load_or_raise(ARCS_DIR, arc_id, "arc")


def list_action_ids() -> list[str]:
    return _list_ids(ACTIONS_DIR)


def list_hook_ids() -> list[str]:
    return _list_ids(HOOKS_DIR)


def list_arc_ids() -> list[str]:
    return _list_ids(ARCS_DIR)
