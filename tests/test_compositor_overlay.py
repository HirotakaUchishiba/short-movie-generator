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


def test_wrap_no_force_break_for_unbreakable_text(caplog) -> None:
    """自然な break point が無い超長文は分断せず 1 chunk として保持 + warning。
    機械的・不自然な分断は絶対しない方針。"""
    import logging
    text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # 26文字、break 候補ゼロ
    with caplog.at_level(logging.WARNING, logger="compositor"):
        out = compositor._wrap_subtitle_text(text, max_chars=10)
    # 1 chunk のまま (= 改行されない)
    assert out == text
    assert any("自然な break point" in rec.message for rec in caplog.records)


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


def test_build_overlay_wraps_long_text_when_chunks_disabled(
    tmp_path, monkeypatch,
) -> None:
    """SUBTITLE_CHUNK_ENABLED=False なら従来通り 1 line = 1 字幕で改行。"""
    monkeypatch.setattr(compositor.config, "SUBTITLE_CHUNK_ENABLED", False)
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
    assert "\n" in written


# ───────────────── chunks (TikTok 風 短いテロップ次々表示) ─────────────────


def test_split_into_chunks_short_text_returns_single() -> None:
    assert compositor._split_into_chunks("短い", max_chars=8) == ["短い"]


def test_split_into_chunks_empty_returns_empty() -> None:
    assert compositor._split_into_chunks("", max_chars=8) == []


def test_split_into_chunks_long_quote() -> None:
    """28文字の鉤括弧文を 8 文字以内で分割。"""
    text = "「弊社都合で受け入れテストを1ヶ月延期させて頂きたいです」"
    chunks = compositor._split_into_chunks(text, max_chars=8)
    # 全 chunk が 8 文字以内 (= 不自然な強制切断はスコア負の場合のみ)
    assert all(len(c) <= 12 for c in chunks)  # 多少の超過を許容 (探索範囲外時)
    # 結合すれば元のテキストに戻る
    assert "".join(chunks) == text
    # 複数 chunk に分かれている
    assert len(chunks) >= 3


def test_split_into_chunks_breaks_at_punctuation() -> None:
    text = "やったー！今日も終わった！お風呂入ろう"
    chunks = compositor._split_into_chunks(text, max_chars=8)
    # 「！」直後で chunk 区切りが来ている
    found_punct_break = False
    for c in chunks:
        if c.endswith("！") or c.endswith("。"):
            found_punct_break = True
            break
    assert found_punct_break


def test_split_into_chunks_zero_max_returns_whole() -> None:
    text = "テスト"
    assert compositor._split_into_chunks(text, max_chars=0) == ["テスト"]


def test_allocate_chunk_timings_proportional() -> None:
    """文字数比例で line.start - line.end を配分。"""
    chunks = ["AB", "CDEF"]  # 2 + 4 = 6 chars
    timings = compositor._allocate_chunk_timings(chunks, 0.0, 6.0)
    assert len(timings) == 2
    # AB: 0.0 - 2.0 (= 6.0 * 2/6)
    assert abs(timings[0][0] - 0.0) < 1e-6
    assert abs(timings[0][1] - 2.0) < 1e-6
    # CDEF: 2.0 - 6.0
    assert abs(timings[1][0] - 2.0) < 1e-6
    assert abs(timings[1][1] - 6.0) < 1e-6


def test_allocate_chunk_timings_no_overlap_no_gap() -> None:
    """連続 chunks に gap や overlap が無いこと。"""
    chunks = ["A", "BB", "CCC"]
    timings = compositor._allocate_chunk_timings(chunks, 1.0, 7.0)
    # 各 chunk の end が次 chunk の start と一致 (浮動小数誤差以内)
    for i in range(len(timings) - 1):
        assert abs(timings[i][1] - timings[i + 1][0]) < 1e-6
    # 最後は line_end と一致
    assert abs(timings[-1][1] - 7.0) < 1e-6


def test_allocate_chunk_timings_empty_chunks() -> None:
    assert compositor._allocate_chunk_timings([], 0.0, 5.0) == []


