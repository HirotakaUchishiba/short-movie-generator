import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.fixture(autouse=True)
def _isolate_cost_records(tmp_path, monkeypatch):
    """テスト実行中の cost recorder が本番 ``data/cost_records.jsonl`` を汚染
    しないよう、COST_RECORDS_PATH を必ず tmp_path に向ける。

    scene_gen / video_analyzer / lipsync 等の既存テストでも recorder 統合が
    走るため、stage 個別テストでも自動で本番ファイルから隔離される。個別
    テストは monkeypatch で同じ env を上書きして任意の path に向け直せる。
    """
    monkeypatch.setenv(
        "COST_RECORDS_PATH", str(tmp_path / "cost_records.jsonl")
    )


@pytest.fixture(autouse=True)
def _isolate_job_store(tmp_path, monkeypatch):
    """preview_server を import するテストが本番 ``data/jobs.json`` を汚染
    しないよう、JOB_STORE_DIR を tmp_path に向ける。"""
    monkeypatch.setenv("JOB_STORE_DIR", str(tmp_path / "jobstore"))


@pytest.fixture(autouse=True)
def _isolate_intent_suggestions(tmp_path, monkeypatch):
    """analyze pipeline / route テストが本番 ``data/intent_suggestions.json``
    を汚染しないよう、INTENT_SUGGESTIONS_PATH と archive dir を tmp_path に向ける。
    """
    monkeypatch.setenv(
        "INTENT_SUGGESTIONS_PATH", str(tmp_path / "intent_suggestions.json")
    )
    monkeypatch.setenv(
        "INTENT_SUGGESTIONS_ARCHIVE_DIR",
        str(tmp_path / "intent_suggestions_archive"),
    )
    import config as _config
    monkeypatch.setattr(
        _config,
        "INTENT_SUGGESTIONS_PATH",
        str(tmp_path / "intent_suggestions.json"),
    )
    monkeypatch.setattr(
        _config,
        "INTENT_SUGGESTIONS_ARCHIVE_DIR",
        str(tmp_path / "intent_suggestions_archive"),
    )


@pytest.fixture(autouse=True)
def _stub_character_images(request, monkeypatch):
    """validator / diagnose_abstract の character ref 物理存在検証は
    既定スキップ (= 開発機の characters/ に依存しない)。

    存在検証を働かせたいテストは個別に
    `monkeypatch.setattr(cmeta_mod, "list_character_images", lambda: [...])`
    で上書きする。``@pytest.mark.real_characters_dir`` を付けた test では
    skip され、character_meta 本体の挙動を直接テストできる。
    """
    if request.node.get_closest_marker("real_characters_dir"):
        return
    from analyze import character_meta as cmeta_mod
    monkeypatch.setattr(cmeta_mod, "list_character_images", lambda: [])
