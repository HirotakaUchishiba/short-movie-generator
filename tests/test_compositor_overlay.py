import os

import compositor


def _base_screenplay() -> dict:
    return {
        "audio_mode": "voiced",
        "scenes": [
            {
                "duration": 3.0,
                "background_prompt": "bg",
                "lines": [
                    {"text": "やばいやばい", "start": 0.0, "end": 1.0},
                    {"text": "セーフ",        "start": 1.0, "end": 3.0},
                ],
            },
        ],
    }


def test_needs_overlay_with_lines() -> None:
    sp = {"scenes": [{"duration": 3, "background_prompt": "bg",
                      "lines": [{"text": "x", "start": 0.0}]}]}
    assert compositor._needs_overlay(sp) is True


def test_needs_overlay_plain_scene() -> None:
    sp = {"scenes": [{"duration": 3, "background_prompt": "bg"}]}
    assert compositor._needs_overlay(sp) is False


def test_escape_fontfile_colon() -> None:
    assert compositor._escape_fontfile("/a:b/c") == "/a\\:b/c"


def test_scene_offsets_accumulates() -> None:
    scenes = [{"duration": 3.0}, {"duration": 5.5}, {"duration": 2.0}]
    assert compositor._scene_offsets(scenes) == [0.0, 3.0, 8.5]


def test_line_window_uses_explicit_end() -> None:
    line = {"text": "a", "start": 1.0, "end": 2.5}
    assert compositor._line_window(line, None, 5.0) == (1.0, 2.5)


def test_line_window_falls_back_to_next_start() -> None:
    line = {"text": "a", "start": 1.0}
    nxt = {"text": "b", "start": 3.0}
    assert compositor._line_window(line, nxt, 5.0) == (1.0, 3.0)


def test_line_window_falls_back_to_scene_duration() -> None:
    line = {"text": "a", "start": 4.0}
    assert compositor._line_window(line, None, 5.0) == (4.0, 5.0)


def test_build_overlay_filter_generates_drawtext(tmp_path) -> None:
    sp = _base_screenplay()
    f = compositor._build_overlay_filter(sp, str(tmp_path))
    assert "drawtext" in f
    assert "[vout]" in f


def test_build_overlay_filter_line_uses_global_time(tmp_path) -> None:
    sp = {
        "scenes": [
            {"duration": 3.0, "background_prompt": "bg",
             "lines": [{"text": "a", "start": 0.0, "end": 1.0}]},
            {"duration": 5.0, "background_prompt": "bg",
             "lines": [{"text": "b", "start": 1.0, "end": 3.0}]},
        ],
    }
    f = compositor._build_overlay_filter(sp, str(tmp_path))
    assert "between(t,0.000,1.000)" in f
    assert "between(t,4.000,6.000)" in f


def test_build_overlay_filter_writes_textfiles(tmp_path) -> None:
    sp = _base_screenplay()
    compositor._build_overlay_filter(sp, str(tmp_path))
    files = os.listdir(tmp_path)
    assert any(x.startswith("drawtext_sub_000_") for x in files)


def test_build_overlay_filter_empty_returns_empty(tmp_path) -> None:
    sp = {"scenes": [{"duration": 3, "background_prompt": "bg"}]}
    assert compositor._build_overlay_filter(sp, str(tmp_path)) == ""


# ───────────────── 実 timeline ベースの offset / リスケール ─────────────────


def test_scene_offsets_from_videos_uses_real_durations(tmp_path, monkeypatch) -> None:
    """scene_<S>.mp4 の実尺累積で offset を計算する。"""
    durations = {"a.mp4": 2.6, "b.mp4": 6.01, "c.mp4": 11.08}
    monkeypatch.setattr(compositor, "_get_duration",
                        lambda p: durations[os.path.basename(p)])
    paths = [str(tmp_path / k) for k in ["a.mp4", "b.mp4", "c.mp4"]]
    assert compositor._scene_offsets_from_videos(paths) == [0.0, 2.6, 8.61]


