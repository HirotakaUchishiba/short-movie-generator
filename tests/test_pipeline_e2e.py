"""段階的パイプライン全体の orchestration を mock 経由で smoke 検証する。

外部 API (ElevenLabs / Imagen / FAL Kling / lipsync) と重い ffmpeg
処理 (compose / overlay) はすべて scene_gen / compositor 関数の差し替えで
スタブする。検証対象は:

    - 各 stage を順番に実行できる (= run_next_stage が dispatch する)
    - 承認なしでは次 stage が起動できない (= ゲート機能が効いている)
    - 各 stage 完了で progress_store.is_generated が True になる
    - overlay 完了で output/reels_<TS>.mp4 と post_caption が出力される
    - final_import が EXTERNAL_ACTION_STAGES として run_next_stage から除外される
"""
import json
import os
import subprocess

import pytest

import config
import progress_store
import scene_gen
import staged_pipeline


def _make_silent_mp3(path: str, duration: float = 0.5) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        "-t", f"{duration:.3f}",
        "-c:a", "libmp3lame", "-q:a", "9",
        path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _make_silent_aac(path: str, duration: float = 0.5) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", f"{duration:.3f}",
        "-c:a", "aac", "-b:a", "64k",
        path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _make_tiny_png(path: str) -> None:
    from PIL import Image
    img = Image.new("RGB", (108, 192), color=(20, 20, 20))
    img.save(path, "PNG")


