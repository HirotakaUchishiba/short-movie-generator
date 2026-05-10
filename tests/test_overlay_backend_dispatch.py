"""staged_pipeline.run_overlay の OVERLAY_BACKEND dispatch 単体テスト。

Phase 2-B 完了基準: OVERLAY_BACKEND=ffmpeg は既存挙動を維持、=remotion は
compositor_remotion.compose_video_remotion を呼ぶ。

設計 doc: docs/plannings/2026-05-10_compositional-architecture.md §5
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import staged_pipeline


@pytest.fixture
def overlay_ts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """run_overlay を呼べる最小限の TS ディレクトリを用意。

    scene 動画 / progress / metadata を mock しているため、実際の Remotion / ffmpeg は
    走らないことを各テストで monkeypatch で担保する。
    """

    ts_path = tmp_path / "20260510_120000"
    ts_path.mkdir(parents=True)
    (ts_path / "tmp").mkdir()
    # scene の本数 (= 1) と一致する dummy mp4
    scene_mp4 = ts_path / "tmp" / "scene_000.mp4"
    scene_mp4.write_bytes(b"\x00" * 100)

    # OUTPUT_DIR を tmp 化 (= reels_<TS>.mp4 が tmp に書かれる)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr("config.OUTPUT_DIR", str(output_dir))

    # progress / scene_videos / approve gate を bypass する
    monkeypatch.setattr(
        staged_pipeline, "_ensure_prev_approved", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "scene_gen.collect_scene_videos", lambda *a, **kw: [str(scene_mp4)]
    )
    monkeypatch.setattr(
        staged_pipeline, "validate_screenplay", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "progress_store.mark_generated", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        staged_pipeline, "generate_post_captions", lambda *a, **kw: "ignored"
    )
    monkeypatch.setattr(
        staged_pipeline, "_promote_cache_entries", lambda *a, **kw: None
    )

    return ts_path


def _minimal_screenplay() -> dict:
    return {
        "caption": "test",
        "scenes": [
            {
                "duration": 2.0,
                "background_prompt": "x",
                "lines": [
                    {"text": "セリフ", "start": 0.0, "end": 1.0}
                ],
            }
        ],
    }


def test_default_backend_uses_ffmpeg(
    overlay_ts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OVERLAY_BACKEND 未設定 / "ffmpeg" 指定で既存 ffmpeg compositor が呼ばれる。"""

    monkeypatch.setattr("config.OVERLAY_BACKEND", "ffmpeg")

    fake_merge = MagicMock(return_value=str(overlay_ts / "merged.mp4"))

    def fake_apply(merged_path, screenplay, temp_dir, output_path, scene_videos=None):
        Path(output_path).write_bytes(b"OVERLAID")

    fake_apply_mock = MagicMock(side_effect=fake_apply)
    monkeypatch.setattr(staged_pipeline, "_merge_scenes", fake_merge)
    monkeypatch.setattr(staged_pipeline, "_apply_overlays", fake_apply_mock)

    with patch("compositor_remotion.compose_video_remotion") as fake_remotion:
        staged_pipeline.run_overlay(
            _minimal_screenplay(), "test_screenplay", str(overlay_ts)
        )

    fake_merge.assert_called_once()
    fake_apply_mock.assert_called_once()
    fake_remotion.assert_not_called()


def test_remotion_backend_calls_compose_video_remotion(
    overlay_ts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OVERLAY_BACKEND=remotion 時に compositor_remotion.compose_video_remotion が呼ばれ、
    ffmpeg compositor は呼ばれない。"""

    monkeypatch.setattr("config.OVERLAY_BACKEND", "remotion")

    overlaid = overlay_ts / "overlaid.mp4"

    def fake_remotion(scene_videos, screenplay, ts_path, output_path, **kwargs):
        # output (= overlaid.mp4) を実際に作る
        Path(output_path).write_bytes(b"REMOTION_OUTPUT")
        return output_path

    fake_merge = MagicMock()
    fake_apply = MagicMock()
    monkeypatch.setattr(staged_pipeline, "_merge_scenes", fake_merge)
    monkeypatch.setattr(staged_pipeline, "_apply_overlays", fake_apply)

    with patch(
        "compositor_remotion.compose_video_remotion",
        side_effect=fake_remotion,
    ) as fake_compose:
        staged_pipeline.run_overlay(
            _minimal_screenplay(), "test_screenplay", str(overlay_ts)
        )

    # remotion が呼ばれた
    fake_compose.assert_called_once()
    args, kwargs = fake_compose.call_args
    # 引数: scene_videos, screenplay, ts_path, overlaid_path
    assert isinstance(args[0], list)
    assert args[0][0].endswith("scene_000.mp4")
    assert args[2] == str(overlay_ts)
    assert args[3] == str(overlaid)

    # ffmpeg side は呼ばれない
    fake_merge.assert_not_called()
    fake_apply.assert_not_called()

    # output mp4 が config.OUTPUT_DIR にコピーされている
    expected = Path(staged_pipeline.config.OUTPUT_DIR) / "reels_20260510_120000.mp4"
    assert expected.exists()
    assert expected.read_bytes() == b"REMOTION_OUTPUT"


def test_remotion_backend_failure_cleans_up_artifacts(
    overlay_ts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """remotion 経路が例外を投げると merged/overlaid/output の partial が掃除される。"""

    monkeypatch.setattr("config.OVERLAY_BACKEND", "remotion")

    def failing_remotion(*args, **kwargs):
        # ファイルだけ書いておいて失敗
        Path(args[3]).write_bytes(b"PARTIAL")
        raise RuntimeError("remotion blew up")

    with patch(
        "compositor_remotion.compose_video_remotion",
        side_effect=failing_remotion,
    ):
        with pytest.raises(RuntimeError, match="remotion blew up"):
            staged_pipeline.run_overlay(
                _minimal_screenplay(), "test_screenplay", str(overlay_ts)
            )

    # 失敗時 cleanup により overlaid.mp4 / output mp4 は消える
    overlaid = overlay_ts / "overlaid.mp4"
    expected = Path(staged_pipeline.config.OUTPUT_DIR) / "reels_20260510_120000.mp4"
    assert not overlaid.exists()
    assert not expected.exists()
