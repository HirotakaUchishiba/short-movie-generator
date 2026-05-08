"""Phase 3: closed-loop 改善ロジック (= バンディット選択 + prompt 注入)。

責務分離:

  - ``improvement.bandit``         ε-greedy のアルゴリズムだけ (DB / config 非依存)
  - ``improvement.axis_performance`` v_axis_performance を読む helper
  - ``improvement.prompt_injector`` Claude system prompt 用の文字列組み立て
  - ``improvement.strategy``       IMPROVEMENT_STRATEGY を読み bandit を組み合わせる

auto_loop からは ``strategy.select_assignments_for_video()`` と
``strategy.record_assignments(video_id, assignments)`` だけ呼べば全経路が動く。
"""
from improvement.bandit import EpsilonGreedyBandit

__all__ = ["EpsilonGreedyBandit"]
