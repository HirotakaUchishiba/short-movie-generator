"""``GET /api/projects/<TS>/render-plan`` の統合テスト。

設計 doc: docs/plannings/2026-05-10_compositional-architecture.md §3-A
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


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
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db

    _db.init_db()
    sp_dir = tmp_path / "screenplays"
    sp_dir.mkdir(parents=True)
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True)
    import config as _cfg
    import staged_pipeline

    monkeypatch.setattr(_cfg, "SCREENPLAYS_DIR", str(sp_dir))
    monkeypatch.setattr(_cfg, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(staged_pipeline.config, "SCREENPLAYS_DIR", str(sp_dir))
    return {"tmp_path": tmp_path, "sp_dir": sp_dir, "temp_dir": temp_dir}


@pytest.fixture
def client(isolated_env: dict, monkeypatch: pytest.MonkeyPatch):
    import preview_server

    monkeypatch.setattr(preview_server, "TEMP_DIR", str(isolated_env["temp_dir"]))
    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


def _make_project_with_scenes(
    isolated_env: dict,
    ts: str,
    screenplay: dict,
    scene_count: int,
) -> Path:
    """project + N 個の dummy scene_<S>.mp4 を作る。"""

    import staged_pipeline

    ts_path = isolated_env["temp_dir"] / ts
    ts_path.mkdir(parents=True, exist_ok=True)
    staged_pipeline.run_script(screenplay, "test.json", str(ts_path))
    for i in range(scene_count):
        _make_dummy_video(ts_path / f"scene_{i:03d}.mp4", duration_sec=2.0)
    return ts_path


# ───────────── happy path ─────────────


def test_returns_render_plan_when_scenes_ready(
    isolated_env: dict, client
) -> None:
    sp = {
        "caption": "test\n#tag",
        "scenes": [
            {
                "duration": 2.0,
                "background_prompt": "x",
                "lines": [{"text": "シーン1", "start": 0.0, "end": 1.0}],
            },
            {
                "duration": 2.0,
                "background_prompt": "y",
                "lines": [{"text": "シーン2", "start": 0.0, "end": 1.0}],
            },
        ],
    }
    _make_project_with_scenes(isolated_env, "20260510_120000", sp, scene_count=2)

    resp = client.get("/api/projects/20260510_120000/render-plan")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "plan" in data
    plan = data["plan"]

    # video meta
    assert plan["video"]["width"] == 1080
    assert plan["video"]["height"] == 1920
    assert plan["video"]["fps"] == 60
    assert plan["video"]["duration_frames"] == 240  # 2s × 2 scenes × 60fps

    # scenes
    assert len(plan["scenes"]) == 2
    # scene_video_path は http URL に書き換えられている
    for s in plan["scenes"]:
        assert s["scene_video_path"].startswith("http://")
        assert "/asset/20260510_120000/" in s["scene_video_path"]
        assert s["scene_video_path"].endswith(".mp4")
    # subtitle_lines が乗っている
    assert len(plan["scenes"][0]["subtitle_lines"]) == 1
    # template default
    assert plan["template"] == "base"


def test_invalid_ts_format_returns_400(client) -> None:
    resp = client.get("/api/projects/..%2Fevil/render-plan")
    assert resp.status_code in (400, 404)


def test_missing_project_returns_404(isolated_env: dict, client) -> None:
    resp = client.get("/api/projects/nonexistent_ts/render-plan")
    assert resp.status_code == 404


def test_returns_409_when_scenes_not_ready(
    isolated_env: dict, client
) -> None:
    """Stage 5 完了前 (= scene_<S>.mp4 無し) は 409 を返す。"""

    import staged_pipeline

    sp = {
        "caption": "x",
        "scenes": [
            {
                "duration": 2.0,
                "background_prompt": "x",
                "lines": [{"text": "x", "start": 0, "end": 1}],
            }
        ],
    }
    ts_path = isolated_env["temp_dir"] / "20260510_999999"
    ts_path.mkdir(parents=True)
    staged_pipeline.run_script(sp, "t.json", str(ts_path))
    # scene_<S>.mp4 を作らない

    resp = client.get("/api/projects/20260510_999999/render-plan")
    assert resp.status_code == 409
    data = resp.get_json()
    assert data["error_code"] == "scene_videos_not_ready"
    assert "Stage 5" in data["message"]
    assert data["missing_scene_indices"] == [0]


def test_returns_409_when_scenes_empty(isolated_env: dict, client) -> None:
    import staged_pipeline

    ts_path = isolated_env["temp_dir"] / "20260510_888888"
    ts_path.mkdir(parents=True)
    staged_pipeline.run_script({"caption": "x", "scenes": [{"duration": 1.0, "background_prompt": "y", "lines": []}]}, "t.json", str(ts_path))
    # screenplay snapshot を空 scenes で書き直す
    sp_path = ts_path / "screenplay.json"
    import json as _json

    sp = _json.loads(sp_path.read_text())
    sp["scenes"] = []
    sp_path.write_text(_json.dumps(sp))

    resp = client.get("/api/projects/20260510_888888/render-plan")
    assert resp.status_code == 409
    data = resp.get_json()
    assert data["error_code"] == "scenes_empty"


def test_subtitle_chunks_have_absolute_timecodes(
    isolated_env: dict, client
) -> None:
    """plan 内の chunk start/end は scene offset 込みの絶対秒であること。"""

    sp = {
        "caption": "x",
        "scenes": [
            {
                "duration": 2.0,
                "background_prompt": "a",
                "lines": [{"text": "セリフ1", "start": 0.0, "end": 1.5}],
            },
            {
                "duration": 2.0,
                "background_prompt": "b",
                "lines": [{"text": "セリフ2", "start": 0.0, "end": 1.5}],
            },
        ],
    }
    _make_project_with_scenes(isolated_env, "20260510_111111", sp, scene_count=2)
    resp = client.get("/api/projects/20260510_111111/render-plan")
    assert resp.status_code == 200
    plan = resp.get_json()["plan"]

    # 1 つ目の scene の字幕は offset 0 から始まる
    assert plan["scenes"][0]["subtitle_lines"][0]["chunks"][0]["start_abs_sec"] >= 0
    # 2 つ目の scene の字幕は scene1 の duration (= 2s) 以降
    assert plan["scenes"][1]["subtitle_lines"][0]["chunks"][0]["start_abs_sec"] >= 2.0


# ───────────── Phase B: pass-through E2E ─────────────
#
# Phase A (PR #157) で `analyze/compose.py:compose_screenplay()` を
# `dict(abstract)` 起点に書き換え、`scene_parts` / `global_parts` /
# `subtitle_y_from_bottom` 等の非派生フィールドを compose 後にも保持する
# ように修正した。以下 3 件は API endpoint 経由で当該フィールドが
# `compositor_remotion.build_render_plan` まで届くことを E2E で保証する。


def test_subtitle_style_in_scene_parts_reaches_render_plan(
    isolated_env: dict, client
) -> None:
    """scene_parts.subtitle_style が render_plan の scenes[i].parts.subtitle_style
    に届くこと。compose で silent strip されないこと (= Phase A の不変条件)。"""

    sp = {
        "caption": "x",
        "scenes": [
            {
                "duration": 2.0,
                "background_prompt": "x",
                "scene_parts": {
                    "subtitle_style": {"id": "karaoke_bold"},
                },
                "lines": [{"text": "シーン1", "start": 0.0, "end": 1.0}],
            },
        ],
    }
    _make_project_with_scenes(isolated_env, "20260510_222222", sp, scene_count=1)

    resp = client.get("/api/projects/20260510_222222/render-plan")
    assert resp.status_code == 200
    plan = resp.get_json()["plan"]

    assert plan["scenes"][0]["parts"]["subtitle_style"]["id"] == "karaoke_bold"


def test_global_parts_reaches_render_plan(
    isolated_env: dict, client
) -> None:
    """global_parts.filter_preset が render_plan の global_parts に届くこと。"""

    sp = {
        "caption": "x",
        "global_parts": {
            "filter_preset": {"id": "warm_cinematic"},
        },
        "scenes": [
            {
                "duration": 2.0,
                "background_prompt": "x",
                "lines": [{"text": "シーン1", "start": 0.0, "end": 1.0}],
            },
        ],
    }
    _make_project_with_scenes(isolated_env, "20260510_333333", sp, scene_count=1)

    resp = client.get("/api/projects/20260510_333333/render-plan")
    assert resp.status_code == 200
    plan = resp.get_json()["plan"]

    assert plan["global_parts"]["filter_preset"]["id"] == "warm_cinematic"


def test_subtitle_y_from_bottom_reaches_render_plan(
    isolated_env: dict, client
) -> None:
    """root の subtitle_y_from_bottom が build_render_plan で
    scenes[i].parts.subtitle_style.params.yFromBottom に流し込まれること。"""

    sp = {
        "caption": "x",
        "subtitle_y_from_bottom": 800,
        "scenes": [
            {
                "duration": 2.0,
                "background_prompt": "x",
                "lines": [{"text": "シーン1", "start": 0.0, "end": 1.0}],
            },
        ],
    }
    _make_project_with_scenes(isolated_env, "20260510_444444", sp, scene_count=1)

    resp = client.get("/api/projects/20260510_444444/render-plan")
    assert resp.status_code == 200
    plan = resp.get_json()["plan"]

    assert (
        plan["scenes"][0]["parts"]["subtitle_style"]["params"]["yFromBottom"] == 800
    )
