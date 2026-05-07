"""final_import.publish の end-to-end フロー (network mock + analytics DB)。"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


pytestmark = pytest.mark.skipif(
    not _ffmpeg_available(), reason="ffmpeg/ffprobe required",
)


def _make_dummy_mp4(path: Path, duration: float = 1.0) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=black:s=64x64:d={duration}",
        "-f", "lavfi", "-i", f"anullsrc=cl=mono:r=8000:d={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


@pytest.fixture
def project(tmp_path, monkeypatch):
    import config
    import progress_store

    monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(config, "POST_CAPTIONS_DIR", str(tmp_path / "post_captions"))
    Path(config.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.POST_CAPTIONS_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))

    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "ref")

    ts = "20260506_140000"
    ts_path = Path(config.TEMP_DIR) / ts
    ts_path.mkdir(parents=True)
    (ts_path / "metadata.json").write_text(json.dumps({
        "screenplay_name": "demo.json",
        "screenplay_path": "screenplay.json",
        "screenplay_sha256": "x" * 64,
        "created_at": "2026-05-06T00:00:00",
    }))
    # screenplay snapshot は publish の caption fallback に必要
    (ts_path / "screenplay.json").write_text(json.dumps({
        "caption": "テストキャプション\n#tag1 #tag2",
        "scenes": [{"lines": [{"text": "a"}]}],
    }))

    for s in ["script", "tts", "bg", "kling", "scene", "overlay"]:
        progress_store.mark_generated(str(ts_path), s)
        progress_store.mark_approved(str(ts_path), s)

    # post_captions/<title>.md
    cap_md = Path(config.POST_CAPTIONS_DIR) / "demo.md"
    cap_md.write_text("# demo\n\n本文テスト\n#hello #world\n\n## 動画ファイル\n- `/x.mp4`\n")

    # CapCut 出力相当のファイルを Stage 7 取込
    src = tmp_path / "capcut.mp4"
    _make_dummy_mp4(src, duration=2.0)
    from final_import import core as fi
    fi.import_final(ts, src, source="cli", skip_fingerprint=True)
    progress_store.mark_approved(str(ts_path), "final_import")
    return ts, str(ts_path)


class _MockResp:
    def __init__(self, status_code, json_data=None, headers=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def test_publish_youtube_calls_upload_and_registers_post(project, monkeypatch):
    from final_import.publish import publish
    from analytics import db as analytics_db
    import progress_store

    ts, ts_path = project

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "tok"})
        return _MockResp(200, headers={"Location": "https://up/"})

    def fake_put(url, **kw):
        return _MockResp(200, json_data={"id": "yt_xyz"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    result = publish(ts, "youtube", privacy="unlisted")
    assert result["platform"] == "youtube"
    assert result["video_id"] == "yt_xyz"
    assert "shorts/yt_xyz" in result["url"]
    assert result["manual"] is False

    # progress_store: publish が generated に
    assert progress_store.is_generated(ts_path, "publish")

    # analytics DB: posts に登録されている
    posts = analytics_db.list_active_posts(platform="youtube")
    assert any(p["platform_post_id"] == "yt_xyz" for p in posts)

    # metadata.json に published_posts が積まれている
    meta = json.loads((Path(ts_path) / "metadata.json").read_text())
    assert any(p["video_id"] == "yt_xyz" for p in meta["published_posts"])


def test_publish_blocked_when_stage8_unapproved(project, monkeypatch):
    import progress_store
    from final_import.publish import publish

    ts, ts_path = project
    # stage 7 を未承認に戻す
    prog = progress_store.load(ts_path)
    prog["stages"]["final_import"]["approved_at"] = None
    progress_store.save(ts_path, prog)

    with pytest.raises(RuntimeError, match="取込"):
        publish(ts, "youtube")


def test_publish_instagram_semi_auto(project, monkeypatch):
    import sys
    from final_import.publish import publish

    ts, ts_path = project
    calls: list[list[str]] = []

    def fake_run(args, **kw):
        calls.append(list(args))

        class R:
            returncode = 0
            stdout = b""
            stderr = b""
        return R()

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("subprocess.run", fake_run)

    result = publish(ts, "instagram")
    assert result["manual"] is True
    assert result["platform"] == "instagram"
    assert result["manual_status"]["clipboard"] is True
    assert result["manual_status"]["app_opened"] is True
    # pbcopy + open のいずれかが呼ばれたこと
    assert any(c[0] == "pbcopy" for c in calls)
    assert any(c[0] == "open" for c in calls)


def test_publish_semi_auto_falls_back_to_finder_reveal_on_app_failure(
    project, monkeypatch,
):
    """`open -a Instagram` が失敗 (アプリ未インストール等) → Finder reveal にフォールバック."""
    import sys
    from final_import.publish import publish

    ts, _ts_path = project
    calls: list[list[str]] = []

    def fake_run(args, **kw):
        calls.append(list(args))

        class R:
            returncode = 0
            stdout = b""
            stderr = b""

        # `open -a Instagram <video>` だけ失敗、他は成功
        if len(args) >= 3 and args[0] == "open" and args[1] == "-a":
            R.returncode = 1
            R.stderr = b"app not found"
        return R()

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("subprocess.run", fake_run)

    result = publish(ts, "instagram")
    assert result["manual_status"]["clipboard"] is True
    assert result["manual_status"]["app_opened"] is False
    assert result["manual_status"]["finder_revealed"] is True
    # pbcopy + open -a + open -R 全部呼ばれた
    assert any(c[:2] == ["open", "-a"] for c in calls)
    assert any(c[:2] == ["open", "-R"] for c in calls)


def test_publish_semi_auto_raises_when_everything_fails(project, monkeypatch):
    """clipboard / open -a / open -R 全滅なら RuntimeError で job failure."""
    import sys
    from final_import.publish import publish

    ts, ts_path = project

    def fake_run(args, **kw):
        class R:
            returncode = 99
            stdout = b""
            stderr = b"all failing"
        return R()

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="すべてが失敗"):
        publish(ts, "tiktok")

    # C2: 全失敗でも metadata に failed=True エントリが残る
    meta = json.loads((Path(ts_path) / "metadata.json").read_text())
    posts = meta.get("published_posts") or []
    failed = [p for p in posts if p.get("platform") == "tiktok"]
    assert len(failed) == 1
    assert failed[0]["failed"] is True
    assert "diagnostics" in failed[0].get("failure_reason", "")
    # progress_store: publish は generated に進めない
    import progress_store
    assert not progress_store.is_generated(ts_path, "publish")


def test_publish_semi_auto_success_when_only_clipboard_works(project, monkeypatch):
    """clipboard だけ成功でも (= 何かはユーザに渡せた) job 成功扱い."""
    import sys
    from final_import.publish import publish

    ts, _ts_path = project

    def fake_run(args, **kw):
        class R:
            returncode = 0 if args[0] == "pbcopy" else 1
            stdout = b""
            stderr = b"app/finder failed"
        return R()

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("subprocess.run", fake_run)

    result = publish(ts, "instagram")
    assert result["manual_status"]["clipboard"] is True
    assert result["manual_status"]["app_opened"] is False
    assert result["manual_status"]["finder_revealed"] is False


def test_publish_updates_existing_raw_video_row(project, monkeypatch):
    """既に raw で ingest 済みの video を canonical final 情報で UPDATE する.

    publish 自体は YouTube だが、_ensure_video_in_analytics の挙動を確認するため
    YouTube upload は mock。"""
    from final_import.publish import publish
    from analytics import db as analytics_db

    ts, ts_path = project

    # 1) raw で ingest 済みの状態を作る (= scripts/ingest_video.py 相当)
    analytics_db.init_db()
    sp_id = analytics_db.upsert_screenplay(f"{ts_path}/screenplay.json")
    raw_path = f"/tmp/old_raw_{ts}.mp4"
    analytics_db.insert_video(
        video_id=ts, screenplay_id=sp_id,
        output_path=raw_path, duration_sec=20.0,
        generation_cost_usd=18.5,
        final_imported=False, final_filename=None,
    )

    # 2) YouTube upload を mock
    class _R:
        status_code = 200
        text = ""
        headers = {"Location": "https://up/"}

        def __init__(self, json_data=None):
            self._j = json_data

        def json(self):
            return self._j

        def raise_for_status(self):
            pass

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _R(json_data={"access_token": "tok"})
        return _R()

    def fake_put(url, **kw):
        r = _R()
        r._j = {"id": "yt_after_final"}
        return r

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    publish(ts, "youtube", privacy="unlisted")

    # 3) videos 行が canonical final で UPDATE されている
    with analytics_db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM videos WHERE id = ?", (ts,),
        ).fetchone()
    assert row["final_imported"] == 1
    assert row["final_filename"] is not None
    # output_path は raw でなく canonical final になっている
    assert "/final/" in row["output_path"]
    assert row["output_path"] != raw_path
    # generation_cost_usd / screenplay_id は保持される (UPDATE で触らないため)
    assert row["generation_cost_usd"] == 18.5
    assert row["screenplay_id"] == sp_id


def test_update_video_final_preserves_other_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "a.db"))
    from analytics import db as _db
    _db.init_db()
    sp_id = "x" * 12
    with _db.get_connection() as conn:
        conn.execute(
            """INSERT INTO screenplays
               (id, path, name, sha256, created_at, raw_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sp_id, "/x", "x", "x" * 64, "2026-05-06T00:00:00", "{}"),
        )
    _db.insert_video(
        video_id="v1", screenplay_id=sp_id,
        output_path="/raw.mp4", duration_sec=10.0,
        generation_cost_usd=12.3,
    )
    updated = _db.update_video_final(
        video_id="v1", output_path="/final/142233.mp4",
        duration_sec=15.0, final_imported=True,
        final_filename="142233.mp4", final_audio_match_score=0.92,
    )
    assert updated is True
    with _db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM videos WHERE id = 'v1'"
        ).fetchone()
    assert row["final_imported"] == 1
    assert row["final_filename"] == "142233.mp4"
    assert row["duration_sec"] == 15.0
    assert row["output_path"].endswith("/final/142233.mp4")
    # 触らないカラム
    assert row["generation_cost_usd"] == 12.3
    assert row["screenplay_id"] == sp_id


