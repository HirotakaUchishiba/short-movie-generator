"""Phase 3: ε-greedy バンディット (= DB / config 非依存の純粋アルゴリズム)。

軸 (= hook_type / tone / dominant_emotion / theme) ごとに独立した instance を
持つ想定。サンプル ≥ 200 で Thompson sampling に切替検討するのは Phase 3.5
以降。

並列実行時の注意:
    instance は in-memory state のみ持ち永続化しない。複数プロセスで同時に
    `select` を呼ぶ場合、それぞれが独立して同じ history を見て同じ exploit
    arm を選びうる (= 並列度が高いと exploration が偏る)。期待値ベースでは
    正しく動くため、シングルマシン cron 程度ならば問題ない。
"""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable


@dataclass
class ArmStats:
    """1 つの値 (= bandit arm) の累積統計。"""
    pulls: int = 0
    total_reward: float = 0.0

    @property
    def mean(self) -> float:
        return self.total_reward / self.pulls if self.pulls else 0.0


class EpsilonGreedyBandit:
    """ε-greedy 選択器。

    ``select(candidates)`` は ``(value, sub_strategy)`` を返す。
    ``sub_strategy`` は ``"explore"`` (= random) / ``"exploit"`` (= 平均最大)。
    """

    def __init__(self, epsilon: float = 0.2,
                 rng: random.Random | None = None) -> None:
        if not 0.0 <= epsilon <= 1.0:
            raise ValueError(f"epsilon must be in [0, 1]: {epsilon}")
        self.epsilon = epsilon
        self.rng = rng or random.Random()
        self.stats: dict[str, ArmStats] = defaultdict(ArmStats)

    def update(self, value: str, reward: float) -> None:
        s = self.stats[value]
        s.pulls += 1
        s.total_reward += float(reward)

    def from_history(self, history: Iterable[tuple[str, float]]) -> None:
        for value, reward in history:
            self.update(value, reward)

    def select(self, candidates: list[str]) -> tuple[str, str]:
        if not candidates:
            raise ValueError("candidates must not be empty")
        if self.rng.random() < self.epsilon:
            return self.rng.choice(candidates), "explore"
        # exploit: 平均 reward 最大。同点は rng で公平に tie-break する
        # (= 旧版は先頭優先で、cold-start arm すべて mean=0 のとき insertion-first
        # に固定的に偏っていた)。
        means = [self.stats.get(v, ArmStats()).mean for v in candidates]
        best_mean = max(means)
        tied = [v for v, m in zip(candidates, means) if m == best_mean]
        if len(tied) == 1:
            return tied[0], "exploit"
        return self.rng.choice(tied), "exploit"

    def snapshot(self) -> dict[str, dict[str, float]]:
        """現在の各 arm の累積を dict で返す (= debug / persist 用)。"""
        return {
            v: {"pulls": float(s.pulls), "total_reward": s.total_reward,
                "mean": s.mean}
            for v, s in self.stats.items()
        }
