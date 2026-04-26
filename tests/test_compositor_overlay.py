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
