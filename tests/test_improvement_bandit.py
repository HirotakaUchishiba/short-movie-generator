"""Phase 3: ε-greedy バンディットの単体テスト (= DB / config 非依存)。"""
from __future__ import annotations

import random

import pytest

from improvement.bandit import EpsilonGreedyBandit


def test_invalid_epsilon_rejected():
    with pytest.raises(ValueError):
        EpsilonGreedyBandit(epsilon=1.5)
    with pytest.raises(ValueError):
        EpsilonGreedyBandit(epsilon=-0.1)


def test_select_explore_when_random_is_below_epsilon():
    """rng.random() が epsilon 未満 → explore (= random choice)。"""
    rng = random.Random()
    rng.random = lambda: 0.0  # 必ず explore
    rng.choice = lambda seq: seq[-1]  # 末尾を選ぶ
    bandit = EpsilonGreedyBandit(epsilon=0.5, rng=rng)
    bandit.update("a", 1.0)  # exploit なら "a" を選ぶ stats
    value, sub = bandit.select(["a", "b", "c"])
    assert sub == "explore"
    assert value == "c"


def test_select_exploit_when_random_above_epsilon():
    rng = random.Random()
    rng.random = lambda: 0.99  # 必ず exploit
    bandit = EpsilonGreedyBandit(epsilon=0.5, rng=rng)
    bandit.update("a", 0.1)
    bandit.update("b", 0.9)
    bandit.update("c", 0.5)
    value, sub = bandit.select(["a", "b", "c"])
    assert sub == "exploit"
    assert value == "b"


def test_exploit_uses_random_tie_break_when_no_history():
    """全 arm の mean が同じ (= cold start) ときは rng で公平に選ぶ。"""
    rng = random.Random()
    rng.random = lambda: 0.99  # 必ず exploit
    rng.choice = lambda seq: seq[1]  # tied 中の 2 番目を選ぶ
    bandit = EpsilonGreedyBandit(epsilon=0.0, rng=rng)
    value, sub = bandit.select(["x", "y", "z"])
    assert sub == "exploit"
    assert value == "y"  # 旧版は先頭固定で "x" だった


def test_exploit_random_tie_break_among_top_arms():
    """history があっても mean が同点なら rng で選ぶ。"""
    rng = random.Random()
    rng.random = lambda: 0.99  # 必ず exploit
    rng.choice = lambda seq: seq[-1]  # tied 末尾
    bandit = EpsilonGreedyBandit(epsilon=0.0, rng=rng)
    bandit.update("a", 0.5)
    bandit.update("b", 0.5)  # a と b が tied
    bandit.update("c", 0.1)  # c は劣等
    value, sub = bandit.select(["a", "b", "c"])
    assert sub == "exploit"
    assert value in {"a", "b"}  # c は選ばれない
    assert value == "b"  # rng.choice([a,b])[-1]


def test_from_history_aggregates_pulls():
    bandit = EpsilonGreedyBandit()
    bandit.from_history([("a", 0.5), ("a", 0.7), ("b", 0.3)])
    snap = bandit.snapshot()
    assert snap["a"]["pulls"] == 2
    assert snap["a"]["mean"] == pytest.approx(0.6)
    assert snap["b"]["mean"] == pytest.approx(0.3)


def test_select_empty_candidates_raises():
    bandit = EpsilonGreedyBandit()
    with pytest.raises(ValueError):
        bandit.select([])