def _make_tiny_mp4(path: str, duration: float = 0.5) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=black:s=108x192:d={duration:.3f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """temp_dir / output_dir / post_captions_dir を tmp に向ける。"""
    temp_dir = tmp_path / "temp"
    sp_dir = tmp_path / "screenplays"
    out_dir = tmp_path / "output"
    cap_dir = tmp_path / "post_captions"
    for d in (temp_dir, sp_dir, out_dir, cap_dir):
        d.mkdir()
    monkeypatch.setattr(config, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(config, "SCREENPLAYS_DIR", str(sp_dir))
    monkeypatch.setattr(config, "OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr(config, "POST_CAPTIONS_DIR", str(cap_dir))
    return {
        "temp": temp_dir, "sp": sp_dir, "out": out_dir, "cap": cap_dir,
    }


@pytest.fixture
def stub_locations(monkeypatch):
    """minimal_screenplay が参照する location を validator が承認するようスタブ。"""
    from analyze import location as loc_mod
    monkeypatch.setattr(loc_mod, "list_locations", lambda: ["home_office"])


@pytest.fixture
def minimal_screenplay():
    return {
        "caption": "テスト用キャプション\n\n#test",
        "scenes": [
            {
                "background_prompt": "test bg 1",
                "animation_prompt": "test motion 1",
                "location_ref": "home_office",
                "lipsync": False,
                "lines": [
                    {"text": "こんにちは", "emotion": "中立"},
                ],
            },
            {
                "background_prompt": "test bg 2",
                "animation_prompt": "test motion 2",
                "location_ref": "home_office",
                "lipsync": False,
                "lines": [
                    {"text": "さようなら", "emotion": "中立"},
                ],
            },
        ],
    }


def _write_template(sp_dir, name: str, body: dict):
    p = sp_dir / f"{name}.json"
    p.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


def _approve_current(ts_path):
    cur = progress_store.current_stage(ts_path)
    if cur and not progress_store.is_approved(ts_path, cur):
        progress_store.mark_approved(ts_path, cur)


def _stub_stage_runners(monkeypatch, ts_path: str, screenplay: dict):
    """scene_gen / compositor の重処理を mock で置換。"""
    n_scenes = len(screenplay["scenes"])

    def fake_tts(sp, temp_dir):
        for s_idx, scene in enumerate(sp["scenes"]):
            duration = 0.5 * (len(scene.get("lines") or []) or 1)
            scene["duration"] = duration
            cumulative = 0.0
            for l_idx, line in enumerate(scene.get("lines") or []):
                line_dur = 0.5
                line["start"] = round(cumulative, 3)
                line["end"] = round(cumulative + line_dur, 3)
                cumulative += line_dur
                _make_silent_mp3(
                    os.path.join(temp_dir, f"tts_{s_idx:03d}_{l_idx:03d}.mp3"),
                    line_dur,
                )
            _make_silent_aac(
                os.path.join(temp_dir, f"audio_{s_idx:03d}.m4a"),
                duration,
            )
        # tts_meta.json も書く (= load_project_screenplay 経由の hydrate 用)
        meta_scenes = []
        for scene in sp["scenes"]:
            ms = {"duration": scene.get("duration", 0.0), "lines": []}
            for line in scene.get("lines") or []:
                ms["lines"].append({
                    "start": line.get("start", 0.0),
                    "end": line.get("end", 0.0),
                })
            meta_scenes.append(ms)
        staged_pipeline.save_tts_meta(temp_dir, {"scenes": meta_scenes})
        return None

    def fake_bg(sp, temp_dir, scene_decisions=None):
        paths = {}
        for s_idx, scene in enumerate(sp["scenes"]):
            bg_key = f"bg_{s_idx:03d}"
            p = os.path.join(temp_dir, f"{bg_key}.png")
            _make_tiny_png(p)
            scene["_bg_key"] = bg_key
            paths[bg_key] = p
        return paths

    def fake_kling(sp, temp_dir, scene_decisions=None):
        for s_idx, scene in enumerate(sp["scenes"]):
            duration = float(scene.get("duration") or 0.5)
            _make_tiny_mp4(
                os.path.join(temp_dir, f"kling_{s_idx:03d}.mp4"), duration,
            )
            _make_tiny_mp4(
                os.path.join(temp_dir, f"scene_{s_idx:03d}.trim.mp4"), duration,
            )

    def fake_assemble(sp, temp_dir):
        out: list[str] = []
        for s_idx, scene in enumerate(sp["scenes"]):
            duration = float(scene.get("duration") or 0.5)
            p = os.path.join(temp_dir, f"scene_{s_idx:03d}.mp4")
            _make_tiny_mp4(p, duration)
            out.append(p)
        return out

    def fake_collect(sp, temp_dir):
        return [
            os.path.join(temp_dir, f"scene_{s_idx:03d}.mp4")
            for s_idx in range(len(sp["scenes"]))
        ]

    def fake_merge(scene_videos, scene_durations, temp_dir):
        merged = os.path.join(temp_dir, "merged.mp4")
        # 単純に最初のシーンファイルをコピーする (= overlay は no-op スタブで回避)
        import shutil as _sh
        _sh.copyfile(scene_videos[0], merged)
        return merged

    def fake_overlay(merged, sp, temp_dir, output_path, scene_videos=None):
        import shutil as _sh
        _sh.copyfile(merged, output_path)

    monkeypatch.setattr(scene_gen, "generate_tts_for_screenplay", fake_tts)
    monkeypatch.setattr(scene_gen, "generate_backgrounds", fake_bg)
    monkeypatch.setattr(
        scene_gen, "generate_kling_for_screenplay", fake_kling)
    monkeypatch.setattr(scene_gen, "assemble_scene_videos", fake_assemble)
    monkeypatch.setattr(scene_gen, "collect_scene_videos", fake_collect)
    monkeypatch.setattr(staged_pipeline, "_merge_scenes", fake_merge)
    monkeypatch.setattr(staged_pipeline, "_apply_overlays", fake_overlay)


def test_pipeline_full_run_through_overlay(
    env, stub_locations, minimal_screenplay, monkeypatch,
):
    """Stage 1 → 7 を順番に走らせて output が出るところまで確認する。"""
    _write_template(env["sp"], "smoke", minimal_screenplay)

    # Stage 1: 新規 project 作成 (run_script)
    ts = "20990101_120000"
    ts_path = os.path.join(str(env["temp"]), ts)
    os.makedirs(ts_path, exist_ok=True)

    template = staged_pipeline.load_template("smoke")
    staged_pipeline.run_script(template, "smoke", ts_path)

    assert progress_store.is_generated(ts_path, "script")
    assert os.path.exists(
        os.path.join(ts_path, staged_pipeline.PROJECT_SCREENPLAY_FILENAME))

    _stub_stage_runners(monkeypatch, ts_path, template)

    # Stage 2-7 の順次実行 (各 stage の前に approve)
    expected_order = ["tts", "bg", "kling", "scene", "overlay"]
    for expected in expected_order:
        progress_store.mark_approved(ts_path, progress_store.current_stage(ts_path))
        sp = staged_pipeline.load_project_screenplay(ts_path)
        executed = staged_pipeline.run_next_stage(sp, "smoke", ts_path)
        assert executed == expected, (
            f"想定: {expected}, 実行: {executed}, "
            f"progress={progress_store.load(ts_path)}"
        )
        assert progress_store.is_generated(ts_path, expected)

    # Stage 7 完了 → pipeline raw + caption が出力ディレクトリに揃う
    assert os.path.exists(
        os.path.join(str(env["out"]), f"reels_{ts}.mp4"))
    assert os.path.exists(
        os.path.join(str(env["cap"]), "smoke.md"))


def test_run_next_stage_blocks_on_unapproved(
    env, stub_locations, minimal_screenplay,
):
    """前 stage を承認していなければ次 stage が起動しない (= ゲート)。"""
    _write_template(env["sp"], "smoke", minimal_screenplay)
    ts = "20990101_130000"
    ts_path = os.path.join(str(env["temp"]), ts)
    os.makedirs(ts_path, exist_ok=True)

    template = staged_pipeline.load_template("smoke")
    staged_pipeline.run_script(template, "smoke", ts_path)
    assert progress_store.is_generated(ts_path, "script")

    # script を承認していないので next_stage は None (= 何も走らない)
    sp = staged_pipeline.load_project_screenplay(ts_path)
    result = staged_pipeline.run_next_stage(sp, "smoke", ts_path)
    assert result is None
    assert not progress_store.is_generated(ts_path, "tts")


def test_run_next_stage_skips_external_action_stages(
    env, stub_locations, minimal_screenplay, monkeypatch,
):
    """Stage 7 (final_import) は run_next_stage から除外される。"""
    _write_template(env["sp"], "smoke", minimal_screenplay)
    ts = "20990101_140000"
    ts_path = os.path.join(str(env["temp"]), ts)
    os.makedirs(ts_path, exist_ok=True)

    template = staged_pipeline.load_template("smoke")
    staged_pipeline.run_script(template, "smoke", ts_path)
    _stub_stage_runners(monkeypatch, ts_path, template)

    for _ in range(5):  # tts → bg → kling → scene → overlay
        progress_store.mark_approved(
            ts_path, progress_store.current_stage(ts_path))
        sp = staged_pipeline.load_project_screenplay(ts_path)
        staged_pipeline.run_next_stage(sp, "smoke", ts_path)

    # overlay まで生成完了。承認しても final_import は EXTERNAL_ACTION で除外
    progress_store.mark_approved(ts_path, "overlay")
    sp = staged_pipeline.load_project_screenplay(ts_path)
    result = staged_pipeline.run_next_stage(sp, "smoke", ts_path)
    assert result is None
    assert not progress_store.is_generated(ts_path, "final_import")