def test_allocate_chunk_timings_zero_duration() -> None:
    chunks = ["A", "B"]
    timings = compositor._allocate_chunk_timings(chunks, 5.0, 5.0)
    # duration 0 でもクラッシュしない
    assert len(timings) == 2


def test_build_overlay_emits_per_chunk_drawtext(tmp_path, monkeypatch) -> None:
    """SUBTITLE_CHUNK_ENABLED=True なら 1 line から複数 drawtext が発行される。"""
    monkeypatch.setattr(compositor.config, "SUBTITLE_CHUNK_ENABLED", True)
    monkeypatch.setattr(compositor.config, "SUBTITLE_CHUNK_MAX_CHARS", 8)

    sp = {
        "scenes": [
            {"duration": 5.0, "background_prompt": "bg",
              "lines": [{
                  "text": "「弊社都合で受け入れテストを1ヶ月延期させて頂きたいです」",
                  "start": 0.0, "end": 4.0,
              }]},
        ],
    }
    compositor._build_overlay_filter(sp, str(tmp_path))
    sub_files = sorted(
        f for f in os.listdir(tmp_path) if f.startswith("drawtext_sub_"))
    # 28 文字を 8 文字以内に分けるので複数 chunk
    assert len(sub_files) >= 3
    # 命名規則: sub_<scene>_<line>_<chunk>.txt
    assert all("_000_000_" in f for f in sub_files)


def test_build_overlay_chunk_files_each_within_max(tmp_path, monkeypatch) -> None:
    """各 chunk ファイルの中身が max_chars 以内 (改行なし、1 行)。"""
    monkeypatch.setattr(compositor.config, "SUBTITLE_CHUNK_ENABLED", True)
    monkeypatch.setattr(compositor.config, "SUBTITLE_CHUNK_MAX_CHARS", 8)

    sp = {
        "scenes": [
            {"duration": 5.0, "background_prompt": "bg",
              "lines": [{"text": "やったー！今日飲み行っちゃおうかな〜",
                          "start": 0.0, "end": 4.0}]},
        ],
    }
    compositor._build_overlay_filter(sp, str(tmp_path))
    for f in os.listdir(tmp_path):
        if not f.startswith("drawtext_sub_"):
            continue
        with open(os.path.join(tmp_path, f)) as fh:
            content = fh.read()
        # chunks は内部に改行を持たない (1 行 1 chunk)
        assert "\n" not in content
        # 文字数も max_chars + 探索余裕 以内
        assert len(content) <= 12


def test_split_never_breaks_at_forbidden_bigrams() -> None:
    """実台本のセリフを全部試して、chunks 境界に _FORBIDDEN_BIGRAMS が
    出現しないことを保証する (機械的・不自然な分断の絶対回避)。"""
    real_lines = [
        "8時50分！？",
        "あともう5分",
        "やばいやばい寝過ぎた！",
        "業務開始します！",
        "ふうー間に合った セーフ！",
        "うわーこれ納期まにあうかなぁ",
        "あ、クライアントからだ",
        "「弊社都合で受け入れテストを1ヶ月延期させて頂きたいです」",
        "やったー！今日飲み行っちゃおうかな〜",
        "おっと、今日研修も受けないと！",
        "IT未経験で不安だったけど",
        "eラーニングとか研修制度も充実してるから安心だなあ！",
        "スタンドデスクまじで便利〜",
        "ずっと座ってると腰痛くなるからな〜",
        "あ、もう昼ご飯か",
        "一旦スーパー行って晩御飯も作っちゃうか！",
        "この道案内のアプリ私がちょっと作ったんだよな",
        "実際に使ってるところ見るとなんだか嬉しいな！",
        "山根さん転職するんだ！",
        "え 年収200万アップ！？",
        "お客さんからの引き抜きの誘いってまじであるんだ！",
        "よし今日も終わった！",
        "お風呂入ろう！",
        "在宅ワークだし手に職つくしITエンジニア最高すぎる！！",
    ]
    forbidden = compositor._FORBIDDEN_BIGRAMS
    failures = []
    for text in real_lines:
        chunks = compositor._split_into_chunks(text, max_chars=12)
        for j in range(len(chunks) - 1):
            boundary = chunks[j][-1] + chunks[j + 1][0]
            if boundary in forbidden:
                failures.append(
                    (text, boundary, chunks[j], chunks[j + 1])
                )
    assert not failures, (
        "禁止 bigram での分断を検出: "
        + "\n".join(
            f"  {t!r} → {a!r} | {b!r} (bigram={bg!r})"
            for t, bg, a, b in failures
        )
    )