def test_update_video_final_returns_false_for_missing_id(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "a.db"))
    from analytics import db as _db
    _db.init_db()
    assert _db.update_video_final(
        video_id="nonexistent", output_path="/x.mp4",
    ) is False


def _setup_youtube_mocks(monkeypatch, video_id="yt_xyz"):
    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "tok"})
        return _MockResp(200, headers={"Location": "https://up/"})

    def fake_put(url, **kw):
        return _MockResp(200, json_data={"id": video_id})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)


# ─── C1: published_posts の重複排除 ───────────────


def test_publish_youtube_skips_repeated_publish_by_default(project, monkeypatch):
    """idempotency: 既に成功済みの YouTube 投稿があれば 2 回目は skip して既存を返す."""
    from final_import.publish import publish

    ts, ts_path = project
    upload_calls = {"count": 0}

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "tok"})
        return _MockResp(200, headers={"Location": "https://up/"})

    def fake_put(url, **kw):
        upload_calls["count"] += 1
        return _MockResp(200, json_data={"id": f"yt_{upload_calls['count']}"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    first = publish(ts, "youtube", privacy="unlisted")
    assert first["video_id"] == "yt_1"
    assert not first.get("skipped")

    # 2 回目 — force_republish 未指定なので skip されるべき
    second = publish(ts, "youtube", privacy="unlisted")
    assert second.get("skipped") is True
    assert second["video_id"] == "yt_1"   # 既存を返す
    assert upload_calls["count"] == 1     # YouTube に 2 回目の upload は走っていない

    meta = json.loads((Path(ts_path) / "metadata.json").read_text())
    posts = [p for p in meta["published_posts"] if p["platform"] == "youtube"]
    assert len(posts) == 1


def test_publish_youtube_force_republish_creates_new_entry(project, monkeypatch):
    """force_republish=True を指定すると 2 回目も upload され、新エントリが追加される."""
    from final_import.publish import publish

    ts, ts_path = project
    state = {"video_ids": iter(["yt_first", "yt_second"])}

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "tok"})
        return _MockResp(200, headers={"Location": "https://up/"})

    def fake_put(url, **kw):
        return _MockResp(200, json_data={"id": next(state["video_ids"])})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    publish(ts, "youtube", privacy="unlisted")
    publish(ts, "youtube", privacy="unlisted", force_republish=True)

    meta = json.loads((Path(ts_path) / "metadata.json").read_text())
    posts = [p for p in meta["published_posts"] if p["platform"] == "youtube"]
    assert len(posts) == 2
    assert {p["video_id"] for p in posts} == {"yt_first", "yt_second"}


