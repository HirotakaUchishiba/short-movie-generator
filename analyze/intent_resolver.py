"""Phase 6: visual_intent_id 推定 / novel intent 自動検出 のヘルパ。

`scripts/analyze_video.py` の Claude prompt が **(a) 既存 intent からの選択**
と **(b) confidence 表明** を返せるよう支援する pure Python ユーティリティ群。
LLM 呼び出し自体は本モジュールでは行わない (= analyze_video.py 側で組込む)。

設計 doc: `docs/plannings/2026-05-10_compositional-architecture.md` §8

依存関係:
  - config.PART_REGISTRY_DIR (= visual_intents.yaml の置き場)
  - pyyaml

提供する責務:
  1. load_intent_catalog() — yaml から id / description / valid_start_emotions /
     compatible_with を抽出し、辞書のリストで返す
  2. format_catalog_for_prompt() — catalog を Claude prompt に注入できる短い
     テキストブロックに整形 (= 各 intent を 1-2 行に圧縮)
  3. parse_intent_assignment() — Claude が返した JSON を validate して
     scene_idx → {visual_intent_id, confidence, start_emotion, duration_bucket}
     の辞書に正規化
  4. detect_novel_intent_candidates() — confidence < threshold が連続するシーン
     から「新規 intent 候補」を抽出 (= analyze 出力に併記してオペレータレビュー用)

LLM テストは別セッション (= 実 ANTHROPIC_API_KEY + 実 reference video)。本モジュールは
mock 入力で全 path を unit test 可能。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)


# ───────────── データクラス ─────────────


@dataclass(frozen=True)
class IntentEntry:
    """visual_intents.yaml の 1 entry を表現。"""

    id: str
    description: str
    valid_start_emotions: tuple[str, ...]
    duration_buckets: tuple[int, ...]
    motion_intensity_bucket: str
    compatible_with: tuple[str, ...]
    deprecated: bool = False

    def to_prompt_line(self) -> str:
        """1 intent を 1-2 行のテキストに圧縮 (= Claude prompt 注入用)。"""

        emo = "/".join(self.valid_start_emotions) if self.valid_start_emotions else "any"
        dur = "/".join(str(d) for d in self.duration_buckets) or "5/10"
        return (
            f"  - {self.id} (start_emotion={emo}, duration={dur}, "
            f"motion={self.motion_intensity_bucket})\n"
            f"    {self.description.strip().splitlines()[0]}"
        )


@dataclass
class SceneIntentAssignment:
    """Claude 出力 1 シーン分。confidence 低なら visual_intent_id=None で
    free-text fallback path を取らせる。"""

    scene_idx: int
    visual_intent_id: str | None
    confidence: float
    start_emotion: str | None = None
    duration_bucket: int | None = None
    motion_intensity: str | None = None
    rationale: str | None = None

    @property
    def is_low_confidence(self) -> bool:
        return self.confidence < float(
            getattr(config, "INTENT_CONFIDENCE_THRESHOLD", 0.7)
        )


@dataclass
class NovelIntentCandidate:
    """confidence 低が連続するシーン群から推定される新規 intent 候補。
    オペレータに「visual_intents.yaml にこういう entry を増やすと hit が上がる」
    と提案する。"""

    proposed_id: str
    description: str
    scene_indices: tuple[int, ...]
    rationale: str


# ───────────── catalog load / prompt 整形 ─────────────


def load_intent_catalog(yaml_path: Path | None = None) -> list[IntentEntry]:
    """`config/part_registry/visual_intents.yaml` から IntentEntry のリストを返す。

    deprecated=True のものはフィルタ済み。yaml が無い / 解析失敗時は空リスト。

    yaml load + cache は `part_registry_loader` (= SSOT) に集約。test 用に
    `yaml_path` を渡された場合のみ legacy 経路 (= 直接 yaml 読込) で返す。
    """

    if yaml_path is not None:
        return _load_intent_catalog_from_path(yaml_path)

    import part_registry_loader as _registry

    out: list[IntentEntry] = []
    for entry in _registry.load_registry("visual_intents"):
        if entry.get("deprecated"):
            continue
        out.append(
            IntentEntry(
                id=entry["id"],
                description=str(entry.get("description") or ""),
                valid_start_emotions=tuple(
                    entry.get("valid_start_emotions") or ()
                ),
                duration_buckets=tuple(
                    int(d) for d in (entry.get("duration_buckets") or [])
                ),
                motion_intensity_bucket=str(
                    entry.get("motion_intensity_bucket") or "low"
                ),
                compatible_with=tuple(entry.get("compatible_with") or ()),
                deprecated=False,
            )
        )
    return out


def _load_intent_catalog_from_path(yaml_path: Path) -> list[IntentEntry]:
    """test fixture から直接 yaml を読み込むための legacy 経路。"""

    if not yaml_path.exists():
        logger.warning("[intent] visual_intents.yaml not found: %s", yaml_path)
        return []

    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("[intent] pyyaml not installed")
        return []

    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as e:
        logger.warning("[intent] yaml parse error: %s", e)
        return []

    out: list[IntentEntry] = []
    for entry in (data or {}).get("parts") or []:
        if not isinstance(entry, dict):
            continue
        eid = entry.get("id")
        if not isinstance(eid, str):
            continue
        if entry.get("deprecated"):
            continue
        out.append(
            IntentEntry(
                id=eid,
                description=str(entry.get("description") or ""),
                valid_start_emotions=tuple(
                    entry.get("valid_start_emotions") or ()
                ),
                duration_buckets=tuple(
                    int(d) for d in (entry.get("duration_buckets") or [])
                ),
                motion_intensity_bucket=str(
                    entry.get("motion_intensity_bucket") or "low"
                ),
                compatible_with=tuple(entry.get("compatible_with") or ()),
                deprecated=False,
            )
        )
    return out


def format_catalog_for_prompt(catalog: list[IntentEntry]) -> str:
    """catalog を Claude prompt 注入用テキストにする。

    出力形式:
      Available visual intents:
        - talking_head_calm (start_emotion=中立/喜び/..., duration=5/10, motion=low)
          Subject stands or sits, faces camera, talks calmly. ...
        - reaction_surprise ...
    """

    if not catalog:
        return "Available visual intents: (none defined)"
    lines = ["Available visual intents:"]
    for entry in catalog:
        lines.append(entry.to_prompt_line())
    return "\n".join(lines)


# ───────────── Claude 出力のパース ─────────────


def parse_intent_assignment(
    raw: Any, catalog: list[IntentEntry] | None = None
) -> list[SceneIntentAssignment]:
    """Claude の JSON 出力を SceneIntentAssignment のリストに正規化する。

    期待する形:
      [
        {"scene_idx": 0, "visual_intent_id": "talking_head_calm",
         "confidence": 0.92, "start_emotion": "中立", "duration_bucket": 5,
         "motion_intensity": "low", "rationale": "..."},
        {"scene_idx": 1, "visual_intent_id": null, "confidence": 0.4,
         "rationale": "no good match — subject is gardening"},
      ]

    catalog が渡されたら、未知の visual_intent_id は None に降格 (= free-text
    fallback)。
    """

    if not isinstance(raw, list):
        logger.warning("[intent] parse: top-level not a list (%s)", type(raw))
        return []

    valid_ids: set[str] | None = None
    if catalog is not None:
        valid_ids = {e.id for e in catalog}

    out: list[SceneIntentAssignment] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        s_idx = entry.get("scene_idx")
        conf = entry.get("confidence")
        if not isinstance(s_idx, int) or not isinstance(conf, (int, float)):
            continue
        intent_id = entry.get("visual_intent_id")
        if intent_id is not None and not isinstance(intent_id, str):
            intent_id = None
        if (
            intent_id is not None
            and valid_ids is not None
            and intent_id not in valid_ids
        ):
            logger.info(
                "[intent] scene %d: unknown intent_id '%s' demoted to None",
                s_idx,
                intent_id,
            )
            intent_id = None
        out.append(
            SceneIntentAssignment(
                scene_idx=s_idx,
                visual_intent_id=intent_id,
                confidence=float(conf),
                start_emotion=_str_or_none(entry.get("start_emotion")),
                duration_bucket=_int_or_none(entry.get("duration_bucket")),
                motion_intensity=_str_or_none(entry.get("motion_intensity")),
                rationale=_str_or_none(entry.get("rationale")),
            )
        )
    return out


def _str_or_none(v: Any) -> str | None:
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _int_or_none(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    return None


# ───────────── novel intent 検出 ─────────────


def detect_novel_intent_candidates(
    assignments: list[SceneIntentAssignment],
    min_streak: int = 2,
) -> list[NovelIntentCandidate]:
    """confidence 低 (= visual_intent_id=None) が `min_streak` 件以上連続するシーン
    群から「新規 intent 候補」を抽出する。

    rationale が共通している (= テキスト類似度高い) と「同じ unmet need」と
    判定したいが、本実装では単に「連続区間ごとに 1 候補」を返す簡易版。
    Claude prompt 側で `proposed_intent_id` を含めて返してもらえば
    そのまま採用できる構造。
    """

    candidates: list[NovelIntentCandidate] = []
    streak: list[SceneIntentAssignment] = []

    def flush() -> None:
        if len(streak) >= min_streak:
            indices = tuple(a.scene_idx for a in streak)
            descriptions = [a.rationale or "" for a in streak if a.rationale]
            description = (
                descriptions[0] if descriptions else "(rationale なし)"
            )
            # 仮 id = first rationale から短縮形を作る (= 運用者がリネームする)
            proposed = (
                "proposed_"
                + (
                    description[:24]
                    .replace(" ", "_")
                    .replace(",", "")
                    .replace("/", "")
                    .lower()
                    or f"intent_scene_{indices[0]}"
                )
            )
            candidates.append(
                NovelIntentCandidate(
                    proposed_id=proposed,
                    description=description,
                    scene_indices=indices,
                    rationale=(
                        f"{len(indices)} consecutive scenes had no good "
                        "match in the existing intent catalog"
                    ),
                )
            )

    for a in assignments:
        if a.visual_intent_id is None:
            streak.append(a)
        else:
            flush()
            streak = []
    flush()
    return candidates
