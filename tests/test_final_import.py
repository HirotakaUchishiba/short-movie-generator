import json
import shutil
import subprocess
from pathlib import Path

import pytest

import config
import progress_store
from final_import import core as fi


def _make_overlay_approved_project(tmp_path: Path, ts: str) -> Path:
    """`temp/<ts>/` を作って overlay まで承認済みの状態にする。"""
    temp_dir = tmp_path / "temp" / ts
    temp_dir.mkdir(parents=True)
    (temp_dir / "metadata.json").write_text(json.dumps({
        "screenplay_name": "x.json",
        "screenplay_path": "screenplay.json",
        "screenplay_sha256": "x" * 64,
        "created_at": "2026-05-06T00:00:00",
    }))
    for s in ["script", "tts", "bg", "kling", "scene", "overlay"]:
        progress_store.mark_generated(str(temp_dir), s)
        progress_store.mark_approved(str(temp_dir), s)
    return temp_dir


def _make_dummy_mp4(path: Path, duration: float = 1.0) -> None:
    """ffmpeg で短い無音 mp4 を生成する。"""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=black:s=64x64:d={duration}",
        "-f", "lavfi", "-i", f"anullsrc=cl=mono:r=8000:d={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


pytestmark = pytest.mark.skipif(
    not _ffmpeg_available(),
    reason="ffmpeg/ffprobe が必要なテスト",
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path / "output"))
    Path(config.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    ts = "20260506_120000"
    ts_path = _make_overlay_approved_project(tmp_path, ts)
    return ts, str(ts_path)


def test_progress_store_has_new_stages():
    assert "final_import" in progress_store.STAGES
    assert "publish" in progress_store.STAGES
    assert "final_import" in progress_store.EXTERNAL_ACTION_STAGES
    assert "publish" in progress_store.EXTERNAL_ACTION_STAGES


def test_import_final_creates_canonical(project, tmp_path):
    ts, ts_path = project
    src = tmp_path / "capcut.mp4"
    _make_dummy_mp4(src, duration=2.0)

    v = fi.import_final(ts, src)
    assert v.is_canonical is True
    assert v.size_bytes > 0
    assert v.duration_sec is not None and v.duration_sec > 0
    assert v.source == "cli"

    final_d = fi.final_dir(ts_path)
    assert (final_d / v.filename).exists()
    assert progress_store.is_generated(ts_path, "final_import")


def test_import_final_requires_overlay_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path / "output"))
    ts = "20260506_130000"
    ts_path = tmp_path / "temp" / ts
    ts_path.mkdir(parents=True)
    (ts_path / "metadata.json").write_text("{}")
    src = tmp_path / "x.mp4"
    _make_dummy_mp4(src, duration=1.0)
    with pytest.raises(RuntimeError, match="字幕"):
        fi.import_final(ts, src)


def test_import_final_rejects_unknown_extension(project, tmp_path):
    ts, _ = project
    src = tmp_path / "weird.mkv"
    src.write_bytes(b"x")
    with pytest.raises(ValueError, match="unsupported"):
        fi.import_final(ts, src)


def test_import_final_rejects_text_renamed_to_mp4(project, tmp_path):
    """拡張子だけ .mp4 にしたテキストは ftyp atom が無いので reject される。"""
    ts, _ = project
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"this is not a real video file")
    with pytest.raises(ValueError, match="ftyp atom missing"):
        fi.import_final(ts, src)


def test_has_mp4_ftyp_atom_recognizes_mp4(tmp_path):
    src = tmp_path / "ok.mp4"
    # 最小の ftyp box header (size=20, type='ftyp', major='isom', minor=0)
    src.write_bytes(
        bytes.fromhex("00000020") + b"ftyp" + b"isom" + bytes(8)
    )
    assert fi.has_mp4_ftyp_atom(src) is True


def test_has_mp4_ftyp_atom_rejects_non_mp4(tmp_path):
    src = tmp_path / "no.mp4"
    src.write_bytes(b"PNG\x89random")
    assert fi.has_mp4_ftyp_atom(src) is False


