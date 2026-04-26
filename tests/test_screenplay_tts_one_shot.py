import json
import os
from unittest.mock import MagicMock

import pytest

import scene_gen


@pytest.fixture
def temp_dir(tmp_path) -> str:
    return str(tmp_path)


def _minimal_screenplay() -> dict:
    return {
        "audio_mode": "voiced",
        "scenes": [
            {"duration": 3.0, "background_prompt": "bg",
             "lines": [{"text": "やばい", "start": 0.0}]},
            {"duration": 3.0, "background_prompt": "bg",
             "lines": [
                 {"text": "セーフ", "start": 0.0},
                 {"text": "助かった", "start": 0.5},
             ]},
        ],
    }


def test_build_screenplay_text_concatenates_with_separator() -> None:
    sp = _minimal_screenplay()
    text, specs = scene_gen._build_screenplay_text(sp)
    # SEP = "  " (2 spaces) between every line
    assert text == "やばい  セーフ  助かった"
    assert len(specs) == 3
    # Validate offsets
    assert text[specs[0]["char_start"]:specs[0]["char_end"]] == "やばい"
    assert text[specs[1]["char_start"]:specs[1]["char_end"]] == "セーフ"
    assert text[specs[2]["char_start"]:specs[2]["char_end"]] == "助かった"


def test_build_position_to_time_map_aligns_chars() -> None:
    text = "abc"
    char_ts = [
        {"char": "a", "start": 0.0, "end": 0.1},
        {"char": "b", "start": 0.1, "end": 0.2},
        {"char": "c", "start": 0.2, "end": 0.3},
    ]
    result = scene_gen._build_position_to_time_map(text, char_ts)
    assert len(result) == 3
    assert result[0]["start"] == 0.0
    assert result[2]["end"] == 0.3


def test_build_position_to_time_map_handles_skipped_chars() -> None:
    """APIが一部charを返さない場合、未マッピングはNoneのまま。"""
    text = "abcd"
    char_ts = [
        {"char": "a", "start": 0.0, "end": 0.1},
        {"char": "c", "start": 0.2, "end": 0.3},
    ]
    result = scene_gen._build_position_to_time_map(text, char_ts)
    assert result[0] is not None
    assert result[1] is None
    assert result[2] is not None
    assert result[3] is None


def test_find_line_time_range_returns_first_and_last() -> None:
    pos_to_time = [
        {"start": 0.0, "end": 0.1},
        {"start": 0.1, "end": 0.2},
        None,
        {"start": 0.3, "end": 0.4},
    ]
    abs_start, abs_end = scene_gen._find_line_time_range(pos_to_time, 0, 4)
    assert abs_start == 0.0
    assert abs_end == 0.4


def test_find_line_time_range_returns_none_when_no_data() -> None:
    pos_to_time = [None, None, None]
    abs_start, abs_end = scene_gen._find_line_time_range(pos_to_time, 0, 3)
    assert abs_start is None
    assert abs_end is None


def test_clear_tts_artifacts_removes_all_relevant_files(temp_dir) -> None:
    for fname in [
        "tts_full.mp3", "tts_full.json", "tts_full.text_meta.json",
        "tts_000_000.mp3", "tts_001_000.mp3", "audio_000.m4a", "audio_001.m4a",
    ]:
        open(os.path.join(temp_dir, fname), "wb").write(b"x")
    scene_gen._clear_tts_artifacts(temp_dir)
    assert sorted(os.listdir(temp_dir)) == []


def test_one_shot_silent_mode_returns_none(temp_dir) -> None:
    sp = _minimal_screenplay()
    sp["audio_mode"] = "silent"
    result = scene_gen.generate_screenplay_tts_one_shot(sp, temp_dir)
    assert result is None


def test_one_shot_no_api_key_skips(temp_dir, monkeypatch) -> None:
    monkeypatch.setattr(scene_gen.config, "ELEVENLABS_API_KEY", None)
    sp = _minimal_screenplay()
    result = scene_gen.generate_screenplay_tts_one_shot(sp, temp_dir)
    assert result is None


