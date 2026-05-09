"""Phase 3: prompt_injector の文字列組み立てテスト。"""
from __future__ import annotations



def test_baseline_returns_base_unchanged(monkeypatch):
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "baseline")
    from improvement.prompt_injector import compose_instructions
    assert compose_instructions(None, base="hello") == "hello"
    assert compose_instructions(None) is None


def test_summary_empty_when_no_data(monkeypatch):
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "shadow")
    monkeypatch.setattr("improvement.prompt_injector.axis_performance",
                        type("M", (), {
                            "reward_history_for_axis":
                                staticmethod(lambda axis, **_: []),
                        }))
    from improvement.prompt_injector import build_performance_summary
    assert build_performance_summary() == ""


def test_summary_lists_top_3(monkeypatch):
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "shadow")
    monkeypatch.setattr("config.BANDIT_AXES", ("hook_type",))

    def fake_history(axis, **_):
        if axis == "hook_type":
            return [("結論先出し", 0.6), ("共感型", 0.4),
                    ("問題提起", 0.3), ("結論先出し", 0.7)]
        return []
    monkeypatch.setattr(
        "improvement.prompt_injector.axis_performance",
        type("M", (), {"reward_history_for_axis": staticmethod(fake_history)}),
    )
    from improvement.prompt_injector import build_performance_summary
    out = build_performance_summary(top_n=3)
    assert "hook_type" in out
    # 結論先出しは平均 0.65 でトップ
    assert "結論先出し" in out
    assert out.find("結論先出し") < out.find("共感型")


def test_compose_instructions_active_strategy_includes_directive(monkeypatch):
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "active")
    monkeypatch.setattr("config.BANDIT_AXES", ())
    from improvement.prompt_injector import compose_instructions
    out = compose_instructions(
        {"hook_type": ("問題提起", "explore")},
        base="台本指示",
    )
    assert "台本指示" in out
    assert "問題提起" in out
    assert "意図的 exploration" in out


def test_compose_instructions_shadow_skips_directive(monkeypatch):
    """shadow では bandit 選択は記録するが prompt には載せない。"""
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "shadow")
    monkeypatch.setattr("config.BANDIT_AXES", ())
    from improvement.prompt_injector import compose_instructions
    out = compose_instructions({"hook_type": ("問題提起", "explore")})
    # exploration directive は出ない (active 限定)
    assert out is None or "問題提起" not in out


def test_active_directive_marks_explore_and_exploit(monkeypatch):
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "active")
    monkeypatch.setattr("config.BANDIT_AXES", ())
    from improvement.prompt_injector import build_exploration_directive
    out = build_exploration_directive({
        "hook_type": ("結論先出し", "exploit"),
        "tone": ("カジュアル", "explore"),
    })
    assert "historical best" in out
    assert "意図的 exploration" in out


def test_summary_format_uses_percent_for_completion(monkeypatch):
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "shadow")
    monkeypatch.setattr("config.BANDIT_AXES", ("hook_type",))

    def fake_history(axis, **_):
        return [("結論先出し", 0.65)] if axis == "hook_type" else []
    monkeypatch.setattr(
        "improvement.prompt_injector.axis_performance",
        type("M", (), {"reward_history_for_axis": staticmethod(fake_history)}),
    )
    from improvement.prompt_injector import build_performance_summary
    out = build_performance_summary(metric="avg_completion")
    assert "65.0%" in out
    assert "avg completion rate" in out


def test_summary_format_uses_count_for_views(monkeypatch):
    """avg_views は raw count なので "%" 表示は誤り。整数表示にする。"""
    monkeypatch.setattr("config.IMPROVEMENT_STRATEGY", "shadow")
    monkeypatch.setattr("config.BANDIT_AXES", ("hook_type",))

    def fake_history(axis, **_):
        return [("結論先出し", 12345.0)] if axis == "hook_type" else []
    monkeypatch.setattr(
        "improvement.prompt_injector.axis_performance",
        type("M", (), {"reward_history_for_axis": staticmethod(fake_history)}),
    )
    from improvement.prompt_injector import build_performance_summary
    out = build_performance_summary(metric="avg_views")
    assert "12,345" in out
    assert "%" not in out
    assert "avg views" in out
