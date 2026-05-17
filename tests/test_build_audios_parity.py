"""one-shot / per-voice 両 path 共通の audio build helpers の parity test。

両 path は `_extract_line_audio_segment()` と
`_assemble_scene_and_merged_audios()` を共有することで per-line ファイル
契約 (= tts_<S>_<L>.mp3 / audio_<S>.m4a / merged_preview.m4a) を保証する。
本テストは共通 helper の単体動作を固定し、両 path の出力 parity を担保する。
"""

import os

import pytest

import config
import scene_gen


def test_extract_line_audio_segment_basic_path(tmp_path, monkeypatch):
    """body + tail concat の全工程が想定通り呼ばれること。"""
    voice_mp3 = str(tmp_path / "voice.mp3")
    out_path = str(tmp_path / "tts_000_000.mp3")
    extract_calls: list[tuple] = []
    concat_calls: list[tuple] = []
    atempo_calls: list[float] = []

    def fake_extract(src, start, dur, dst, **_):
        extract_calls.append((src, start, dur, dst))
        with open(dst, "wb") as f:
            f.write(b"X")

    def fake_concat(pieces, dst):
        concat_calls.append((tuple(pieces), dst))
        with open(dst, "wb") as f:
            f.write(b"X")

    monkeypatch.setattr(scene_gen, "_extract_audio_segment", fake_extract)
    monkeypatch.setattr(scene_gen, "_concat_audios_to_mp3", fake_concat)
    monkeypatch.setattr(scene_gen, "_apply_atempo_inplace",
                        lambda p, r: atempo_calls.append(r))
    monkeypatch.setattr(scene_gen, "_natural_tail_silence_sec", lambda: 0.3)

    silence = scene_gen._extract_line_audio_segment(
        voice_mp3=voice_mp3,
        voice_full_dur=10.0,
        abs_start=1.0,
        abs_end=2.0,
        next_abs_start_in_voice=3.0,
        out_path=out_path,
        trim_sil=False,
        max_sil_sec=0.25,
        sil_thr=-40,
        atempo=1.0,
    )

    # body (1.0-2.0, dur=1.0) + tail (2.0-2.3, dur=0.3) を extract
    assert len(extract_calls) == 2
    assert extract_calls[0][1] == 1.0
    assert extract_calls[0][2] == pytest.approx(1.0)
    assert extract_calls[1][1] == 2.0
    assert extract_calls[1][2] == pytest.approx(0.3)
    # concat される pieces は body + tail の 2 つ
    assert len(concat_calls[0][0]) == 2
    # atempo=1.0 なので適用されない
    assert atempo_calls == []
    # natural silence (= atempo 補正後 = 0.3 / 1.0)
    assert silence == pytest.approx(0.3)


def test_extract_line_audio_segment_clamps_to_voice_end(tmp_path, monkeypatch):
    """abs_end が voice_full_dur 超過なら body は clamp、tail は available=0 で省略。"""
    voice_mp3 = str(tmp_path / "voice.mp3")
    out_path = str(tmp_path / "tts.mp3")
    extract_calls: list[tuple] = []

    def fake_extract(src, start, dur, dst, **_):
        extract_calls.append((start, dur))
        with open(dst, "wb") as f:
            f.write(b"X")

    monkeypatch.setattr(scene_gen, "_extract_audio_segment", fake_extract)
    monkeypatch.setattr(
        scene_gen, "_concat_audios_to_mp3",
        lambda pieces, dst: open(dst, "wb").write(b"X"),
    )
    monkeypatch.setattr(scene_gen, "_apply_atempo_inplace", lambda p, r: None)
    monkeypatch.setattr(scene_gen, "_natural_tail_silence_sec", lambda: 0.5)

    scene_gen._extract_line_audio_segment(
        voice_mp3=voice_mp3,
        voice_full_dur=2.5,
        abs_start=1.0,
        abs_end=3.0,  # voice_full_dur 超過
        next_abs_start_in_voice=float("inf"),
        out_path=out_path,
        trim_sil=False, max_sil_sec=0.25, sil_thr=-40, atempo=1.0,
    )

    # body 切出は abs_start=1.0, dur = (clamp 2.5 - 1.0) = 1.5
    assert extract_calls[0][0] == 1.0
    assert extract_calls[0][1] == pytest.approx(1.5)
    # tail は available=0 で省略
    assert len(extract_calls) == 1


