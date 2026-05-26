import config
from stages.prompts import augment_animation_prompt


def test_settle_pct_follows_frontload_ratio(monkeypatch):
    monkeypatch.setattr(config, "ACTION_FRONTLOAD_RATIO", 0.85)
    out = augment_animation_prompt("subject walks to desk", 5.0)
    assert "first 85% of the clip" in out
    assert "hold the final" in out


def test_settle_pct_changes_with_ratio(monkeypatch):
    monkeypatch.setattr(config, "ACTION_FRONTLOAD_RATIO", 0.7)
    out = augment_animation_prompt("subject walks to desk", 5.0)
    assert "first 70% of the clip" in out


def test_augment_is_idempotent(monkeypatch):
    monkeypatch.setattr(config, "ACTION_FRONTLOAD_RATIO", 0.85)
    once = augment_animation_prompt("subject walks to desk", 5.0)
    twice = augment_animation_prompt(once, 5.0)
    assert once == twice


def test_negative_constraint_appended_once(monkeypatch):
    monkeypatch.setattr(config, "KLING_NEGATIVE_CONSTRAINT", "no on-screen text")
    out = augment_animation_prompt("subject walks", 5.0)
    assert out.count("no on-screen text") == 1
    twice = augment_animation_prompt(out, 5.0)
    assert twice.count("no on-screen text") == 1
