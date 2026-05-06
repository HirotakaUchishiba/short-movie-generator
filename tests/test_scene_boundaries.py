"""scene 境界の手動再定義 (apply_scene_boundaries + API) のテスト。

シナリオ:
  TTS 完了後に「scene 0 (3line) + scene 1 (2line)」を「scene 0 (1line) +
  scene 1 (4line)」に再分割する → tts_full.mp3 はそのまま、per-line/per-scene
  file が新 index で再構築される。

実 ElevenLabs / ffmpeg は使わず、_build_audios_from_full を mock してファイル
作成だけ確認する。
"""
import json
import os
from unittest.mock import MagicMock

import pytest

import progress_store
import staged_pipeline


_TWO_SCENE_SP = {
    "caption": "test",
    "scenes": [
        {
            "duration": 6.0,
            "background_prompt": "bg0",
            "animation_prompt": "anim0",
            "lines": [
                {"text": "line A", "start": 0.0, "end": 2.0, "emotion": "中立"},
                {"text": "line B", "start": 2.0, "end": 4.0, "emotion": "中立"},
                {"text": "line C", "start": 4.0, "end": 6.0, "emotion": "中立"},
            ],
        },
        {
            "duration": 4.0,
            "background_prompt": "bg1",
            "animation_prompt": "anim1",
            "lines": [
                {"text": "line D", "start": 0.0, "end": 2.0, "emotion": "中立"},
                {"text": "line E", "start": 2.0, "end": 4.0, "emotion": "中立"},
            ],
        },
    ],
}


@pytest.fixture
def project(tmp_path, monkeypatch) -> str:
    sp_dir = tmp_path / "screenplays"
    sp_dir.mkdir()
    monkeypatch.setattr(staged_pipeline.config, "SCREENPLAYS_DIR", str(sp_dir))
    ts_path = tmp_path / "ts1"
    ts_path.mkdir()
    staged_pipeline.run_script(_TWO_SCENE_SP, "test_template", str(ts_path))
    # TTS 関連 dummy file を撒いておく (cleanup 対象を確認するため)
    for fname in [
        "tts_000_000.mp3", "tts_000_001.mp3", "tts_000_002.mp3",
        "tts_001_000.mp3", "tts_001_001.mp3",
        "audio_000.m4a", "audio_001.m4a",
        "bg_000.png", "bg_001.png",
        "composite_000.png", "composite_001.png",
        "kling_000.mp4", "kling_001.mp4",
        "scene_000.mp4", "scene_001.mp4",
        "scene_000.trim.mp4", "scene_001.trim.mp4",
        "tts_full.mp3", "tts_full.json",
    ]:
        (ts_path / fname).write_bytes(b"x")
    progress_store.mark_generated(str(ts_path), "script")
    progress_store.mark_approved(str(ts_path), "script")
    progress_store.mark_generated(str(ts_path), "tts")
    progress_store.mark_approved(str(ts_path), "tts")
    progress_store.mark_generated(str(ts_path), "bg")
    progress_store.mark_approved(str(ts_path), "bg")
    progress_store.mark_generated(str(ts_path), "kling")
    progress_store.mark_approved(str(ts_path), "kling")
    return str(ts_path)


def _stub_build_audios(monkeypatch, called: list) -> None:
    """_build_audios_from_full は ffmpeg / オーディオ処理を伴うので mock。
    呼び出し時に scene 数だけ tts_*_*.mp3 と audio_*.m4a を作る。
    """
    import scene_gen
    def fake(screenplay, ts_path):
        called.append((screenplay, ts_path))
        for i, scene in enumerate(screenplay.get("scenes") or []):
            for j in range(len(scene.get("lines") or [])):
                p = os.path.join(ts_path, f"tts_{i:03d}_{j:03d}.mp3")
                with open(p, "wb") as f:
                    f.write(b"x")
            with open(os.path.join(ts_path, f"audio_{i:03d}.m4a"), "wb") as f:
                f.write(b"x")
    monkeypatch.setattr(scene_gen, "_build_audios_from_full", fake)


# ─── apply_scene_boundaries ロジック ────────────────────────