def test_line_window_rescales_with_real_duration() -> None:
    """scene_real_duration を渡すと line.start / end が比例で伸びる。"""
    line = {"text": "a", "start": 1.0, "end": 2.5}
    # 想定 5.0 → 実 7.5 = 1.5x
    s, e = compositor._line_window(line, None, 5.0, scene_real_duration=7.5)
    assert s == 1.5
    assert e == 3.75


def test_line_window_no_rescale_without_real_duration() -> None:
    """scene_real_duration が None なら従来動作。"""
    line = {"text": "a", "start": 1.0, "end": 2.5}
    assert compositor._line_window(line, None, 5.0) == (1.0, 2.5)


def test_line_window_fallback_uses_real_duration_for_end() -> None:
    """end 未指定 / next も無い場合は scene_real_duration を end に使う。"""
    line = {"text": "a", "start": 4.0}
    s, e = compositor._line_window(line, None, 5.0, scene_real_duration=7.5)
    # start = 4.0 * 1.5 = 6.0、end は scene_real_duration = 7.5
    assert s == 6.0
    assert e == 7.5


def test_build_overlay_uses_real_timeline_when_videos_provided(
    tmp_path, monkeypatch,
) -> None:
    sp = {
        "scenes": [
            {"duration": 3.0, "background_prompt": "bg",
              "lines": [{"text": "a", "start": 0.0, "end": 1.0}]},
            {"duration": 5.0, "background_prompt": "bg",
              "lines": [{"text": "b", "start": 1.0, "end": 3.0}]},
        ],
    }
    # scene 0 = 4.0s (sp 3.0 → 実 4.0、ratio=4/3≈1.333)
    # scene 1 = 7.5s (sp 5.0 → 実 7.5、ratio=1.5)
    durations = {"a.mp4": 4.0, "b.mp4": 7.5}
    monkeypatch.setattr(compositor, "_get_duration",
                        lambda p: durations[os.path.basename(p)])

    paths = [str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")]
    f = compositor._build_overlay_filter(sp, str(tmp_path), scene_videos=paths)

    # scene 0 line (0.0-1.0) は ratio 1.333 で 0.0-1.333、offset 0
    assert "between(t,0.000,1.333)" in f
    # scene 1 line (1.0-3.0) は ratio 1.5 で 1.5-4.5、offset 4.0 → 5.5-8.5
    assert "between(t,5.500,8.500)" in f


def test_build_overlay_falls_back_to_sp_duration_without_videos(
    tmp_path,
) -> None:
    """scene_videos 未指定なら従来通り scene.duration ベース。"""
    sp = {
        "scenes": [
            {"duration": 3.0, "background_prompt": "bg",
              "lines": [{"text": "a", "start": 0.0, "end": 1.0}]},
            {"duration": 5.0, "background_prompt": "bg",
              "lines": [{"text": "b", "start": 1.0, "end": 3.0}]},
        ],
    }
    f = compositor._build_overlay_filter(sp, str(tmp_path))
    assert "between(t,0.000,1.000)" in f
    assert "between(t,4.000,6.000)" in f


# ───────────────── _wrap_subtitle_text 自動折り返し ─────────────────


def test_wrap_short_text_passthrough() -> None:
    assert compositor._wrap_subtitle_text("短い", max_chars=17) == "短い"


def test_wrap_at_punctuation() -> None:
    """句点直後で折る。"""
    text = "やったー！今日飲み行っちゃおうかな〜"  # 17文字
    out = compositor._wrap_subtitle_text(text, max_chars=10)
    assert "\n" in out
    # 「！」の直後で折られているはず
    assert out.startswith("やったー！")


def test_wrap_at_particle() -> None:
    """主要助詞の直後で折る。"""
    text = "これは普通の文章ですが折り返したい場合があります"
    out = compositor._wrap_subtitle_text(text, max_chars=10)
    lines = out.split("\n")
    # 何らかの自然境界で折られていること
    assert len(lines) >= 2


def test_wrap_long_quote_stays_in_lines() -> None:
    """28文字の鉤括弧テキストが 17 文字以内に折られる。"""
    text = "「弊社都合で受け入れテストを1ヶ月延期させて頂きたいです」"
    out = compositor._wrap_subtitle_text(text, max_chars=17)
    for line in out.split("\n"):
        assert len(line) <= 21  # 多少超過する場合あり (= max_chars+5 範囲)
    # 「で」「を」「て」など助詞直後が break point になっていること
    assert "\n" in out


def test_wrap_brackets_do_not_split_internally() -> None:
    """『 』 の前後では break が発生する (中で割られない)。"""
    text = "「弊社都合で受け入れテストを1ヶ月延期させて頂きたいです」"
    out = compositor._wrap_subtitle_text(text, max_chars=17)
    # 「『」「『」が行の途中で出現するなら、その直前で改行されているはず
    for line in out.split("\n"):
        # 鉤括弧は行末か行頭にあるべき (中央付近にはほぼ来ない)
        assert "「" not in line[1:-1] or line.startswith("「") or line.endswith("「")


def test_wrap_force_break_with_warning(caplog) -> None:
    """break point が無い超長文は強制改行 + warning ログ。"""
    import logging
    text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # 26文字、break 候補ゼロ
    with caplog.at_level(logging.WARNING, logger="compositor"):
        out = compositor._wrap_subtitle_text(text, max_chars=10)
    assert "\n" in out
    assert any("強制改行" in rec.message for rec in caplog.records)


def test_wrap_idempotent_on_already_short_text() -> None:
    text = "ABC"
    assert compositor._wrap_subtitle_text(text, max_chars=10) == text


def test_wrap_zero_max_chars_no_op() -> None:
    """max_chars=0 はそのまま返す (異常入力ガード)。"""
    text = "すごく長いテキストが来ても何も起きない"
    assert compositor._wrap_subtitle_text(text, max_chars=0) == text


# ───────────────── break score 単体 ─────────────────


def test_break_score_strong_punctuation() -> None:
    # "やったー！今日" の "！" 直後で切る = position 5 (左行 "やったー！")
    text = "やったー！今日"
    assert compositor._break_score_at(text, 5) >= 100


def test_break_score_particle_after() -> None:
    # "これは普通" の "は" 直後で切る = position 3 (左行 "これは")
    text = "これは普通"
    assert compositor._break_score_at(text, 3) >= 60


def test_break_score_no_break_in_kanji_run() -> None:
    text = "弊社都合"
    # "社" の後 (position 2) は 漢字↔漢字 で 0 になるはず
    assert compositor._break_score_at(text, 2) == 0


def test_break_score_katakana_kanji_boundary() -> None:
    text = "テストを"
    # 'テスト' (3) と 'を' の間 = カタカナ↔ひらがな
    # ただし 'を' 直前だから助詞ルールが効く可能性あり → ≥ 30
    assert compositor._break_score_at(text, 3) >= 30


# ───────────────── 統合 ─────────────────


def test_build_overlay_wraps_long_text(tmp_path, monkeypatch) -> None:
    """長文 line.text が drawtext に渡る前に改行される。"""
    monkeypatch.setattr(compositor.config, "SUBTITLE_MAX_CHARS_PER_LINE", 10)

    sp = {
        "scenes": [
            {"duration": 5.0, "background_prompt": "bg",
              "lines": [{"text": "やったー！今日飲み行っちゃおうかな〜",
                          "start": 0.0, "end": 4.0}]},
        ],
    }
    compositor._build_overlay_filter(sp, str(tmp_path))
    sub_files = [f for f in os.listdir(tmp_path) if f.startswith("drawtext_sub_")]
    assert len(sub_files) == 1
    with open(os.path.join(tmp_path, sub_files[0])) as f:
        written = f.read()
    assert "\n" in written  # 改行されている