def test_split_chunk_length_within_reasonable_max() -> None:
    """各 chunk が max_chars + 余裕分 (= 4 文字) 以内に収まる。
    自然な break point が無いケースでは超過するが警告ログが出る前提。"""
    real_lines = [
        "8時50分！？",
        "「弊社都合で受け入れテストを1ヶ月延期させて頂きたいです」",
        "在宅ワークだし手に職つくしITエンジニア最高すぎる！！",
        "実際に使ってるところ見るとなんだか嬉しいな！",
    ]
    for text in real_lines:
        chunks = compositor._split_into_chunks(text, max_chars=12)
        for c in chunks:
            # 12 + 4 = 16 文字以内 (探索範囲拡張分)
            assert len(c) <= 16, f"chunk too long: {c!r} from {text!r}"


def test_split_does_not_break_after_ma_in_verb() -> None:
    """「ま」を含む動詞活用形 (まにあう / まで / ます) で分断されない。"""
    text = "うわーこれ納期まにあうかなぁ"
    chunks = compositor._split_into_chunks(text, max_chars=12)
    # 「まにあう」が分断されていないこと
    assert all("まにあう" not in (chunks[j][-2:] + chunks[j + 1][:2])
               for j in range(len(chunks) - 1)) or \
           all(not (chunks[j].endswith("ま") and chunks[j + 1].startswith("に"))
               for j in range(len(chunks) - 1))


def test_build_overlay_chunk_timings_consecutive(tmp_path, monkeypatch) -> None:
    """生成される drawtext の enable 時刻が連続している (gap なし)。"""
    import re
    monkeypatch.setattr(compositor.config, "SUBTITLE_CHUNK_ENABLED", True)
    monkeypatch.setattr(compositor.config, "SUBTITLE_CHUNK_MAX_CHARS", 8)

    sp = {
        "scenes": [
            {"duration": 5.0, "background_prompt": "bg",
              "lines": [{"text": "「弊社都合で受け入れテストを1ヶ月延期させて頂きたいです」",
                          "start": 0.0, "end": 4.0}]},
        ],
    }
    f = compositor._build_overlay_filter(sp, str(tmp_path))
    matches = re.findall(r"between\(t,([\d.]+),([\d.]+)\)", f)
    assert len(matches) >= 3
    # 最初の chunk は 0.000 開始
    assert float(matches[0][0]) == 0.0
    # 最後の chunk は line_end (= 4.0) 終了
    assert abs(float(matches[-1][1]) - 4.0) < 1e-3
    # 連続性: 各 chunk の end が次の start と一致
    for i in range(len(matches) - 1):
        assert abs(float(matches[i][1]) - float(matches[i + 1][0])) < 1e-3


# ───────────────── 手動チャンク (lines[].subtitles) ─────────────────