def test_import_final_multiple_versions_canonical_is_latest(project, tmp_path):
    ts, ts_path = project
    src1 = tmp_path / "a.mp4"
    src2 = tmp_path / "b.mp4"
    _make_dummy_mp4(src1, duration=1.0)
    _make_dummy_mp4(src2, duration=2.0)

    v1 = fi.import_final(ts, src1)
    v2 = fi.import_final(ts, src2)
    assert v1.filename != v2.filename

    versions = fi.list_final_versions(ts_path)
    assert len(versions) == 2
    canonical_filenames = [v.filename for v in versions if v.is_canonical]
    assert canonical_filenames == [v2.filename]


def test_import_final_resets_approval_on_new_version(project, tmp_path):
    ts, ts_path = project
    src1 = tmp_path / "a.mp4"
    _make_dummy_mp4(src1, duration=1.0)
    fi.import_final(ts, src1)
    progress_store.mark_approved(ts_path, "final_import")
    assert progress_store.is_approved(ts_path, "final_import")

    src2 = tmp_path / "b.mp4"
    _make_dummy_mp4(src2, duration=2.0)
    fi.import_final(ts, src2)
    assert not progress_store.is_approved(ts_path, "final_import")


def test_set_canonical_final(project, tmp_path):
    ts, ts_path = project
    src1 = tmp_path / "a.mp4"
    src2 = tmp_path / "b.mp4"
    _make_dummy_mp4(src1)
    _make_dummy_mp4(src2)
    v1 = fi.import_final(ts, src1)
    fi.import_final(ts, src2)

    fi.set_canonical_final(ts_path, v1.filename)
    canonical = [v for v in fi.list_final_versions(ts_path) if v.is_canonical]
    assert len(canonical) == 1
    assert canonical[0].filename == v1.filename


def test_delete_canonical_promotes_latest_remaining(project, tmp_path):
    ts, ts_path = project
    src1 = tmp_path / "a.mp4"
    src2 = tmp_path / "b.mp4"
    _make_dummy_mp4(src1)
    _make_dummy_mp4(src2)
    v1 = fi.import_final(ts, src1)
    v2 = fi.import_final(ts, src2)
    assert v2.is_canonical

    fi.delete_final_version(ts_path, v2.filename)
    versions = fi.list_final_versions(ts_path)
    assert len(versions) == 1
    assert versions[0].filename == v1.filename
    assert versions[0].is_canonical


def test_delete_all_resets_progress(project, tmp_path):
    ts, ts_path = project
    src = tmp_path / "a.mp4"
    _make_dummy_mp4(src)
    v = fi.import_final(ts, src)
    assert progress_store.is_generated(ts_path, "final_import")

    fi.delete_final_version(ts_path, v.filename)
    assert not progress_store.is_generated(ts_path, "final_import")


def test_resolve_canonical_falls_back_to_pipeline_raw(project, tmp_path):
    ts, ts_path = project
    raw = Path(config.OUTPUT_DIR) / f"reels_{ts}.mp4"
    raw.write_bytes(b"fake")
    resolved = fi.resolve_canonical_video(ts_path)
    assert resolved == raw


def test_resolve_canonical_prefers_final(project, tmp_path):
    ts, ts_path = project
    raw = Path(config.OUTPUT_DIR) / f"reels_{ts}.mp4"
    raw.write_bytes(b"fake")
    src = tmp_path / "capcut.mp4"
    _make_dummy_mp4(src)
    v = fi.import_final(ts, src)
    resolved = fi.resolve_canonical_video(ts_path)
    assert resolved.name == v.filename
    assert resolved.parent == fi.final_dir(ts_path)


# ─── P1 fix tests ─────────────────────────────────────────────────


def test_imported_filenames_are_safe_for_api_regex(project, tmp_path):
    """API 側の `^[\\w\\.\\-]+$` を必ず通る命名に揃っていること."""
    import re as _re
    ts, ts_path = project
    src = tmp_path / "My Final Cut Pro Export.mov"
    _make_dummy_mp4(src)
    v = fi.import_final(ts, src)
    assert _re.match(r"^[\w\.\-]+$", v.filename), v.filename
    # 拡張子は元と一致 (.mov)
    assert v.filename.endswith(".mov")


