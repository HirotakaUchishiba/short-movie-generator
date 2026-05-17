"""per_character_tts.py の単体テスト。

- speaker collection (= compose 後の line.speaker → unique base set)
- voice resolution (= characters/<base>/voice.json → config fallback)
- per-voice cache key (= voice_id / settings の変化で必ず miss する)
- per-voice 並列生成 (= ElevenLabs API mock)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import per_character_tts as pct


# ─── speaker collection ────────────────────────────────────────────


class TestCollectUniqueSpeakers:
    def test_empty_screenplay_returns_empty(self) -> None:
        assert pct.collect_unique_speakers({}) == []
        assert pct.collect_unique_speakers({"scenes": []}) == []

    def test_no_speaker_returns_empty(self) -> None:
        sp = {"scenes": [{"lines": [{"text": "a"}, {"text": "b"}]}]}
        assert pct.collect_unique_speakers(sp) == []

    def test_single_speaker(self) -> None:
        sp = {"scenes": [{"lines": [
            {"text": "a", "speaker": "f1"},
            {"text": "b", "speaker": "f1"},
        ]}]}
        assert pct.collect_unique_speakers(sp) == ["f1"]

    def test_strips_wardrobe_suffix(self) -> None:
        """speaker が resolved id (= f1__office) なら base に剥がす。"""
        sp = {"scenes": [{"lines": [
            {"text": "a", "speaker": "f1__office"},
            {"text": "b", "speaker": "f1__casual"},  # 同 base
            {"text": "c", "speaker": "m1__suit"},
        ]}]}
        assert pct.collect_unique_speakers(sp) == ["f1", "m1"]

    def test_sorted_order(self) -> None:
        """結果は alphabetical sorted (= 並列実行順序の決定論性)。"""
        sp = {"scenes": [{"lines": [
            {"text": "a", "speaker": "m2"},
            {"text": "b", "speaker": "f1"},
            {"text": "c", "speaker": "m1"},
        ]}]}
        assert pct.collect_unique_speakers(sp) == ["f1", "m1", "m2"]

    def test_skips_invalid_speaker_types(self) -> None:
        sp = {"scenes": [{"lines": [
            {"text": "a", "speaker": "f1"},
            {"text": "b", "speaker": ""},
            {"text": "c", "speaker": None},
            {"text": "d", "speaker": 42},
        ]}]}
        assert pct.collect_unique_speakers(sp) == ["f1"]


class TestPrimarySpeaker:
    def test_returns_most_frequent(self) -> None:
        sp = {"scenes": [{"lines": [
            {"speaker": "f1"}, {"speaker": "f1"}, {"speaker": "f1"},
            {"speaker": "m1"}, {"speaker": "m1"},
        ]}]}
        assert pct.primary_speaker(sp) == "f1"

    def test_alphabetical_on_tie(self) -> None:
        sp = {"scenes": [{"lines": [
            {"speaker": "m1"}, {"speaker": "f1"},
        ]}]}
        # 同数なら alphabetical 先頭
        assert pct.primary_speaker(sp) == "f1"

    def test_none_when_no_speakers(self) -> None:
        sp = {"scenes": [{"lines": [{"text": "a"}]}]}
        assert pct.primary_speaker(sp) is None


# ─── voice resolution ──────────────────────────────────────────────


@pytest.fixture
def isolated_chars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """テスト用に characters/ を一時 dir に差し替える。"""
    monkeypatch.setattr("config.CHARACTERS_DIR", str(tmp_path))
    # character_meta が module-level で読む CHARACTERS_DIR も差し替え
    monkeypatch.setattr(
        "analyze.character_meta.CHARACTERS_DIR", tmp_path,
    )
    return tmp_path


def _write_voice_json(base_dir: Path, base_id: str, content: dict) -> None:
    (base_dir / base_id).mkdir(parents=True, exist_ok=True)
    (base_dir / base_id / "voice.json").write_text(
        json.dumps(content), encoding="utf-8",
    )


class TestResolveVoiceForSpeaker:
    def test_uses_character_voice_id(self, isolated_chars: Path) -> None:
        _write_voice_json(isolated_chars, "f1", {
            "id": "f1",
            "voice_id": "char_voice_abc",
            "voice_overrides": {"stability": 0.6},
        })
        vid, ov = pct.resolve_voice_for_speaker("f1")
        assert vid == "char_voice_abc"
        assert ov == {"stability": 0.6}

    def test_falls_back_to_config(
        self, isolated_chars: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """voice.json に voice_id が無ければ config 既定にフォールバック。"""
        monkeypatch.setattr(
            "config.ELEVENLABS_VOICE_ID", "config_default_voice",
        )
        _write_voice_json(isolated_chars, "f1", {
            "id": "f1",
            "voice_overrides": {"stability": 0.6},
        })
        vid, ov = pct.resolve_voice_for_speaker("f1")
        assert vid == "config_default_voice"
        assert ov == {"stability": 0.6}

    def test_missing_voice_json_falls_back_to_config(
        self, isolated_chars: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """voice.json 自体が無くても crash せず config にフォールバック。"""
        monkeypatch.setattr(
            "config.ELEVENLABS_VOICE_ID", "config_default_voice",
        )
        vid, ov = pct.resolve_voice_for_speaker("ghost_char")
        assert vid == "config_default_voice"
        assert ov == {}

    def test_corrupt_voice_json_falls_back(
        self, isolated_chars: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """壊れた JSON でも crash せず config にフォールバック (graceful)。"""
        monkeypatch.setattr(
            "config.ELEVENLABS_VOICE_ID", "config_default_voice",
        )
        (isolated_chars / "f1").mkdir(parents=True)
        (isolated_chars / "f1" / "voice.json").write_text("{{ not json")
        vid, ov = pct.resolve_voice_for_speaker("f1")
        assert vid == "config_default_voice"
        assert ov == {}


class TestBuildVoiceSettings:
    def test_defaults_from_config(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("config.ELEVENLABS_VOICE_STABILITY", 0.5)
        monkeypatch.setattr("config.ELEVENLABS_VOICE_SIMILARITY_BOOST", 0.7)
        monkeypatch.setattr("config.ELEVENLABS_VOICE_STYLE", 0.3)
        settings = pct.build_voice_settings({}, speed=1.0)
        assert settings == {
            "stability": 0.5,
            "similarity_boost": 0.7,
            "style": 0.3,
            "speed": 1.0,
        }

    def test_overrides_take_precedence(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("config.ELEVENLABS_VOICE_STABILITY", 0.5)
        monkeypatch.setattr("config.ELEVENLABS_VOICE_SIMILARITY_BOOST", 0.7)
        monkeypatch.setattr("config.ELEVENLABS_VOICE_STYLE", 0.3)
        settings = pct.build_voice_settings(
            {"stability": 0.9, "style": 0.1}, speed=1.0,
        )
        assert settings["stability"] == 0.9
        assert settings["style"] == 0.1
        assert settings["similarity_boost"] == 0.7  # not overridden


class TestComputeCacheKey:
    def test_deterministic(self) -> None:
        s = {"stability": 0.5, "style": 0.3, "speed": 1.0}
        h1 = pct.compute_per_voice_cache_key("abc", "v1", s)
        h2 = pct.compute_per_voice_cache_key("abc", "v1", dict(s))
        assert h1 == h2
        assert len(h1) == 12

    def test_voice_id_change_invalidates(self) -> None:
        s = {"stability": 0.5, "speed": 1.0}
        assert pct.compute_per_voice_cache_key("abc", "v1", s) != \
               pct.compute_per_voice_cache_key("abc", "v2", s)

    def test_settings_change_invalidates(self) -> None:
        assert pct.compute_per_voice_cache_key(
            "abc", "v1", {"stability": 0.5},
        ) != pct.compute_per_voice_cache_key(
            "abc", "v1", {"stability": 0.6},
        )

    def test_text_change_invalidates(self) -> None:
        s = {"stability": 0.5}
        assert pct.compute_per_voice_cache_key("abc", "v1", s) != \
               pct.compute_per_voice_cache_key("abcd", "v1", s)

    def test_settings_key_order_does_not_matter(self) -> None:
        h1 = pct.compute_per_voice_cache_key("abc", "v1", {
            "stability": 0.5, "speed": 1.0,
        })
        h2 = pct.compute_per_voice_cache_key("abc", "v1", {
            "speed": 1.0, "stability": 0.5,
        })
        assert h1 == h2


# ─── per-voice generation (= integration with mocked ElevenLabs) ──


@pytest.fixture
def mock_eleven(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> MagicMock:
    """ElevenLabs API を fake_api で mock。

    output_path に dummy mp3 を、output_path の拡張子を .json に置換した
    パスに dummy timestamps JSON を書き出す (= 実 API と同じ contract)。
    """

    def fake_api(*, text: str, voice_id: str, output_path: str, **kwargs):
        Path(output_path).write_bytes(b"ID3\x03" + b"\x00" * 200)
        # ElevenLabs は <output_path 拡張子なし>.json に bare list を書く
        # (= 実 elevenlabs_client.py の format)
        json_path = output_path.rsplit(".", 1)[0] + ".json"
        char_list = [
            {"char": c, "start": float(i), "end": float(i) + 0.5}
            for i, c in enumerate(text)
        ]
        Path(json_path).write_text(json.dumps(char_list))
        return char_list

    monkeypatch.setattr(
        "elevenlabs_client.generate_speech_with_timestamps", fake_api,
    )
    monkeypatch.setattr(
        "elevenlabs_client.MODEL_ID", "test_model_v1",
    )

    # artifact_integrity を bypass (= dummy mp3 を valid 扱い)
    monkeypatch.setattr(
        "artifact_integrity.is_valid_audio", lambda p: True,
    )

    # cost_recorder を no-op に
    monkeypatch.setattr(
        "cost_tracking.recorder.record_tts",
        MagicMock(return_value=None),
    )

    # ELEVENLABS_API_KEY を非空に
    monkeypatch.setattr("config.ELEVENLABS_API_KEY", "fake_key")

    return fake_api


@pytest.fixture
def ts_path(tmp_path: Path) -> str:
    """1 プロジェクトの ts_path を返す。"""
    p = tmp_path / "20260517_120000"
    p.mkdir()
    return str(p)


class TestGeneratePerVoiceFullAudios:
    """並列 generation の end-to-end (= API mock 経由)。"""

    def test_empty_speakers_returns_empty(
        self, mock_eleven: MagicMock, ts_path: str,
    ) -> None:
        result = pct.generate_per_voice_full_audios(
            speakers=[],
            full_text="abc",
            ts_path=ts_path,
            speed=1.0,
            project_ts="20260517_120000",
        )
        assert result == {}

    def test_single_speaker_one_call(
        self, mock_eleven: MagicMock, ts_path: str,
        isolated_chars: Path,
    ) -> None:
        _write_voice_json(isolated_chars, "f1", {
            "id": "f1", "voice_id": "char_v1",
        })
        result = pct.generate_per_voice_full_audios(
            speakers=["f1"],
            full_text="hello",
            ts_path=ts_path,
            speed=1.0,
            project_ts="20260517_120000",
        )
        assert set(result.keys()) == {"f1"}
        assert result["f1"].voice_id == "char_v1"
        assert Path(result["f1"].mp3_path).exists()
        assert Path(result["f1"].char_ts_path).exists()

    def test_multi_speaker_parallel(
        self, mock_eleven: MagicMock, ts_path: str,
        isolated_chars: Path,
    ) -> None:
        _write_voice_json(isolated_chars, "f1", {
            "id": "f1", "voice_id": "char_v_f1",
        })
        _write_voice_json(isolated_chars, "m1", {
            "id": "m1", "voice_id": "char_v_m1",
        })
        result = pct.generate_per_voice_full_audios(
            speakers=["f1", "m1"],
            full_text="abc",
            ts_path=ts_path,
            speed=1.0,
            project_ts="20260517_120000",
        )
        assert set(result.keys()) == {"f1", "m1"}
        assert result["f1"].voice_id == "char_v_f1"
        assert result["m1"].voice_id == "char_v_m1"
        # ファイル名が衝突しない
        assert result["f1"].mp3_path != result["m1"].mp3_path
        # text_meta.json に voice_id が記録されている (= module の責務)
        f1_meta = json.loads(Path(
            pct.per_voice_paths(ts_path, "f1")["text_meta"]).read_text())
        m1_meta = json.loads(Path(
            pct.per_voice_paths(ts_path, "m1")["text_meta"]).read_text())
        assert f1_meta["voice_id"] == "char_v_f1"
        assert m1_meta["voice_id"] == "char_v_m1"
        # 各 char_ts は bare list (= 実 elevenlabs format)
        ts_f1 = json.loads(Path(result["f1"].char_ts_path).read_text())
        assert isinstance(ts_f1, list)
        assert all("char" in c and "start" in c and "end" in c for c in ts_f1)

    def test_cache_hit_skips_api(
        self, mock_eleven: MagicMock, ts_path: str,
        isolated_chars: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_voice_json(isolated_chars, "f1", {
            "id": "f1", "voice_id": "char_v1",
        })
        # 1 回目
        call_count = [0]

        def counting_fake(*args, **kwargs):
            call_count[0] += 1
            return mock_eleven(*args, **kwargs)

        monkeypatch.setattr(
            "elevenlabs_client.generate_speech_with_timestamps",
            counting_fake,
        )
        pct.generate_per_voice_full_audios(
            speakers=["f1"], full_text="abc", ts_path=ts_path,
            speed=1.0, project_ts="20260517_120000",
        )
        assert call_count[0] == 1
        # 2 回目 — 同じ text + voice なので cache hit
        pct.generate_per_voice_full_audios(
            speakers=["f1"], full_text="abc", ts_path=ts_path,
            speed=1.0, project_ts="20260517_120000",
        )
        assert call_count[0] == 1  # 増えない

    def test_voice_id_swap_invalidates_cache(
        self, mock_eleven: MagicMock, ts_path: str,
        isolated_chars: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_voice_json(isolated_chars, "f1", {
            "id": "f1", "voice_id": "voice_A",
        })
        call_count = [0]

        def counting_fake(*args, **kwargs):
            call_count[0] += 1
            return mock_eleven(*args, **kwargs)

        monkeypatch.setattr(
            "elevenlabs_client.generate_speech_with_timestamps",
            counting_fake,
        )
        pct.generate_per_voice_full_audios(
            speakers=["f1"], full_text="abc", ts_path=ts_path,
            speed=1.0, project_ts="20260517_120000",
        )
        # voice_id を入れ替える
        _write_voice_json(isolated_chars, "f1", {
            "id": "f1", "voice_id": "voice_B",
        })
        pct.generate_per_voice_full_audios(
            speakers=["f1"], full_text="abc", ts_path=ts_path,
            speed=1.0, project_ts="20260517_120000",
        )
        assert call_count[0] == 2  # 再呼出

    def test_no_api_key_raises(
        self, monkeypatch: pytest.MonkeyPatch, ts_path: str,
    ) -> None:
        monkeypatch.setattr("config.ELEVENLABS_API_KEY", "")
        with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
            pct.generate_per_voice_full_audios(
                speakers=["f1"], full_text="abc", ts_path=ts_path,
                speed=1.0, project_ts="20260517_120000",
            )

    def test_one_voice_failure_fails_all(
        self, mock_eleven: MagicMock, ts_path: str,
        isolated_chars: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """1 voice の API 失敗で全体が例外を投げる (= fail-fast)。"""
        _write_voice_json(isolated_chars, "f1", {
            "id": "f1", "voice_id": "voice_A",
        })
        _write_voice_json(isolated_chars, "m1", {
            "id": "m1", "voice_id": "voice_B",
        })

        def selective_fail(*, text, voice_id, output_path, **kwargs):
            if voice_id == "voice_B":
                raise RuntimeError("simulated B failure")
            return mock_eleven(
                text=text, voice_id=voice_id, output_path=output_path,
                **kwargs,
            )

        monkeypatch.setattr(
            "elevenlabs_client.generate_speech_with_timestamps",
            selective_fail,
        )
        with pytest.raises(RuntimeError, match="simulated B failure"):
            pct.generate_per_voice_full_audios(
                speakers=["f1", "m1"], full_text="abc", ts_path=ts_path,
                speed=1.0, project_ts="20260517_120000",
            )

    def test_one_voice_failure_skipped_above(
        self,
    ) -> None:
        """skip marker (= self-doc)。fail-fast は上記でカバー済み。"""
        pass

    def test_cost_recorded_per_voice(
        self, mock_eleven: MagicMock, ts_path: str,
        isolated_chars: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """n voice なら record_tts も n 回呼ばれる。"""
        _write_voice_json(isolated_chars, "f1", {
            "id": "f1", "voice_id": "voice_A",
        })
        _write_voice_json(isolated_chars, "m1", {
            "id": "m1", "voice_id": "voice_B",
        })
        record_mock = MagicMock(return_value=None)
        monkeypatch.setattr(
            "cost_tracking.recorder.record_tts", record_mock,
        )
        pct.generate_per_voice_full_audios(
            speakers=["f1", "m1"], full_text="abcde", ts_path=ts_path,
            speed=1.0, project_ts="20260517_120000",
        )
        assert record_mock.call_count == 2
        # 各 call が characters=5 (= len("abcde"))
        for call in record_mock.call_args_list:
            assert call.kwargs["characters"] == 5