def test_apply_regroup_basic(project, monkeypatch) -> None:
    called: list = []
    _stub_build_audios(monkeypatch, called)
    # 5 line 全体を [0, 1] = scene0 (1 line) + scene1 (4 line) に再分割
    res = staged_pipeline.apply_scene_boundaries(project, [0, 1])
    assert res == {"scenes": 2, "lines": 5}
    # snapshot は抽象台本のまま (= background_prompt は焼かれない、
    # start / end / duration も含まれない = SSOT は tts_meta.json)
    abstract = staged_pipeline.load_project_abstract(project)
    assert len(abstract["scenes"]) == 2
    assert [l["text"] for l in abstract["scenes"][0]["lines"]] == ["line A"]
    assert [l["text"] for l in abstract["scenes"][1]["lines"]] == [
        "line B", "line C", "line D", "line E",
    ]
    assert "background_prompt" not in abstract["scenes"][0]
    assert "start" not in abstract["scenes"][1]["lines"][0]  # SSOT 分離
    # tts_meta.json に新 group の timing が書き出されている
    meta = staged_pipeline.load_tts_meta(project)
    assert meta is not None
    assert len(meta["scenes"]) == 2
    # scene 内相対秒に正規化されている (= 各 scene の先頭 line.start = 0)
    assert meta["scenes"][1]["lines"][0]["start"] == 0.0
    # _build_audios_from_full が新構造で呼ばれた
    assert len(called) == 1
    assert len(called[0][0]["scenes"]) == 2


def test_apply_creates_new_scene_indexed_audio_files(project, monkeypatch) -> None:
    called: list = []
    _stub_build_audios(monkeypatch, called)
    staged_pipeline.apply_scene_boundaries(project, [0, 2])
    # 旧 5 個の tts_* と 2 個の audio_* は全削除されたあと、新構造で再作成
    files = sorted(os.listdir(project))
    audio_files = [f for f in files if f.startswith("audio_")]
    tts_files = [
        f for f in files
        if f.startswith("tts_") and f.endswith(".mp3") and f != "tts_full.mp3"
    ]
    # 新 scene 数 = 2, line 数 = 2 / 3
    assert audio_files == ["audio_000.m4a", "audio_001.m4a"]
    assert sorted(tts_files) == [
        "tts_000_000.mp3", "tts_000_001.mp3",
        "tts_001_000.mp3", "tts_001_001.mp3", "tts_001_002.mp3",
    ]


def test_apply_removes_bg_kling_scene_files(project, monkeypatch) -> None:
    _stub_build_audios(monkeypatch, [])
    staged_pipeline.apply_scene_boundaries(project, [0, 3])
    files = set(os.listdir(project))
    # bg / composite / kling / scene 系は全削除されている
    for stale in [
        "bg_000.png", "bg_001.png",
        "composite_000.png", "composite_001.png",
        "kling_000.mp4", "kling_001.mp4",
        "scene_000.mp4", "scene_001.mp4",
        "scene_000.trim.mp4", "scene_001.trim.mp4",
    ]:
        assert stale not in files, f"{stale} が残っている"
    # tts_full は不変 (ElevenLabs 再呼出し回避の核)
    assert "tts_full.mp3" in files
    assert "tts_full.json" in files


def test_apply_progress_reset_correctly(project, monkeypatch) -> None:
    _stub_build_audios(monkeypatch, [])
    staged_pipeline.apply_scene_boundaries(project, [0, 2])
    pg = progress_store.load(project)
    # script: 不変 (= 承認済 維持)
    assert pg["stages"]["script"]["approved_at"] is not None
    # tts: generated 維持、approved だけ解除
    assert pg["stages"]["tts"]["generated_at"] is not None
    assert pg["stages"]["tts"]["approved_at"] is None
    # bg 以降: 全 reset
    for stage in ["bg", "kling", "scene", "overlay"]:
        assert pg["stages"][stage]["generated_at"] is None
        assert pg["stages"][stage]["approved_at"] is None


def test_apply_validates_boundaries_must_start_with_zero(project) -> None:
    with pytest.raises(ValueError, match="0 から始める"):
        staged_pipeline.apply_scene_boundaries(project, [1, 3])