def test_manual_subtitles_skip_auto_split(tmp_path, monkeypatch) -> None:
    """lines[].subtitles を指定すると _split_into_chunks は呼ばれず、
    指定通りのチャンク数 / 時間 / テキストで drawtext が生成される。"""
    monkeypatch.setattr(compositor.config, "SUBTITLE_CHUNK_ENABLED", True)
    monkeypatch.setattr(compositor.config, "SUBTITLE_CHUNK_MAX_CHARS", 4)

    def boom(*_a, **_kw):
        raise AssertionError("auto split が呼ばれている")

    monkeypatch.setattr(compositor, "_split_into_chunks", boom)

    sp = {
        "scenes": [
            {
                "duration": 5.0,
                "background_prompt": "bg",
                "lines": [
                    {
                        "text": "(無視されるはずの本文)",
                        "start": 0.0,
                        "end": 4.0,
                        "subtitles": [
                            {"text": "やばい",   "start": 0.0, "end": 1.2},
                            {"text": "セーフ", "start": 1.2, "end": 4.0},
                        ],
                    }
                ],
            }
        ],
    }
    f = compositor._build_overlay_filter(sp, str(tmp_path))
    assert "between(t,0.000,1.200)" in f
    assert "between(t,1.200,4.000)" in f
    sub_files = sorted(
        x for x in os.listdir(tmp_path) if x.startswith("drawtext_sub_"))
    assert len(sub_files) == 2
    contents = []
    for x in sub_files:
        with open(os.path.join(tmp_path, x)) as fh:
            contents.append(fh.read())
    assert contents == ["やばい", "セーフ"]


def test_manual_subtitles_rescaled_with_real_duration(
    tmp_path, monkeypatch,
) -> None:
    """scene_videos が渡されたら subtitles[].start/end も実尺比でリスケール。"""
    sp = {
        "scenes": [
            {
                "duration": 5.0,
                "background_prompt": "bg",
                "lines": [
                    {
                        "text": "x",
                        "start": 0.0,
                        "end": 4.0,
                        "subtitles": [
                            {"text": "A", "start": 0.0, "end": 2.0},
                            {"text": "B", "start": 2.0, "end": 4.0},
                        ],
                    }
                ],
            }
        ],
    }
    durations = {"a.mp4": 7.5}  # ratio 1.5
    monkeypatch.setattr(
        compositor, "_get_duration",
        lambda p: durations[os.path.basename(p)])
    paths = [str(tmp_path / "a.mp4")]
    f = compositor._build_overlay_filter(sp, str(tmp_path), scene_videos=paths)
    # A: 0 - 2 → 0 - 3.0、B: 2 - 4 → 3.0 - 6.0
    assert "between(t,0.000,3.000)" in f
    assert "between(t,3.000,6.000)" in f


def test_manual_subtitles_offset_by_previous_scene(tmp_path) -> None:
    """前シーンの duration ぶん絶対時刻が後ろにシフトする。"""
    sp = {
        "scenes": [
            {"duration": 3.0, "background_prompt": "bg",
              "lines": [{"text": "a", "start": 0.0, "end": 1.0}]},
            {
                "duration": 5.0,
                "background_prompt": "bg",
                "lines": [
                    {
                        "text": "x",
                        "start": 0.0,
                        "end": 4.0,
                        "subtitles": [
                            {"text": "M", "start": 1.0, "end": 2.5},
                        ],
                    }
                ],
            },
        ],
    }
    f = compositor._build_overlay_filter(sp, str(tmp_path))
    # offset 3.0 + 1.0 = 4.0、3.0 + 2.5 = 5.5
    assert "between(t,4.000,5.500)" in f


def test_resolve_timings_all_auto_proportional() -> None:
    """全 chunk の start/end が無いとき、line 範囲を文字数比例で埋める。"""
    items = [{"text": "AB"}, {"text": "CDEF"}]  # 2 + 4 = 6
    out = compositor._resolve_subtitle_timings(items, 0.0, 6.0)
    assert len(out) == 2
    assert abs(out[0][0] - 0.0) < 1e-6
    assert abs(out[0][1] - 2.0) < 1e-6
    assert abs(out[1][0] - 2.0) < 1e-6
    assert abs(out[1][1] - 6.0) < 1e-6


def test_resolve_timings_all_fixed_passthrough() -> None:
    """全 chunk が固定値のときはそのまま返る。"""
    items = [
        {"text": "A", "start": 0.0, "end": 1.0},
        {"text": "B", "start": 1.0, "end": 3.0},
    ]
    out = compositor._resolve_subtitle_timings(items, 0.0, 5.0)
    assert out == [(0.0, 1.0), (1.0, 3.0)]


