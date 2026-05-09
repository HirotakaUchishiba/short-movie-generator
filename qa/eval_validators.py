"""Phase 2: validator の recall / precision を週次で評価する。

直近 N 日の ``qa_failures`` を読み、各 tag について
    - ``human_reject`` (= 人間が NG とした)
    - ``auto_flagged`` (= validator が NG とした)
の重なりから recall / precision を計算する。

人間 reject はあるが auto は捕まえていない → recall 低 (= しきい値が緩い)
人間 OK だが auto が NG にした → precision 低 (= しきい値が厳しい)

週次集計を ``data/validator_eval/<YYYY-Wxx>.json`` に書き出し、運用者が
しきい値調整するための判断材料にする (= 自動チューニングは Phase 3 以降)。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __name__ == "__main__":
    SCRIPT_DIR = Path(__file__).resolve().parent
    ROOT = SCRIPT_DIR.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from analytics import db  # noqa: E402

logger = logging.getLogger(__name__)


def _eval_dir() -> Path:
    return Path(config.BASE_DIR) / "data" / "validator_eval"


def load_recent_failures(days: int = 30) -> list[dict]:
    """直近 ``days`` 日の qa_failures を返す。tags は JSON deserialize 済み。"""
    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    since_sql = since_dt.strftime("%Y-%m-%d %H:%M:%S")
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM qa_failures WHERE created_at >= ? ORDER BY id",
            (since_sql,),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        try:
            d["tags"] = json.loads(d.get("tags") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
        out.append(d)
    return out


def evaluate_per_tag(failures: list[dict]) -> dict[str, dict[str, float]]:
    """tag 別に human / auto / both 件数 + recall / precision を集計する。"""
    by_tag: dict[str, dict[str, set]] = defaultdict(
        lambda: {"human": set(), "auto": set()},
    )
    for f in failures:
        key = (f["ts"], f.get("scene_idx"), f.get("line_idx"))
        for tag in f.get("tags") or []:
            if f.get("source") == "human_reject":
                by_tag[tag]["human"].add(key)
            elif f.get("source") == "auto_flagged":
                by_tag[tag]["auto"].add(key)

    out: dict[str, dict[str, float]] = {}
    for tag, sets in by_tag.items():
        h = sets["human"]
        a = sets["auto"]
        both = h & a
        recall = (len(both) / len(h)) if h else 0.0
        precision = (len(both) / len(a)) if a else 0.0
        out[tag] = {
            "human_reject": float(len(h)),
            "auto_flagged": float(len(a)),
            "both": float(len(both)),
            "recall": recall,
            "precision": precision,
        }
    return out


def run_eval(days: int = 30) -> dict:
    """直近 ``days`` 日の評価を実行し、結果を dict + ファイルに書き出す。"""
    failures = load_recent_failures(days=days)
    per_tag = evaluate_per_tag(failures)
    summary = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_days": days,
        "total_failures": len(failures),
        "per_tag": per_tag,
    }
    out_dir = _eval_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    week = datetime.now(timezone.utc).strftime("%G-W%V")
    out_path = out_dir / f"{week}.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info("[eval] wrote %s (tags=%d)", out_path, len(per_tag))
    return summary


def main() -> int:
    import log_setup
    log_setup.setup()
    parser = argparse.ArgumentParser(prog="eval_validators")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    summary = run_eval(days=args.days)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