def test_apply_validates_ascending_unique(project) -> None:
    with pytest.raises(ValueError, match="昇順"):
        staged_pipeline.apply_scene_boundaries(project, [0, 3, 2])
    with pytest.raises(ValueError, match="昇順"):
        staged_pipeline.apply_scene_boundaries(project, [0, 2, 2])


def test_apply_validates_in_range(project) -> None:
    # n_lines=5 → 0..4 が有効。5 は範囲外
    with pytest.raises(ValueError, match="範囲外"):
        staged_pipeline.apply_scene_boundaries(project, [0, 5])


def test_apply_one_scene_with_all_lines(project, monkeypatch) -> None:
    """[0] だけ → 全 line が 1 scene にまとまる。"""
    _stub_build_audios(monkeypatch, [])
    res = staged_pipeline.apply_scene_boundaries(project, [0])
    assert res == {"scenes": 1, "lines": 5}
    sp = staged_pipeline.load_project_screenplay(project)
    assert len(sp["scenes"]) == 1
    assert len(sp["scenes"][0]["lines"]) == 5


def test_apply_each_line_own_scene(project, monkeypatch) -> None:
    """全 line が独立 scene になるパターン。"""
    _stub_build_audios(monkeypatch, [])
    res = staged_pipeline.apply_scene_boundaries(project, [0, 1, 2, 3, 4])
    assert res == {"scenes": 5, "lines": 5}
    sp = staged_pipeline.load_project_screenplay(project)
    assert all(len(s["lines"]) == 1 for s in sp["scenes"])


# ─── REST API ─────────────────────────────────────────────────

@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    from analytics import db as _db
    _db.init_db()
    sp_dir = tmp_path / "screenplays"
    sp_dir.mkdir(parents=True)
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True)
    import config as _cfg
    monkeypatch.setattr(_cfg, "SCREENPLAYS_DIR", str(sp_dir))
    monkeypatch.setattr(_cfg, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(staged_pipeline.config, "SCREENPLAYS_DIR", str(sp_dir))
    return {"sp_dir": sp_dir, "temp_dir": temp_dir}


@pytest.fixture
def client(isolated_env, monkeypatch):
    import preview_server
    monkeypatch.setattr(preview_server, "TEMP_DIR", str(isolated_env["temp_dir"]))
    preview_server.app.config["TESTING"] = True
    return preview_server.app.test_client()


def _make_project_via_api(isolated_env) -> str:
    ts = "20260503_010000"
    ts_path = str(isolated_env["temp_dir"] / ts)
    os.makedirs(ts_path)
    staged_pipeline.run_script(_TWO_SCENE_SP, "test_template", ts_path)
    progress_store.mark_generated(ts_path, "script")
    progress_store.mark_approved(ts_path, "script")
    progress_store.mark_generated(ts_path, "tts")
    return ts


def test_api_apply_scene_boundaries(client, isolated_env, monkeypatch) -> None:
    _stub_build_audios(monkeypatch, [])
    ts = _make_project_via_api(isolated_env)
    r = client.post(
        f"/api/projects/{ts}/scene-boundaries",
        json={"line_boundaries": [0, 2]},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body == {"ok": True, "scenes": 2, "lines": 5}


def test_api_400_for_invalid_payload(client, isolated_env) -> None:
    ts = _make_project_via_api(isolated_env)
    r = client.post(
        f"/api/projects/{ts}/scene-boundaries",
        json={"line_boundaries": "not a list"},
    )
    assert r.status_code == 400


def test_api_400_when_boundaries_dont_start_with_zero(
    client, isolated_env, monkeypatch,
) -> None:
    _stub_build_audios(monkeypatch, [])
    ts = _make_project_via_api(isolated_env)
    r = client.post(
        f"/api/projects/{ts}/scene-boundaries",
        json={"line_boundaries": [1, 3]},
    )
    assert r.status_code == 400


def test_api_404_for_unknown_project(client) -> None:
    r = client.post(
        "/api/projects/29991231_000000/scene-boundaries",
        json={"line_boundaries": [0]},
    )
    assert r.status_code == 404