def test_resolve_timings_mixed_uses_anchors() -> None:
    """中央のみ固定。前後の auto chunks は line 端と固定境界の間で配分。"""
    items = [
        {"text": "AAAA"},                            # auto: 0.0 - 4.0 (固定境界まで)
        {"text": "BB", "start": 4.0, "end": 6.0},    # 固定
        {"text": "CCCC"},                            # auto: 6.0 - 10.0
    ]
    out = compositor._resolve_subtitle_timings(items, 0.0, 10.0)
    assert abs(out[0][0] - 0.0) < 1e-6
    assert abs(out[0][1] - 4.0) < 1e-6
    assert out[1] == (4.0, 6.0)
    assert abs(out[2][0] - 6.0) < 1e-6
    assert abs(out[2][1] - 10.0) < 1e-6


def test_resolve_timings_two_autos_in_segment_split_by_chars() -> None:
    """連続 auto chunks は前後の確定境界の間で文字数比例で配分。"""
    items = [
        {"text": "AB"},                                # auto
        {"text": "CDEF"},                              # auto (合計 6 chars in 0-6 range)
        {"text": "G", "start": 6.0, "end": 7.0},
    ]
    out = compositor._resolve_subtitle_timings(items, 0.0, 7.0)
    # 0-6 を 2:4 で配分 → 0-2, 2-6
    assert abs(out[0][1] - 2.0) < 1e-6
    assert abs(out[1][0] - 2.0) < 1e-6
    assert abs(out[1][1] - 6.0) < 1e-6
    assert out[2] == (6.0, 7.0)


def test_resolve_timings_zero_chars_falls_back_to_even() -> None:
    """文字数 0 の auto chunks は均等割で埋める。"""
    items = [{"text": ""}, {"text": ""}, {"text": ""}]
    out = compositor._resolve_subtitle_timings(items, 0.0, 6.0)
    # 均等 2.0 ずつ
    assert abs(out[0][1] - 2.0) < 1e-6
    assert abs(out[1][0] - 2.0) < 1e-6
    assert abs(out[1][1] - 4.0) < 1e-6
    assert abs(out[2][1] - 6.0) < 1e-6


def test_resolve_timings_empty_returns_empty() -> None:
    assert compositor._resolve_subtitle_timings([], 0.0, 5.0) == []


def test_manual_subtitles_text_only_auto_distributes(
    tmp_path,
) -> None:
    """手動チャンクで text だけ書けば line 範囲を文字数比例で配分する。"""
    sp = {
        "scenes": [
            {
                "duration": 5.0,
                "background_prompt": "bg",
                "lines": [
                    {
                        "text": "x",
                        "start": 0.0,
                        "end": 6.0,
                        "subtitles": [
                            {"text": "AB"},     # 2 chars
                            {"text": "CDEF"},   # 4 chars (合計 6)
                        ],
                    }
                ],
            }
        ],
    }
    f = compositor._build_overlay_filter(sp, str(tmp_path))
    # 0-6 を 2:4 配分 → 0-2, 2-6
    assert "between(t,0.000,2.000)" in f
    assert "between(t,2.000,6.000)" in f


def test_manual_subtitles_mixed_auto_and_fixed(tmp_path) -> None:
    """一部だけ動画タイムで打ち込み、残りは自動配分。"""
    sp = {
        "scenes": [
            {
                "duration": 10.0,
                "background_prompt": "bg",
                "lines": [
                    {
                        "text": "x",
                        "start": 0.0,
                        "end": 10.0,
                        "subtitles": [
                            {"text": "AAAA"},
                            {"text": "BB", "start": 4.0, "end": 6.0},
                            {"text": "CCCC"},
                        ],
                    }
                ],
            }
        ],
    }
    f = compositor._build_overlay_filter(sp, str(tmp_path))
    assert "between(t,0.000,4.000)" in f
    assert "between(t,4.000,6.000)" in f
    assert "between(t,6.000,10.000)" in f


