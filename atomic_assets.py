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

``actions/<id>.json`` の ``duration_bucket_sec`` は X-3 以降で scene 粒度の
bandit 軸として参照する予定で、X-2a 時点では誰も読まない (= 仕様として残す)。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ACTIONS_DIR = ROOT / "actions"
HOOKS_DIR = ROOT / "hooks"
ARCS_DIR = ROOT / "arcs"

_VALID_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class AtomicAssetNotFound(KeyError):
    """指定された id の atomic asset が存在しない / id 形式が不正なとき。"""


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_or_raise(directory: Path, asset_id: str, kind: str) -> dict:
    if not isinstance(asset_id, str) or not _VALID_ID_RE.match(asset_id):
        raise AtomicAssetNotFound(
            f"{kind} '{asset_id}' is not a valid id "
            f"(allowed pattern: {_VALID_ID_RE.pattern})",
        )
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


def build_prompt_menu() -> dict:
    """Phase X-2b: Claude SYSTEM_PROMPT に注入する atomic id menu を構築する。

    各集合の id + 主要メタ (= Claude が選択判断するために必要な最小限) のみを
    含む。subject_state / animation_motion 等の生成 prompt 本体は **含めない**
    (= Claude にビジュアル詳細を意識させると "似たシーンを自由生成して" の方向
    に逸れるため)。

    返り値の構造:
        {
          "actions": [{id, label, recommended_emotion, recommended_camera_distance,
                       compatible_locations, duration_bucket_sec}, ...],
          "hooks":   [{id, label, description, first_scene_action_id,
                       follow_arc_id_candidates}, ...],
          "arcs":    [{id, label, description, emotion_sequence,
                       scene_count_range}, ...],
        }

    ローカル disk から都度ロードする (= キャッシュ無し)。SSOT 集合は数十件
    オーダーでファイル I/O も微量、analyze pipeline は 1 動画 1 回しか呼ばない
    のでパフォーマンス影響は無視できる。
    """
    actions: list[dict] = []
    for action_id in list_action_ids():
        a = load_action(action_id)
        actions.append({
            "id": action_id,
            "label": a.get("label"),
            "recommended_emotion": a.get("recommended_emotion"),
            "recommended_camera_distance": a.get("recommended_camera_distance"),
            "compatible_locations": a.get("compatible_locations") or [],
            "duration_bucket_sec": a.get("duration_bucket_sec"),
        })

    hooks: list[dict] = []
    for hook_id in list_hook_ids():
        h = load_hook(hook_id)
        first_template = h.get("first_scene_template") or {}
        hooks.append({
            "id": hook_id,
            "label": h.get("label"),
            "description": h.get("description"),
            "first_scene_action_id": first_template.get("action_id"),
            "follow_arc_id_candidates": h.get("follow_arc_id_candidates") or [],
        })

    arcs: list[dict] = []
    for arc_id in list_arc_ids():
        ar = load_arc(arc_id)
        arcs.append({
            "id": arc_id,
            "label": ar.get("label"),
            "description": ar.get("description"),
            "emotion_sequence": ar.get("emotion_sequence") or [],
            "scene_count_range": ar.get("scene_count_range"),
        })

    return {"actions": actions, "hooks": hooks, "arcs": arcs}