def test_extract_line_audio_segment_applies_atempo(tmp_path, monkeypatch):
    """atempo > 1.0 のとき atempo が適用され、silence 値が割られる。"""
    voice_mp3 = str(tmp_path / "v.mp3")
    out_path = str(tmp_path / "o.mp3")
    atempo_calls: list[float] = []

    monkeypatch.setattr(
        scene_gen, "_extract_audio_segment",
        lambda src, st, du, dst, **_: open(dst, "wb").write(b"X"),
    )
    monkeypatch.setattr(
        scene_gen, "_concat_audios_to_mp3",
        lambda pieces, dst: open(dst, "wb").write(b"X"),
    )
    monkeypatch.setattr(
        scene_gen, "_apply_atempo_inplace",
        lambda p, r: atempo_calls.append(r),
    )
    monkeypatch.setattr(scene_gen, "_natural_tail_silence_sec", lambda: 0.4)

    silence = scene_gen._extract_line_audio_segment(
        voice_mp3=voice_mp3, voice_full_dur=10.0,
        abs_start=0.0, abs_end=1.0, next_abs_start_in_voice=5.0,
        out_path=out_path,
        trim_sil=False, max_sil_sec=0.25, sil_thr=-40, atempo=1.5,
    )

    assert atempo_calls == [1.5]
    # natural_extract=0.4, atempo=1.5 → silence = 0.4 / 1.5
    assert silence == pytest.approx(0.4 / 1.5)


def test_assemble_scene_and_merged_audios_updates_screenplay(
    tmp_path, monkeypatch,
):
    """per-scene と merged_preview の concat + scene["duration"] / line["start","end"] 更新。"""
    sp = {
        "scenes": [
            {"lines": [
                {"text": "a", "start": 0, "end": 0},
                {"text": "b", "start": 0, "end": 0},
            ]},
            {"lines": [{"text": "c", "start": 0, "end": 0}]},
        ],
    }
    ts_path = str(tmp_path)

    for s, n in ((0, 2), (1, 1)):
        for l in range(n):
            p = os.path.join(ts_path, f"tts_{s:03d}_{l:03d}.mp3")
            with open(p, "wb") as f:
                f.write(b"X")

    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 2.0)
    aac_calls: list[tuple] = []

    def fake_aac(pieces, dst):
        aac_calls.append((tuple(pieces), dst))
        with open(dst, "wb") as f:
            f.write(b"X")

    monkeypatch.setattr(scene_gen, "_concat_audios_to_aac", fake_aac)

    by_scene = {
        0: [{"scene_idx": 0, "line_idx": 0}, {"scene_idx": 0, "line_idx": 1}],
        1: [{"scene_idx": 1, "line_idx": 0}],
    }
    line_actual_silences = {(0, 0): 0.0, (0, 1): 0.0, (1, 0): 0.0}

    scene_gen._assemble_scene_and_merged_audios(
        screenplay=sp, ts_path=ts_path,
        by_scene=by_scene, line_actual_silences=line_actual_silences,
    )

    # 各 scene の audio_<S>.m4a (2) + merged_preview.m4a (1) で 3 calls
    assert len(aac_calls) == 3
    assert sp["scenes"][0]["duration"] == pytest.approx(
        2.0 * 2 + config.SCENE_TTS_TAIL_BUFFER
    )
    assert sp["scenes"][1]["duration"] == pytest.approx(
        2.0 + config.SCENE_TTS_TAIL_BUFFER
    )
    # speech_dur = file_dur (2.0) - silence (0.0) = 2.0
    assert sp["scenes"][0]["lines"][0]["start"] == 0.0
    assert sp["scenes"][0]["lines"][0]["end"] == 2.0
    assert sp["scenes"][0]["lines"][1]["start"] == 2.0
    assert sp["scenes"][0]["lines"][1]["end"] == 4.0


def test_assemble_skips_empty_scene(tmp_path, monkeypatch):
    """line がない scene は duration=0 にして audio 生成しない。"""
    sp = {
        "scenes": [
            {"lines": [{"text": "x", "start": 0, "end": 0}]},
            {"lines": []},
        ],
    }
    ts_path = str(tmp_path)
    with open(os.path.join(ts_path, "tts_000_000.mp3"), "wb") as f:
        f.write(b"X")

    monkeypatch.setattr(scene_gen, "_get_duration", lambda p: 1.0)
    aac_calls: list[tuple] = []

    def fake_aac(pieces, dst):
        aac_calls.append((tuple(pieces), dst))
        with open(dst, "wb") as f:
            f.write(b"X")

    monkeypatch.setattr(scene_gen, "_concat_audios_to_aac", fake_aac)

    by_scene = {0: [{"scene_idx": 0, "line_idx": 0}]}
    scene_gen._assemble_scene_and_merged_audios(
        screenplay=sp, ts_path=ts_path, by_scene=by_scene,
        line_actual_silences={(0, 0): 0.0},
    )

    # scene 0 のみ audio + merged で 2 calls
    assert len(aac_calls) == 2
    assert sp["scenes"][1]["duration"] == 0.0


def test_rebuild_audios_from_full_after_boundary_change_delegates(monkeypatch):
    """public wrapper が one-shot 経路 (_build_audios_from_full) に委譲する。"""
    calls: list[tuple] = []
    monkeypatch.setattr(
        scene_gen, "_build_audios_from_full",
        lambda sp, tp: calls.append((sp, tp)),
    )
    scene_gen.rebuild_audios_from_full_after_boundary_change({"x": 1}, "/p")
    assert calls == [({"x": 1}, "/p")]