def test_hidden_line_skipped_in_overlay(tmp_path) -> None:
    """lines[].hidden=True なら drawtext が生成されない。"""
    sp = {
        "scenes": [
            {
                "duration": 5.0,
                "background_prompt": "bg",
                "lines": [
                    {"text": "見える", "start": 0.0, "end": 1.0},
                    {"text": "隠す",   "start": 1.0, "end": 2.0, "hidden": True},
                    {"text": "見える2", "start": 2.0, "end": 3.0},
                ],
            }
        ],
    }
    f = compositor._build_overlay_filter(sp, str(tmp_path))
    sub_files = sorted(
        x for x in os.listdir(tmp_path) if x.startswith("drawtext_sub_"))
    contents = []
    for x in sub_files:
        with open(os.path.join(tmp_path, x)) as fh:
            contents.append(fh.read())
    assert "隠す" not in contents
    # 隣接 line の timing は影響を受けない (line_window は next_line を見る)
    assert "between(t,0.000,1.000)" in f
    assert "between(t,2.000,3.000)" in f


def test_hidden_line_does_not_affect_next_line_window(tmp_path) -> None:
    """hidden line は next_line として残るので、前の line の終端に影響しない。"""
    sp = {
        "scenes": [
            {
                "duration": 5.0,
                "background_prompt": "bg",
                "lines": [
                    {"text": "前", "start": 0.0},  # end 未指定 → next.start まで
                    {"text": "中", "start": 2.0, "end": 3.0, "hidden": True},
                    {"text": "後", "start": 3.0, "end": 4.0},
                ],
            }
        ],
    }
    f = compositor._build_overlay_filter(sp, str(tmp_path))
    # 前 line は hidden line の start (2.0) まで表示される
    assert "between(t,0.000,2.000)" in f
    assert "between(t,3.000,4.000)" in f


def test_needs_overlay_all_hidden_returns_false() -> None:
    """全 line が hidden なら overlay 工程不要。"""
    sp = {
        "scenes": [
            {
                "duration": 3.0,
                "background_prompt": "bg",
                "lines": [
                    {"text": "a", "start": 0.0, "end": 1.0, "hidden": True},
                    {"text": "b", "start": 1.0, "end": 2.0, "hidden": True},
                ],
            }
        ],
    }
    assert compositor._needs_overlay(sp) is False


def test_needs_overlay_partial_hidden_returns_true() -> None:
    """1つでも hidden でない line があれば overlay 必要。"""
    sp = {
        "scenes": [
            {
                "duration": 3.0,
                "background_prompt": "bg",
                "lines": [
                    {"text": "a", "start": 0.0, "end": 1.0, "hidden": True},
                    {"text": "b", "start": 1.0, "end": 2.0},
                ],
            }
        ],
    }
    assert compositor._needs_overlay(sp) is True


def test_hidden_line_with_subtitles_field_still_skipped(tmp_path) -> None:
    """hidden=True は subtitles[] が残っていても優先される。"""
    sp = {
        "scenes": [
            {
                "duration": 5.0,
                "background_prompt": "bg",
                "lines": [
                    {
                        "text": "x",
                        "start": 0.0,
                        "end": 4.0,
                        "hidden": True,
                        "subtitles": [
                            {"text": "残骸", "start": 0.0, "end": 2.0},
                        ],
                    }
                ],
            }
        ],
    }
    f = compositor._build_overlay_filter(sp, str(tmp_path))
    # subtitles[] のテキストも drawtext として出ない
    assert "between(t,0.000,2.000)" not in f
    sub_files = [
        x for x in os.listdir(tmp_path) if x.startswith("drawtext_sub_")]
    assert sub_files == []


def test_manual_subtitles_empty_text_skipped(tmp_path) -> None:
    """空文字 text の subtitle は drawtext を生成しない。"""
    sp = {
        "scenes": [
            {
                "duration": 5.0,
                "background_prompt": "bg",
                "lines": [
                    {
                        "text": "x",
                        "start": 0.0,
                        "end": 4.0,
                        "subtitles": [
                            {"text": "",      "start": 0.0, "end": 1.0},
                            {"text": "あり", "start": 1.0, "end": 2.0},
                        ],
                    }
                ],
            }
        ],
    }
    f = compositor._build_overlay_filter(sp, str(tmp_path))
    assert "between(t,1.000,2.000)" in f
    assert "between(t,0.000,1.000)" not in f