def test_publish_youtube_dedups_same_video_id(project, monkeypatch):
    """同じ ``(platform, video_id)`` を 2 回登録 → 既存 entry が update される."""
    from final_import.publish import publish

    ts, ts_path = project

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "tok"})
        return _MockResp(200, headers={"Location": "https://up/"})

    def fake_put(url, **kw):
        return _MockResp(200, json_data={"id": "yt_same"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    publish(ts, "youtube", privacy="unlisted")
    first_meta = json.loads((Path(ts_path) / "metadata.json").read_text())
    first_published_at = first_meta["published_posts"][0]["published_at"]

    # 同 ts の published_at は最低 1 秒 ずれる必要があるので少し待つ
    import time as _time
    _time.sleep(1.1)

    # force_republish で同 video_id が再度返ったときの dedup 動作を確認
    publish(ts, "youtube", privacy="public", force_republish=True)
    meta = json.loads((Path(ts_path) / "metadata.json").read_text())
    posts = [p for p in meta["published_posts"] if p["platform"] == "youtube"]
    assert len(posts) == 1
    # update され published_at が新しくなる
    assert posts[0]["video_id"] == "yt_same"
    assert posts[0]["published_at"] > first_published_at


def test_publish_semi_auto_retry_after_failure_deduplicates(project, monkeypatch):
    """半自動: 1 回目 failed → 2 回目 OK → metadata は 1 entry (= update + failed=False)."""
    import sys
    from final_import.publish import publish

    ts, ts_path = project

    def fake_run_all_fail(args, **kw):
        class R:
            returncode = 99
            stdout = b""
            stderr = b"failed"
        return R()

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("subprocess.run", fake_run_all_fail)
    with pytest.raises(RuntimeError):
        publish(ts, "instagram")

    meta = json.loads((Path(ts_path) / "metadata.json").read_text())
    posts = [p for p in meta["published_posts"] if p["platform"] == "instagram"]
    assert len(posts) == 1
    assert posts[0]["failed"] is True

    # 2 回目: 全部成功
    def fake_run_all_ok(args, **kw):
        class R:
            returncode = 0
            stdout = b""
            stderr = b""
        return R()

    monkeypatch.setattr("subprocess.run", fake_run_all_ok)
    publish(ts, "instagram")

    meta = json.loads((Path(ts_path) / "metadata.json").read_text())
    posts = [p for p in meta["published_posts"] if p["platform"] == "instagram"]
    # update 1 件のまま
    assert len(posts) == 1
    assert posts[0].get("failed") is False
    assert posts[0]["manual"] is True


# ─── C3: YouTube OAuth refresh / retry ───────────────


def test_publish_youtube_retries_on_401_after_token_refresh(project, monkeypatch):
    """YouTube upload init が 401 → 1 回 refresh して 200 で完了."""
    from final_import.publish import publish

    ts, ts_path = project
    state = {"oauth_calls": 0, "init_calls": 0}

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            state["oauth_calls"] += 1
            return _MockResp(200, json_data={
                "access_token": f"tok_{state['oauth_calls']}",
            })
        # init upload
        state["init_calls"] += 1
        if state["init_calls"] == 1:
            return _MockResp(401, text="invalid token")
        return _MockResp(200, headers={"Location": "https://up/"})

    def fake_put(url, **kw):
        return _MockResp(200, json_data={"id": "yt_recovered"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    result = publish(ts, "youtube", privacy="unlisted")
    assert result["video_id"] == "yt_recovered"
    # refresh が 2 回 (initial + retry)、init も 2 回
    assert state["oauth_calls"] == 2
    assert state["init_calls"] == 2


def test_publish_youtube_raises_when_refresh_token_invalid(project, monkeypatch):
    """refresh_token 自体が 400/401 → guidance 付き RuntimeError."""
    from final_import.publish import publish

    ts, _ts_path = project

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(401, json_data={"error": "invalid_grant"},
                             text='{"error":"invalid_grant"}')
        return _MockResp(200, headers={"Location": "https://up/"})

    monkeypatch.setattr("requests.post", fake_post)

    with pytest.raises(RuntimeError, match="YOUTUBE_REFRESH_TOKEN"):
        publish(ts, "youtube")


# ─── F: analytics resilience ───────────────


def test_publish_queues_when_analytics_db_fails_3_times(
    project, monkeypatch, tmp_path,
):
    """analytics DB が 3 回連続で失敗 → queue に 1 entry、publish 自体は成功するが
    Stage 8 は **未** generated (= sync 後に立つ)。"""
    from final_import.publish import publish
    from analytics import pending_queue
    import progress_store

    monkeypatch.setenv(
        "ANALYTICS_PENDING_PATH", str(tmp_path / "analytics_pending.jsonl"),
    )
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    ts, ts_path = project
    _setup_youtube_mocks(monkeypatch)

    call_count = {"n": 0}

    def boom(*_a, **_kw):
        call_count["n"] += 1
        raise RuntimeError("simulated DB outage")

    from analytics import db as analytics_db
    monkeypatch.setattr(analytics_db, "register_post", boom)

    result = publish(ts, "youtube", privacy="unlisted")
    assert result["video_id"] == "yt_xyz"
    assert result["analytics_persisted"] is False
    assert call_count["n"] == 3

    entries = pending_queue.read_all()
    assert len(entries) == 1
    e = entries[0]
    assert e["ts"] == ts
    assert e["platform"] == "youtube"
    assert e["platform_post_id"] == "yt_xyz"
    assert e["url"].endswith("/shorts/yt_xyz")
    assert e["caption"]
    assert isinstance(e["hashtags"], list)
    assert e["timestamp"]

    # Stage 8 は queue 同期完了まで保留 — 未 generated
    assert not progress_store.is_generated(ts_path, "publish")
    # published_posts entry には analytics_pending=True が入っている
    meta = json.loads((Path(ts_path) / "metadata.json").read_text())
    yt = [p for p in meta["published_posts"] if p["platform"] == "youtube"]
    assert len(yt) == 1
    assert yt[0]["analytics_pending"] is True


def test_finalize_pending_publish_promotes_stage8_after_replay(
    project, monkeypatch, tmp_path,
):
    """queue replay 成功 → finalize_pending_publish が Stage 8 を立て、
    published_posts[].analytics_pending を False に flip する。"""
    from final_import.publish import publish, finalize_pending_publish
    from analytics import pending_queue, db as analytics_db
    import progress_store

    monkeypatch.setenv(
        "ANALYTICS_PENDING_PATH", str(tmp_path / "analytics_pending.jsonl"),
    )
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    ts, ts_path = project
    _setup_youtube_mocks(monkeypatch)

    # 1st publish: DB ダウンで queue に積む
    real_register = analytics_db.register_post
    state = {"down": True}

    def conditional_register(*a, **kw):
        if state["down"]:
            raise RuntimeError("DB down")
        return real_register(*a, **kw)

    monkeypatch.setattr(analytics_db, "register_post", conditional_register)
    publish(ts, "youtube", privacy="unlisted")
    assert not progress_store.is_generated(ts_path, "publish")

    # DB 復旧 → replay → finalize
    state["down"] = False
    result = pending_queue.replay()
    assert result["success"] == 1
    for synced in set(result["synced_ts"]):
        finalize_pending_publish(synced)

    assert progress_store.is_generated(ts_path, "publish")
    meta = json.loads((Path(ts_path) / "metadata.json").read_text())
    yt = [p for p in meta["published_posts"] if p["platform"] == "youtube"]
    assert yt[0]["analytics_pending"] is False


def test_publish_no_queue_when_db_succeeds_on_third_attempt(
    project, monkeypatch, tmp_path,
):
    """2 回失敗 → 3 回目成功 → queue は空."""
    from final_import.publish import publish
    from analytics import pending_queue, db as analytics_db

    monkeypatch.setenv(
        "ANALYTICS_PENDING_PATH", str(tmp_path / "analytics_pending.jsonl"),
    )
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    ts, _ts_path = project
    _setup_youtube_mocks(monkeypatch)

    state = {"n": 0}
    real_register = analytics_db.register_post

    def flaky(*args, **kwargs):
        state["n"] += 1
        if state["n"] < 3:
            raise RuntimeError("flaky")
        return real_register(*args, **kwargs)

    monkeypatch.setattr(analytics_db, "register_post", flaky)

    result = publish(ts, "youtube")
    assert result["video_id"] == "yt_xyz"
    assert state["n"] == 3

    assert pending_queue.read_all() == []
    posts = analytics_db.list_active_posts(platform="youtube")
    assert any(p["platform_post_id"] == "yt_xyz" for p in posts)


def test_publish_concurrent_queue_writes_are_complete_json(
    project, monkeypatch, tmp_path,
):
    """連続 publish 2 回が両方 DB 失敗 → queue に 2 件、それぞれ完整な JSON."""
    import json as _json
    from final_import.publish import publish
    from analytics import pending_queue, db as analytics_db

    monkeypatch.setenv(
        "ANALYTICS_PENDING_PATH", str(tmp_path / "analytics_pending.jsonl"),
    )
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    ts, _ts_path = project

    monkeypatch.setattr(
        analytics_db, "register_post",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("dead")),
    )

    upload_ids = ["yt_a", "yt_b"]
    state = {"i": 0}

    def fake_post(url, **kw):
        if "oauth2.googleapis.com" in url:
            return _MockResp(200, json_data={"access_token": "tok"})
        return _MockResp(200, headers={"Location": "https://up/"})

    def fake_put(url, **kw):
        vid = upload_ids[state["i"]]
        state["i"] += 1
        return _MockResp(200, json_data={"id": vid})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)

    # idempotency ガード回避のため 2 回目は force_republish=True
    publish(ts, "youtube")
    publish(ts, "youtube", force_republish=True)

    queue_path = tmp_path / "analytics_pending.jsonl"
    raw_lines = queue_path.read_text(encoding="utf-8").splitlines()
    assert len(raw_lines) == 2
    parsed = [_json.loads(line) for line in raw_lines]
    ids = {p["platform_post_id"] for p in parsed}
    assert ids == {"yt_a", "yt_b"}
    for p in parsed:
        assert p["ts"] == ts
        assert p["platform"] == "youtube"
        assert p["url"].startswith("https://")
        assert p["caption"]
        assert "timestamp" in p
