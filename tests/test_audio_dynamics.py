"""audio_dynamics の単体テスト (ffmpeg/librosa は mock)。"""


import audio_dynamics


def test_classify_intensity_thresholds() -> None:
    assert audio_dynamics._classify_intensity(0.10) == "weak"
    assert audio_dynamics._classify_intensity(0.40) == "moderate"
    assert audio_dynamics._classify_intensity(0.60) == "strong"


def test_classify_speed_by_char_per_sec() -> None:
    # 6字で 2秒 = 3 cps → slow
    assert audio_dynamics._classify_speed("やばいかな", 2.0) == "slow"
    # 6字で 1秒 = 6 cps → medium
    assert audio_dynamics._classify_speed("やばいかな", 1.0) == "medium"
    # 10字で 1秒 = 10 cps → fast
    assert audio_dynamics._classify_speed("やばいやばい寝過ぎた", 1.0) == "fast"


def test_classify_speed_handles_zero_duration() -> None:
    assert audio_dynamics._classify_speed("abc", 0) == "medium"


def test_extract_line_dynamics_returns_empty_when_missing(tmp_path) -> None:
    path = str(tmp_path / "not_exist.mp3")
    assert audio_dynamics.extract_line_dynamics(path, "text") == {}


def test_extract_line_dynamics_combines_classifications(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "a.mp3"
    audio_path.write_bytes(b"x")

    monkeypatch.setattr(audio_dynamics, "_ffprobe_duration", lambda p: 1.5)

    fake_feats = {"pitch_trend": "rising", "rms_peak": 0.65}

    import audio_features
    monkeypatch.setattr(audio_features, "extract_phrase_features",
                          lambda p, s, e: fake_feats)
    monkeypatch.setattr(audio_dynamics, "_classify_silence_pattern",
                          lambda p, d: "fluent")

    out = audio_dynamics.extract_line_dynamics(str(audio_path), "やばい寝過ぎ")
    assert out["intensity"] == "strong"   # rms 0.65
    assert out["pitch_trend"] == "rising"
    assert out["silence_pattern"] == "fluent"
    # 6字 / 1.5s = 4 cps → medium 境界
    assert out["speed"] in ("slow", "medium")


def test_summarize_scene_dynamics_skips_missing_files(tmp_path, monkeypatch) -> None:
    # 1 line目のファイルだけ存在
    (tmp_path / "tts_000_000.mp3").write_bytes(b"x")

    monkeypatch.setattr(audio_dynamics, "extract_line_dynamics",
                          lambda p, t: {"intensity": "moderate", "speed": "fast",
                                        "pitch_trend": "flat", "silence_pattern": "fluent",
                                        "duration": 1.0})

    lines = [{"text": "a"}, {"text": "b"}]
    out = audio_dynamics.summarize_scene_dynamics(lines, str(tmp_path), 0)
    assert "line0" in out
    assert "line1" not in out  # ファイル無し
    assert "moderate fast flat fluent" in out


def test_summarize_scene_dynamics_returns_empty_when_no_files(tmp_path) -> None:
    out = audio_dynamics.summarize_scene_dynamics([{"text": "a"}], str(tmp_path), 0)
    assert out == ""