def test_one_shot_full_flow_with_mocked_api(temp_dir, monkeypatch) -> None:
    """APIをmockし、char timestampsから line.start/end と scene.duration が
    正しく逆算されることを検証する。"""
    monkeypatch.setattr(scene_gen.config, "ELEVENLABS_API_KEY", "test-key")

    sp = _minimal_screenplay()
    full_text, _ = scene_gen._build_screenplay_text(sp)

    # APIモック: 各charに 0.1秒間隔でtimestampを付ける
    fake_timestamps = []
    for i, ch in enumerate(full_text):
        fake_timestamps.append({
            "char": ch,
            "start": i * 0.1,
            "end": (i + 1) * 0.1,
        })

    def fake_api(*args, **kwargs):
        # output_pathにダミーmp3を作成、timestamps_jsonに保存
        out = kwargs["output_path"]
        open(out, "wb").write(b"fake_mp3")
        ts_path = out.rsplit(".", 1)[0] + ".json"
        with open(ts_path, "w") as f:
            json.dump(fake_timestamps, f)
        return fake_timestamps

    monkeypatch.setattr(
        scene_gen.elevenlabs_client,
        "generate_speech_with_timestamps", fake_api,
    )
    # ffmpeg呼び出しもmock (実ファイルがないので)
    extract_calls = []

    def fake_extract(input_path, start_sec, duration, output_path,
                      codec="aac", bitrate="192k"):
        extract_calls.append({
            "out": output_path, "start": start_sec, "duration": duration,
        })
        open(output_path, "wb").write(b"x")

    # _get_duration は output_path 別に extract dur を覚えて返す
    file_durs: dict[str, float] = {}
    def dynamic_extract(input_path, start_sec, duration, output_path, **kw):
        file_durs[output_path] = duration
        extract_calls.append({
            "out": output_path, "start": start_sec, "duration": duration,
        })
        open(output_path, "wb").write(b"x")
    monkeypatch.setattr(scene_gen, "_extract_audio_segment", dynamic_extract)
    monkeypatch.setattr(scene_gen, "_get_duration",
                          lambda p: file_durs.get(p, 0.3))
    monkeypatch.setattr(scene_gen, "_apply_atempo_inplace", lambda *a, **kw: None)

    result = scene_gen.generate_screenplay_tts_one_shot(sp, temp_dir)
    assert result is not None

    # scene.duration は SCENE_MIN_DURATION 以上
    assert sp["scenes"][0]["duration"] >= scene_gen.config.SCENE_MIN_DURATION
    # S1L1 (やばい): char 0..3, abs_start=0, abs_end=0.3
    # → 旧仕様 (連続抽出): line.start=0.0, line.end=0.3
    assert sp["scenes"][0]["lines"][0]["start"] == 0.0
    assert sp["scenes"][0]["lines"][0]["end"] == pytest.approx(0.3, abs=0.01)

    # キャッシュメタ保存
    assert os.path.exists(os.path.join(temp_dir, "tts_full.text_meta.json"))


def test_one_shot_caches_when_text_unchanged(temp_dir, monkeypatch) -> None:
    """text_hash (text + voice + speed の hash) が変わらなければAPI再呼び出ししない。"""
    monkeypatch.setattr(scene_gen.config, "ELEVENLABS_API_KEY", "test-key")
    sp = _minimal_screenplay()

    full_text, _ = scene_gen._build_screenplay_text(sp)
    native_speed, atempo = scene_gen._split_global_speed()
    voice_id = scene_gen.config.ELEVENLABS_VOICE_ID
    trim_sil = bool(getattr(scene_gen.config, "TTS_TRIM_LONG_SILENCES", False))
    max_sil_ms = float(getattr(scene_gen.config, "TTS_MAX_SILENCE_MS", 250))
    sil_thr = float(getattr(scene_gen.config, "TTS_SILENCE_THRESHOLD_DB", -40))
    cache_key = (
        f"{full_text}|v={voice_id}|s={native_speed:.3f}|a={atempo:.3f}"
        f"|trim={int(trim_sil)}|maxsil={max_sil_ms:.0f}|thr={sil_thr:.1f}"
    )
    import hashlib
    text_hash = hashlib.sha256(cache_key.encode()).hexdigest()[:12]

    fake_ts = [{"char": ch, "start": i * 0.1, "end": (i + 1) * 0.1}
                for i, ch in enumerate(full_text)]
    open(os.path.join(temp_dir, "tts_full.mp3"), "wb").write(b"cached")
    with open(os.path.join(temp_dir, "tts_full.json"), "w") as f:
        json.dump(fake_ts, f)
    with open(os.path.join(temp_dir, "tts_full.text_meta.json"), "w") as f:
        json.dump({"text_hash": text_hash}, f)

    api_spy = MagicMock()
    monkeypatch.setattr(
        scene_gen.elevenlabs_client,
        "generate_speech_with_timestamps", api_spy,
    )
    monkeypatch.setattr(
        scene_gen, "_extract_audio_segment",
        lambda *a, **kw: open(a[3], "wb").write(b"x"),
    )
    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 0.3)
    monkeypatch.setattr(scene_gen, "_apply_atempo_inplace", lambda *a, **kw: None)

    scene_gen.generate_screenplay_tts_one_shot(sp, temp_dir)
    api_spy.assert_not_called()


