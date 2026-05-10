"""compositor_remotion.py の単体テスト。

設計 doc: docs/plannings/2026-05-10_compositional-architecture.md §5
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import compositor_remotion


def _make_dummy_video(path: Path, duration_sec: float = 2.0) -> None:
    """ffmpeg で空っぽの 1080x1920 / 60fps mp4 を作る (= ffprobe で読める尺だけ持つ)。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=black:size=1080x1920:rate=60:duration={duration_sec}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "30",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, check=True, timeout=30)


@pytest.fixture
def dummy_scene_videos(tmp_path: Path) -> list[str]:
    """2 シーンぶんの dummy mp4 (= 各 2 秒) を作って絶対パスを返す。"""

    videos: list[str] = []
    for i in range(2):
        p = tmp_path / "tmp" / f"scene_{i:03d}.mp4"
        _make_dummy_video(p, duration_sec=2.0)
        videos.append(str(p))
    return videos


# ───────────── build_render_plan ─────────────


class TestBuildRenderPlan:
    def test_basic_plan_structure(
        self, dummy_scene_videos: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("config.SUBTITLE_CHUNK_ENABLED", False)
        screenplay = {
            "caption": "test",
            "scenes": [
                {
                    "duration": 2.0,
                    "lines": [
                        {"text": "シーン1のセリフ", "start": 0.5, "end": 1.5}
                    ],
                },
                {
                    "duration": 2.0,
                    "lines": [
                        {"text": "シーン2のセリフ", "start": 0.0, "end": 2.0}
                    ],
                },
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)

        # video meta
        assert plan["video"]["width"] == 1080
        assert plan["video"]["height"] == 1920
        assert plan["video"]["fps"] == 60
        # 2 scenes × 2s @ 60fps = 240 frames (実尺ベース)
        assert plan["video"]["duration_frames"] == 240
        assert plan["template"] == "base"

        # scenes
        assert len(plan["scenes"]) == 2
        assert plan["scenes"][0]["index"] == 0
        assert plan["scenes"][0]["offset_sec"] == 0
        assert plan["scenes"][0]["duration_sec"] == pytest.approx(2.0, abs=0.05)

        # 2 つ目の scene の offset は 1 つ目の duration を引き継ぐ
        assert plan["scenes"][1]["offset_sec"] == pytest.approx(2.0, abs=0.05)

        # 字幕の絶対秒は scene offset 込み
        s2_chunks = plan["scenes"][1]["subtitle_lines"][0]["chunks"]
        assert s2_chunks[0]["start_abs_sec"] >= 2.0

        # subtitle_style 既定は minimal
        assert plan["scenes"][0]["parts"]["subtitle_style"]["id"] == "minimal"
        # default params が注入されている
        params = plan["scenes"][0]["parts"]["subtitle_style"]["params"]
        assert "fontSize" in params
        assert "fontColor" in params
        assert "yFromBottom" in params

    def test_manual_chunks_preserved(
        self, dummy_scene_videos: list[str]
    ) -> None:
        screenplay = {
            "caption": "x",
            "scenes": [
                {
                    "duration": 2.0,
                    "lines": [
                        {
                            "text": "全体",
                            "start": 0.0,
                            "end": 2.0,
                            "subtitles": [
                                {"text": "前半", "start": 0.0, "end": 1.0},
                                {"text": "後半", "start": 1.0, "end": 2.0},
                            ],
                        }
                    ],
                },
                {
                    "duration": 2.0,
                    "lines": [
                        {"text": "シーン2", "start": 0, "end": 2}
                    ],
                },
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        chunks = plan["scenes"][0]["subtitle_lines"][0]["chunks"]
        assert len(chunks) == 2
        # manual で時刻指定されていれば anchor_kind=manual
        assert chunks[0]["anchor_kind"] == "manual"
        assert chunks[1]["anchor_kind"] == "manual"
        assert chunks[0]["text"] == "前半"
        assert chunks[1]["text"] == "後半"

    def test_hidden_lines_excluded(self, dummy_scene_videos: list[str]) -> None:
        screenplay = {
            "caption": "x",
            "scenes": [
                {
                    "duration": 2.0,
                    "lines": [
                        {"text": "見える", "start": 0.0, "end": 1.0},
                        {"text": "隠れる", "start": 1.0, "end": 2.0, "hidden": True},
                    ],
                },
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        sub_lines = plan["scenes"][0]["subtitle_lines"]
        # hidden は除外される
        assert len(sub_lines) == 1
        assert sub_lines[0]["chunks"][0]["text"] == "見える"

    def test_scene_count_mismatch_raises(
        self, dummy_scene_videos: list[str]
    ) -> None:
        # screenplay が 3 シーン、scene_videos が 2 本 → reject
        screenplay = {
            "caption": "x",
            "scenes": [
                {"duration": 2.0, "lines": []},
                {"duration": 2.0, "lines": []},
                {"duration": 2.0, "lines": []},
            ],
        }
        with pytest.raises(ValueError, match="本数が一致"):
            compositor_remotion.build_render_plan(
                screenplay, dummy_scene_videos
            )

    def test_public_relpath_rewrites_paths(
        self, dummy_scene_videos: list[str]
    ) -> None:
        screenplay = {
            "caption": "x",
            "scenes": [
                {"duration": 2.0, "lines": []},
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(
            screenplay, dummy_scene_videos, public_relpath="_render_TEST"
        )
        # 絶対パスではなく relative path が入る
        for s in plan["scenes"]:
            assert s["scene_video_path"].startswith("_render_TEST/scene_")
            assert s["scene_video_path"].endswith(".mp4")

    def test_subtitle_y_from_bottom_override(
        self, dummy_scene_videos: list[str]
    ) -> None:
        screenplay = {
            "caption": "x",
            "subtitle_y_from_bottom": 500,
            "scenes": [
                {"duration": 2.0, "lines": [{"text": "x", "start": 0, "end": 1}]},
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        params = plan["scenes"][0]["parts"]["subtitle_style"]["params"]
        assert params["yFromBottom"] == 500

    def test_scene_parts_subtitle_style_passed_through(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """scene.scene_parts.subtitle_style.id が plan に入る (Phase 4 で他カテゴリ追加)。"""

        screenplay = {
            "caption": "x",
            "scenes": [
                {
                    "duration": 2.0,
                    "lines": [{"text": "y", "start": 0, "end": 1}],
                    "scene_parts": {
                        "subtitle_style": {
                            "id": "minimal",
                            "params": {"fontColor": "#FF0000"},
                        }
                    },
                },
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        sty = plan["scenes"][0]["parts"]["subtitle_style"]
        assert sty["id"] == "minimal"
        # explicit param が default を上書きする
        assert sty["params"]["fontColor"] == "#FF0000"

    def test_scene_parts_stickers_passed_through(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """Phase 4-B: scene_parts.stickers[] が plan.scenes[].parts.stickers に
        正規化されて入る (= id / at / duration / params)。"""

        screenplay = {
            "caption": "x",
            "scenes": [
                {
                    "duration": 2.0,
                    "lines": [{"text": "y", "start": 0, "end": 1}],
                    "scene_parts": {
                        "stickers": [
                            {
                                "id": "exclaim_red",
                                "at": 0.5,
                                "duration": 1.5,
                                "params": {"top": 0.3, "right": 0.1},
                            },
                            {
                                "id": "sparkle",
                                "at": 1.0,
                                # duration 省略 → render 側 default 1.5 秒
                            },
                        ]
                    },
                },
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        stickers = plan["scenes"][0]["parts"]["stickers"]
        assert len(stickers) == 2
        assert stickers[0]["id"] == "exclaim_red"
        assert stickers[0]["at"] == 0.5
        assert stickers[0]["duration"] == 1.5
        assert stickers[0]["params"]["top"] == 0.3
        # 2 件目: duration 未指定なら省略
        assert stickers[1]["id"] == "sparkle"
        assert "duration" not in stickers[1]
        # scene 1 (= sticker 無し) は parts.stickers が無い
        assert "stickers" not in plan["scenes"][1]["parts"]

    def test_global_filter_preset_passed_through(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """Phase 4-C: global_parts.filter_preset が plan に正規化されて入る。"""

        screenplay = {
            "caption": "x",
            "global_parts": {
                "filter_preset": {
                    "id": "warm_cinematic",
                    "params": {"strength": 1.0},
                },
            },
            "scenes": [
                {"duration": 2.0, "lines": []},
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        assert plan["global_parts"]["filter_preset"]["id"] == "warm_cinematic"
        assert plan["global_parts"]["filter_preset"]["params"]["strength"] == 1.0

    def test_global_parts_empty_default(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """global_parts なしの screenplay でも空 dict が返る。"""

        screenplay = {
            "caption": "x",
            "scenes": [
                {"duration": 2.0, "lines": []},
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        assert plan["global_parts"] == {}

    def test_invalid_filter_preset_dropped(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """id が無い / dict でない filter_preset は静かにドロップ。"""

        screenplay = {
            "caption": "x",
            "global_parts": {
                "filter_preset": {"params": {}},  # id 欠落
            },
            "scenes": [
                {"duration": 2.0, "lines": []},
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        assert plan["global_parts"] == {}

    def test_invalid_sticker_entries_skipped(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """id / at が欠けている sticker entry は静かにスキップ。"""

        screenplay = {
            "caption": "x",
            "scenes": [
                {
                    "duration": 2.0,
                    "lines": [],
                    "scene_parts": {
                        "stickers": [
                            {"id": "exclaim_red"},  # at 欠落
                            {"at": 1.0},  # id 欠落
                            "not_a_dict",  # 型違い
                            {"id": "sparkle", "at": 0.5},  # 正常
                        ]
                    },
                },
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        stickers = plan["scenes"][0]["parts"]["stickers"]
        assert len(stickers) == 1
        assert stickers[0]["id"] == "sparkle"

    def test_camera_move_passed_through(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """Phase 4-D: scene_parts.camera_move が plan.scenes[].parts.camera_move に
        正規化されて入る。"""

        screenplay = {
            "caption": "x",
            "scenes": [
                {
                    "duration": 2.0,
                    "lines": [],
                    "scene_parts": {
                        "camera_move": {
                            "id": "subtle_zoom_in",
                            "params": {"to_scale": 1.07},
                        }
                    },
                },
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        cam = plan["scenes"][0]["parts"]["camera_move"]
        assert cam["id"] == "subtle_zoom_in"
        assert cam["params"]["to_scale"] == 1.07
        # camera_move 無し scene には key が立たない
        assert "camera_move" not in plan["scenes"][1]["parts"]

    def test_invalid_camera_move_dropped(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """id 欠落 / dict でない camera_move は静かにドロップ。"""

        screenplay = {
            "caption": "x",
            "scenes": [
                {
                    "duration": 2.0,
                    "lines": [],
                    "scene_parts": {
                        "camera_move": {"params": {}},  # id 欠落
                    },
                },
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        assert "camera_move" not in plan["scenes"][0]["parts"]

    def test_lower_third_passed_through(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """Phase 4-E: scene_parts.lower_third が plan.scenes[].parts.lower_third に
        正規化されて入る。"""

        screenplay = {
            "caption": "x",
            "scenes": [
                {
                    "duration": 2.0,
                    "lines": [],
                    "scene_parts": {
                        "lower_third": {
                            "id": "name_banner",
                            "at": 0.5,
                            "duration": 2.5,
                            "params": {
                                "text": "山田太郎",
                                "sub_text": "エンジニア",
                            },
                        }
                    },
                },
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        lt = plan["scenes"][0]["parts"]["lower_third"]
        assert lt["id"] == "name_banner"
        assert lt["at"] == 0.5
        assert lt["duration"] == 2.5
        assert lt["params"]["text"] == "山田太郎"
        # lower_third 無し scene には key が立たない
        assert "lower_third" not in plan["scenes"][1]["parts"]

    def test_transitions_in_out_passed_through(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """Phase 4-G: scene_parts.transition_in / transition_out が plan に
        正規化されて入る。"""

        screenplay = {
            "caption": "x",
            "scenes": [
                {
                    "duration": 2.0,
                    "lines": [],
                    "scene_parts": {
                        "transition_in": {
                            "id": "dip_to_black",
                            "params": {"duration_frames": 18},
                        },
                        "transition_out": {"id": "dip_to_white"},
                    },
                },
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        ti = plan["scenes"][0]["parts"]["transition_in"]
        to = plan["scenes"][0]["parts"]["transition_out"]
        assert ti["id"] == "dip_to_black"
        assert ti["params"]["duration_frames"] == 18
        assert to["id"] == "dip_to_white"
        assert to["params"] == {}
        # 2 つ目 scene には key 無し
        assert "transition_in" not in plan["scenes"][1]["parts"]

    def test_frame_layout_passed_through(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """Phase 4-H: scene_parts.frame_layout が plan に正規化されて入る。"""

        screenplay = {
            "caption": "x",
            "scenes": [
                {
                    "duration": 2.0,
                    "lines": [],
                    "scene_parts": {
                        "frame_layout": {
                            "id": "letterbox_top_bottom",
                            "params": {"video_height_ratio": 0.7},
                        }
                    },
                },
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        fl = plan["scenes"][0]["parts"]["frame_layout"]
        assert fl["id"] == "letterbox_top_bottom"
        assert fl["params"]["video_height_ratio"] == 0.7
        assert "frame_layout" not in plan["scenes"][1]["parts"]

    def test_invalid_frame_layout_dropped(
        self, dummy_scene_videos: list[str]
    ) -> None:
        screenplay = {
            "caption": "x",
            "scenes": [
                {
                    "duration": 2.0,
                    "lines": [],
                    "scene_parts": {"frame_layout": {"params": {}}},  # id 欠落
                },
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        assert "frame_layout" not in plan["scenes"][0]["parts"]

    def test_invalid_transitions_dropped(
        self, dummy_scene_videos: list[str]
    ) -> None:
        screenplay = {
            "caption": "x",
            "scenes": [
                {
                    "duration": 2.0,
                    "lines": [],
                    "scene_parts": {
                        "transition_in": {"params": {}},  # id 欠落
                        "transition_out": "not_a_dict",
                    },
                },
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        assert "transition_in" not in plan["scenes"][0]["parts"]
        assert "transition_out" not in plan["scenes"][0]["parts"]

    def test_intro_outro_cards_passed_through(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """Phase 4-F: global_parts.intro_card / outro_card が render_plan に
        正規化されて入る。"""

        screenplay = {
            "caption": "x",
            "global_parts": {
                "intro_card": {
                    "id": "simple_intro",
                    "duration_sec": 1.5,
                    "params": {"text": "知らないと損する3つのコツ"},
                },
                "outro_card": {
                    "id": "subscribe_outro",
                    "duration_sec": 2.0,
                    "params": {
                        "text": "チャンネル登録お願いします",
                        "sub_text": "↓ 押すだけ",
                    },
                },
            },
            "scenes": [
                {"duration": 2.0, "lines": []},
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        intro = plan["global_parts"]["intro_card"]
        outro = plan["global_parts"]["outro_card"]
        assert intro["id"] == "simple_intro"
        assert intro["duration_sec"] == 1.5
        assert intro["params"]["text"] == "知らないと損する3つのコツ"
        assert outro["id"] == "subscribe_outro"
        assert outro["duration_sec"] == 2.0
        assert outro["params"]["sub_text"] == "↓ 押すだけ"

    def test_bgm_passed_through_with_constant_volume(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """Phase 5-B: bgm = {path, ducking_curve(number)} が plan に正規化される。"""

        screenplay = {
            "caption": "x",
            "global_parts": {
                "bgm": {
                    "path": "_audio/upbeat.mp3",
                    "ducking_curve": 0.35,
                },
            },
            "scenes": [
                {"duration": 2.0, "lines": []},
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        bgm = plan["global_parts"]["bgm"]
        assert bgm["path"] == "_audio/upbeat.mp3"
        assert bgm["ducking_curve"] == 0.35

    def test_bgm_passed_through_with_curve_array(
        self, dummy_scene_videos: list[str]
    ) -> None:
        screenplay = {
            "caption": "x",
            "global_parts": {
                "bgm": {
                    "path": "https://cdn.example.com/track.mp3",
                    "ducking_curve": [[0.0, 0.4], [10.0, 0.2]],
                },
            },
            "scenes": [
                {"duration": 2.0, "lines": []},
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        bgm = plan["global_parts"]["bgm"]
        assert bgm["path"].startswith("https://")
        assert bgm["ducking_curve"] == [[0.0, 0.4], [10.0, 0.2]]

    def test_bgm_default_ducking_when_unspecified(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """ducking_curve が無いと default 0.4 が入る。"""

        screenplay = {
            "caption": "x",
            "global_parts": {
                "bgm": {"path": "x.mp3"},
            },
            "scenes": [
                {"duration": 2.0, "lines": []},
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        assert plan["global_parts"]["bgm"]["ducking_curve"] == 0.4

    def test_invalid_bgm_dropped(self, dummy_scene_videos: list[str]) -> None:
        """path が無い bgm は静かにドロップ。"""

        screenplay = {
            "caption": "x",
            "global_parts": {"bgm": {"ducking_curve": 0.3}},
            "scenes": [
                {"duration": 2.0, "lines": []},
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        assert "bgm" not in plan["global_parts"]

    def test_sfx_passed_through(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """Phase 5-B: scene_parts.sfx[] が plan.scenes[].parts.sfx に
        正規化されて入る。"""

        screenplay = {
            "caption": "x",
            "scenes": [
                {
                    "duration": 2.0,
                    "lines": [],
                    "scene_parts": {
                        "sfx": [
                            {"path": "_audio/whoosh.mp3", "at": 0.5, "volume": 0.7},
                            {"path": "_audio/ding.mp3", "at": 1.5},
                        ]
                    },
                },
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        sfx = plan["scenes"][0]["parts"]["sfx"]
        assert len(sfx) == 2
        assert sfx[0]["path"] == "_audio/whoosh.mp3"
        assert sfx[0]["at"] == 0.5
        assert sfx[0]["volume"] == 0.7
        assert sfx[1]["path"] == "_audio/ding.mp3"
        assert "volume" not in sfx[1]
        assert "sfx" not in plan["scenes"][1]["parts"]

    def test_invalid_sfx_entries_skipped(
        self, dummy_scene_videos: list[str]
    ) -> None:
        screenplay = {
            "caption": "x",
            "scenes": [
                {
                    "duration": 2.0,
                    "lines": [],
                    "scene_parts": {
                        "sfx": [
                            {"path": "x.mp3"},  # at 欠落
                            {"at": 1.0},  # path 欠落
                            "not_a_dict",
                            {"path": "ok.mp3", "at": 0.5},
                        ]
                    },
                },
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        sfx = plan["scenes"][0]["parts"]["sfx"]
        assert len(sfx) == 1
        assert sfx[0]["path"] == "ok.mp3"

    def test_invalid_intro_outro_cards_dropped(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """id 欠落 / duration_sec 欠落 / dict でない card は静かにドロップ。"""

        screenplay = {
            "caption": "x",
            "global_parts": {
                "intro_card": {"params": {"text": "x"}},  # id / duration 欠落
                "outro_card": {"id": "simple_intro"},  # duration_sec 欠落
            },
            "scenes": [
                {"duration": 2.0, "lines": []},
                {"duration": 2.0, "lines": []},
            ],
        }
        plan = compositor_remotion.build_render_plan(screenplay, dummy_scene_videos)
        assert "intro_card" not in plan["global_parts"]
        assert "outro_card" not in plan["global_parts"]

    def test_invalid_lower_third_dropped(
        self, dummy_scene_videos: list[str]
    ) -> None:
        """id / at / duration いずれか欠落の lower_third は静かにドロップ。"""

        for bad in (
            {"params": {"text": "x"}},  # id / at / duration 欠落
            {"id": "name_banner", "at": 0.5},  # duration 欠落
            {"id": "name_banner", "duration": 2.0, "params": {}},  # at 欠落
        ):
            screenplay = {
                "caption": "x",
                "scenes": [
                    {
                        "duration": 2.0,
                        "lines": [],
                        "scene_parts": {"lower_third": bad},
                    },
                    {"duration": 2.0, "lines": []},
                ],
            }
            plan = compositor_remotion.build_render_plan(
                screenplay, dummy_scene_videos
            )
            assert "lower_third" not in plan["scenes"][0]["parts"]


# ───────────── render_via_remotion (= subprocess mock) ─────────────


class TestCompositionIdForTemplate:
    def test_known_templates(self) -> None:
        assert (
            compositor_remotion.composition_id_for_template("base")
            == "ScreenplayBase"
        )
        assert (
            compositor_remotion.composition_id_for_template("youtube")
            == "ScreenplayYoutube"
        )
        assert (
            compositor_remotion.composition_id_for_template("instagram")
            == "ScreenplayInstagram"
        )
        assert (
            compositor_remotion.composition_id_for_template("tiktok")
            == "ScreenplayTikTok"
        )

    def test_unknown_template_falls_back_to_base(self) -> None:
        assert (
            compositor_remotion.composition_id_for_template("nonexistent")
            == "ScreenplayBase"
        )


class TestRenderViaRemotion:
    def test_invokes_remotion_cli_with_correct_args(
        self, tmp_path: Path
    ) -> None:
        plan = {
            "video": {
                "width": 1080,
                "height": 1920,
                "fps": 60,
                "duration_frames": 156,
            },
            "scenes": [],
            "global_parts": {},
            "template": "base",
        }
        output = tmp_path / "out.mp4"

        called: dict = {}

        def fake_run(cmd, **kwargs):
            called["cmd"] = cmd
            called["cwd"] = kwargs.get("cwd")

            class _R:
                returncode = 0
                stderr = ""
                stdout = ""

            return _R()

        with patch.object(subprocess, "run", side_effect=fake_run):
            compositor_remotion.render_via_remotion(plan, str(output))

        cmd = called["cmd"]
        assert cmd[:3] == ["npx", "remotion", "render"]
        assert cmd[3] == "ScreenplayBase"
        # frames=0-{N-1} で durationInFrames を強制
        frames_arg = next(a for a in cmd if a.startswith("--frames="))
        assert frames_arg == "--frames=0-155"
        # props は plan_path を指す
        props_arg = next(a for a in cmd if a.startswith("--props="))
        assert os.path.exists(props_arg.split("=", 1)[1])

    def test_failure_raises(self, tmp_path: Path) -> None:
        plan = {
            "video": {
                "width": 1080,
                "height": 1920,
                "fps": 60,
                "duration_frames": 60,
            },
            "scenes": [],
            "global_parts": {},
            "template": "base",
        }
        output = tmp_path / "out.mp4"

        def fake_run(cmd, **kwargs):
            class _R:
                returncode = 1
                stderr = "Boom"
                stdout = ""

            return _R()

        with patch.object(subprocess, "run", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="remotion render failed"):
                compositor_remotion.render_via_remotion(plan, str(output))


# ───────────── _link_scene_videos ─────────────


class TestLinkSceneVideos:
    def test_creates_symlinks(
        self, dummy_scene_videos: list[str], tmp_path: Path
    ) -> None:
        workspace = tmp_path / "public" / "_render_TS"
        workspace.mkdir(parents=True)
        rels = compositor_remotion._link_scene_videos(
            dummy_scene_videos, workspace, "_render_TS"
        )
        assert len(rels) == 2
        # symlink が生成されている (or copy fallback)
        link0 = workspace / "scene_000.mp4"
        assert link0.exists()
        # 内容が同じ
        assert link0.read_bytes()[:100] == Path(dummy_scene_videos[0]).read_bytes()[:100]

    def test_relinks_when_target_changed(
        self, dummy_scene_videos: list[str], tmp_path: Path
    ) -> None:
        workspace = tmp_path / "public" / "_render_TS"
        workspace.mkdir(parents=True)

        # 1 回目
        compositor_remotion._link_scene_videos(
            dummy_scene_videos, workspace, "_render_TS"
        )

        # ターゲットが変わったら relink される
        new_video = tmp_path / "another.mp4"
        _make_dummy_video(new_video, duration_sec=1.0)
        rels = compositor_remotion._link_scene_videos(
            [str(new_video), dummy_scene_videos[1]], workspace, "_render_TS"
        )
        link0 = workspace / "scene_000.mp4"
        assert link0.exists()
        # 新しい動画を指す
        if link0.is_symlink():
            assert os.readlink(str(link0)) == str(new_video)
