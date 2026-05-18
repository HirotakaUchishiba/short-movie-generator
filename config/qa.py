"""自動 QA validator / bandit / human gate の設定 (= Phase 2-4 制御群)。

config/__init__.py から段階分割 (= §3.1.4-b)。validator の on/off と
bandit 戦略の切替、publish 直前の human gate を 1 箇所にまとめる。
"""

import os
import warnings as _warnings

# ───────────── Phase 2: 自動 QA Validator ─────────────
# 全 validator のグローバル on/off (= 緊急時 / Phase 1 状態に戻す kill-switch)。
QA_VALIDATORS_ENABLED = os.getenv("QA_VALIDATORS_ENABLED", "1") in ("1", "true", "True")

# 個別 validator を無効化する。 ":" / "," 区切りで複数指定可。
# 例: "lipsync_quality,character_drift" → ML 依存の重量級 2 つだけ skip
_blacklist_raw = os.getenv("QA_VALIDATOR_BLACKLIST", "")
QA_VALIDATOR_BLACKLIST: tuple[str, ...] = tuple(
    s.strip() for s in _blacklist_raw.replace(":", ",").split(",")
    if s.strip()
)

# stage ごとの retry 上限 (= validator NG が続いた場合に手放す回数)。
# Phase 1 の暫定 validator は全 stage 1 だったが、Phase 2 で stage 別に
# コスト / 改善余地のバランスを取る。
QA_RETRY_LIMITS: dict[str, int] = {
    "tts": 2,
    "bg": 2,
    "kling": 3,
    "scene": 2,
    "overlay": 1,
}

# ───────────── Phase 3: Closed-loop 改善 ─────────────
# baseline: バンディット完全無効。Phase 2 までの挙動。
# shadow:   バンディットの選択を experiment_assignments に記録するだけ
#           (= prompt 注入はしない、効果評価期間)。
# active:   バンディットの選択を analyze の instructions に注入する
#           (= 本番実験)。
VALID_IMPROVEMENT_STRATEGIES: tuple[str, ...] = ("baseline", "shadow", "active")
_raw_improvement_strategy = os.getenv("IMPROVEMENT_STRATEGY", "baseline")
if _raw_improvement_strategy in VALID_IMPROVEMENT_STRATEGIES:
    IMPROVEMENT_STRATEGY = _raw_improvement_strategy
else:
    _warnings.warn(
        f"IMPROVEMENT_STRATEGY={_raw_improvement_strategy!r} is invalid "
        f"(valid: {VALID_IMPROVEMENT_STRATEGIES}). "
        "Falling back to 'baseline'.",
        RuntimeWarning, stacklevel=2,
    )
    IMPROVEMENT_STRATEGY = "baseline"

# ε-greedy の exploration 確率。0.2 = 20% random、80% historical best。
BANDIT_EPSILON = float(os.getenv("BANDIT_EPSILON", "0.2"))

# 各軸ごとの reward 履歴を独立に管理する対象。
# 順序の変更 / 追加は v_axis_performance の SELECT 列とも整合させること。
BANDIT_AXES: tuple[str, ...] = (
    "hook_type", "tone", "dominant_emotion", "theme",
)

# ───────────── Phase 4: 本番展開 ─────────────
# True (= 既定): publish 直前に人手承認を要求する (= 半自動運用)
# False: 完全自動 (= cron で publish まで通る、本番アカウントへの直撃含む)
# 注: AUTO_LOOP_ALLOW_PUBLIC=0 の間は public 公開が unlisted に降格されるので、
# このフラグを False にしても public 暴発は二重防衛で抑止される。
PRODUCTION_HUMAN_GATE_ENABLED = os.getenv(
    "PRODUCTION_HUMAN_GATE_ENABLED", "1",
) in ("1", "true", "True")