def test_regen_tts_full_clears_cache(temp_dir, monkeypatch) -> None:
    """regen_tts_full は既存生成物を削除してから生成。"""
    monkeypatch.setattr(scene_gen.config, "ELEVENLABS_API_KEY", "test-key")
    open(os.path.join(temp_dir, "tts_full.mp3"), "wb").write(b"old")
    open(os.path.join(temp_dir, "audio_000.m4a"), "wb").write(b"old")

    api_calls = []

    def fake_api(*args, **kwargs):
        api_calls.append(kwargs)
        out = kwargs["output_path"]
        open(out, "wb").write(b"new")
        ts_path = out.rsplit(".", 1)[0] + ".json"
        with open(ts_path, "w") as f:
            json.dump([], f)

    monkeypatch.setattr(
        scene_gen.elevenlabs_client,
        "generate_speech_with_timestamps", fake_api,
    )
    monkeypatch.setattr(
        scene_gen, "_extract_audio_segment",
        lambda *a, **kw: None,
    )

    sp = _minimal_screenplay()
    scene_gen.regen_tts_full(sp, temp_dir)
    # APIが呼ばれた = キャッシュ削除されたから
    assert len(api_calls) == 1


def test_split_global_speed_normal() -> None:
    native, atempo = scene_gen._split_global_speed(1.0)
    assert native == 1.0
    assert atempo == 1.0


def test_split_global_speed_within_native_range() -> None:
    native, atempo = scene_gen._split_global_speed(0.9)
    assert native == 0.9
    assert atempo == 1.0


def test_split_global_speed_above_native_max_uses_atempo() -> None:
    native, atempo = scene_gen._split_global_speed(1.5)
    assert native == 1.2  # native上限
    assert abs(atempo - 1.25) < 0.001  # 1.5 / 1.2


def test_split_global_speed_2x() -> None:
    native, atempo = scene_gen._split_global_speed(2.0)
    assert native == 1.2
    assert abs(atempo - (2.0 / 1.2)) < 0.001


def test_split_global_speed_below_native_min_uses_atempo() -> None:
    native, atempo = scene_gen._split_global_speed(0.5)
    assert native == 0.7  # native下限
    assert abs(atempo - (0.5 / 0.7)) < 0.001


def test_split_global_speed_clamps_extremes() -> None:
    native, atempo = scene_gen._split_global_speed(5.0)
    assert native == 1.2
    assert abs(atempo - (2.0 / 1.2)) < 0.001
    native, atempo = scene_gen._split_global_speed(0.1)
    assert native == 0.7
    assert abs(atempo - (0.5 / 0.7)) < 0.001


def test_adjust_timestamps_for_silence_trim_subtracts_excess() -> None:
    """無音超過分を時刻から差し引く。"""
    char_ts = [
        {"char": "a", "start": 0.0, "end": 0.5},
        {"char": "b", "start": 0.5, "end": 1.0},
        {"char": "c", "start": 2.0, "end": 2.5},  # 無音(1.0〜2.0)後
    ]
    silences = [(1.0, 2.0)]  # 1秒の無音
    max_silence_sec = 0.25  # 250msに圧縮 → 750ms削減
    scene_gen._adjust_timestamps_for_silence_trim(
        char_ts, silences, max_silence_sec)
    # 'a', 'b' は無音より前なので影響なし
    assert char_ts[0]["start"] == 0.0
    assert char_ts[1]["end"] == 1.0
    # 'c' は無音より後なので 0.75秒 (= 1.0 - 0.25) 引く
    assert abs(char_ts[2]["start"] - (2.0 - 0.75)) < 0.01
    assert abs(char_ts[2]["end"] - (2.5 - 0.75)) < 0.01


def test_adjust_timestamps_for_silence_trim_no_excess_no_change() -> None:
    """無音が max 以下なら変更なし。"""
    char_ts = [{"char": "a", "start": 1.5, "end": 2.0}]
    silences = [(1.0, 1.2)]  # 200ms 無音 (max=250msなら超過なし)
    scene_gen._adjust_timestamps_for_silence_trim(char_ts, silences, 0.25)
    assert char_ts[0]["start"] == 1.5
    assert char_ts[0]["end"] == 2.0


def test_adjust_timestamps_handles_empty_silences() -> None:
    char_ts = [{"char": "a", "start": 1.0, "end": 1.5}]
    scene_gen._adjust_timestamps_for_silence_trim(char_ts, [], 0.25)
    assert char_ts[0]["start"] == 1.0