def test_existing_final_path_is_renamed_in_place(project, tmp_path):
    """final/ 内に既にあるファイルは safe name に in-place rename される."""
    import re as _re
    ts, ts_path = project
    final_d = fi.ensure_final_dir(ts_path)
    drop = final_d / "out with space.mp4"
    src = tmp_path / "raw.mp4"
    _make_dummy_mp4(src)
    shutil.copyfile(src, drop)
    v = fi.import_final(ts, drop)
    assert _re.match(r"^[\w\.\-]+$", v.filename)
    assert (final_d / v.filename).exists()
    # 元の "out with space.mp4" は in-place rename で消えている
    assert not drop.exists()


def test_dropping_same_filename_creates_distinct_versions(project, tmp_path):
    """同じ ``out.mp4`` を 2 回入れても history に同名が並ばない."""
    ts, ts_path = project
    src1 = tmp_path / "out.mp4"
    src2 = tmp_path / "x" / "out.mp4"
    src2.parent.mkdir()
    _make_dummy_mp4(src1, duration=1.0)
    _make_dummy_mp4(src2, duration=2.0)
    v1 = fi.import_final(ts, src1)
    v2 = fi.import_final(ts, src2)
    assert v1.filename != v2.filename
    versions = fi.list_final_versions(ts_path)
    filenames = [v.filename for v in versions]
    assert len(filenames) == len(set(filenames))


def test_set_canonical_resets_publish_progress(project, tmp_path):
    """canonical を切替えると Stage 8 (publish) の generated/approved が消える."""
    ts, ts_path = project
    src1 = tmp_path / "a.mp4"
    src2 = tmp_path / "b.mp4"
    _make_dummy_mp4(src1)
    _make_dummy_mp4(src2)
    v1 = fi.import_final(ts, src1)
    v2 = fi.import_final(ts, src2)
    # 両 stage を承認 + publish 履歴にも 1 件足す
    progress_store.mark_approved(ts_path, "final_import")
    progress_store.mark_generated(ts_path, "publish")
    progress_store.mark_approved(ts_path, "publish")

    fi.set_canonical_final(ts_path, v1.filename)

    assert not progress_store.is_approved(ts_path, "final_import")
    assert not progress_store.is_generated(ts_path, "publish")
    assert not progress_store.is_approved(ts_path, "publish")


def test_set_canonical_noop_keeps_progress(project, tmp_path):
    """同じ canonical を再指定しても (= 変化なし) 既存承認は破棄しない."""
    ts, ts_path = project
    src = tmp_path / "a.mp4"
    _make_dummy_mp4(src)
    v = fi.import_final(ts, src)
    progress_store.mark_approved(ts_path, "final_import")

    fi.set_canonical_final(ts_path, v.filename)
    # 取込時点で既に承認済みなので、no-op 切替なら approval は残る
    assert progress_store.is_approved(ts_path, "final_import")


def test_delete_canonical_resets_publish(project, tmp_path):
    """canonical を削除 → 別バージョンが昇格すると publish もリセット."""
    ts, ts_path = project
    src1 = tmp_path / "a.mp4"
    src2 = tmp_path / "b.mp4"
    _make_dummy_mp4(src1)
    _make_dummy_mp4(src2)
    v1 = fi.import_final(ts, src1)
    v2 = fi.import_final(ts, src2)
    progress_store.mark_approved(ts_path, "final_import")
    progress_store.mark_generated(ts_path, "publish")
    progress_store.mark_approved(ts_path, "publish")

    fi.delete_final_version(ts_path, v2.filename)

    assert not progress_store.is_approved(ts_path, "final_import")
    assert not progress_store.is_generated(ts_path, "publish")


def test_delete_non_canonical_keeps_progress(project, tmp_path):
    """canonical でないバージョンを削除しても publish 承認はそのまま."""
    ts, ts_path = project
    src1 = tmp_path / "a.mp4"
    src2 = tmp_path / "b.mp4"
    _make_dummy_mp4(src1)
    _make_dummy_mp4(src2)
    v1 = fi.import_final(ts, src1)
    v2 = fi.import_final(ts, src2)  # canonical
    progress_store.mark_approved(ts_path, "final_import")
    progress_store.mark_generated(ts_path, "publish")
    progress_store.mark_approved(ts_path, "publish")

    fi.delete_final_version(ts_path, v1.filename)

    assert progress_store.is_approved(ts_path, "final_import")
    assert progress_store.is_approved(ts_path, "publish")
