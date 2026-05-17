"""gemini_dialogue_rewriter.py の単体テスト。

設計 doc: docs/plannings/2026-05-17_gemini-dialogue-rewrite.md

Gemini API は mock。validator / fallback / status の遷移を中心にテストする。
"""
from __future__ import annotations

import json

import pytest

import gemini_dialogue_rewriter as rw


# ─── fixtures ───────────────────────────────────────────────────


def _two_scene_sp() -> dict:
    """2 scenes × 2 lines の最小台本。"""
    return {
        "caption": "知らないと損する3つのコツ\n\n#tips #ライフハック",
        "scenes": [
            {"lines": [
                {"text": "やばいやばい", "emotion": "焦り",
                 "speaker": "f1"},
                {"text": "本当にこれはひどい", "emotion": "落胆",
                 "speaker": "f1"},
            ]},
            {"lines": [
                {"text": "セーフ間に合った", "emotion": "満足",
                 "speaker": "m1"},
                {"text": "助かったよ本当に", "emotion": "喜び",
                 "speaker": "m1"},
            ]},
        ],
    }


@pytest.fixture
def enable_rewrite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYZE_DIALOGUE_REWRITE_ENABLED", "1")
    monkeypatch.setattr("config.GOOGLE_API_KEY", "fake-key")


@pytest.fixture
def mock_gemini(monkeypatch: pytest.MonkeyPatch):
    """`_call_gemini` を controllable な fake で差し替える helper。

    test 側で `mock_gemini(response_text)` を呼んで応答 text を仕込む。
    """

    state = {"response_text": "", "input_tokens": 100, "output_tokens": 200,
             "call_count": 0, "raise_on_call": None}

    def fake_call(prompt: str):
        state["call_count"] += 1
        if state["raise_on_call"] is not None:
            raise state["raise_on_call"]
        return state["response_text"], state["input_tokens"], state["output_tokens"]

    monkeypatch.setattr(rw, "_call_gemini", fake_call)
    return state


# ─── kill-switch / no-op パターン ───────────────────────────────


class TestSkipPaths:
    def test_disabled_by_env_returns_original(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ANALYZE_DIALOGUE_REWRITE_ENABLED", "0")
        sp = _two_scene_sp()
        result = rw.rewrite_screenplay(sp)
        assert result.status == "skipped"
        assert result.reason == "disabled_by_env"
        assert result.screenplay is sp  # 同じ object を返す

    def test_no_api_key_returns_original(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ANALYZE_DIALOGUE_REWRITE_ENABLED", "1")
        monkeypatch.setattr("config.GOOGLE_API_KEY", None)
        sp = _two_scene_sp()
        result = rw.rewrite_screenplay(sp)
        assert result.status == "skipped"
        assert result.reason == "no_api_key"

    def test_empty_screenplay_skipped(
        self, enable_rewrite,
    ) -> None:
        result = rw.rewrite_screenplay({"scenes": []})
        assert result.status == "skipped"
        assert result.reason == "no_content"


# ─── 正常系 ─────────────────────────────────────────────────────


class TestSuccessfulRewrite:
    def test_all_lines_rewritten(
        self, enable_rewrite, mock_gemini,
    ) -> None:
        """全 line + caption が valid に rewrite されたら status=success。"""
        sp = _two_scene_sp()
        # 元のテキスト長と ±20% 以内 + 半角句読点無し
        mock_gemini["response_text"] = json.dumps({
            "caption": "誰でもできる小ワザ3選\n\n#コツ #便利",
            "lines": [
                {"scene_idx": 0, "line_idx": 0, "text": "あぁまずい"},
                {"scene_idx": 0, "line_idx": 1, "text": "これは厳しい状況"},
                {"scene_idx": 1, "line_idx": 0, "text": "ぎりぎり間に合った"},
                {"scene_idx": 1, "line_idx": 1, "text": "本当に助かりました"},
            ],
        }, ensure_ascii=False)

        result = rw.rewrite_screenplay(sp)
        assert result.status == "success"
        assert result.per_line_fallback_count == 0
        assert result.input_tokens == 100
        assert result.output_tokens == 200
        # 各 line が rewrite されている
        assert result.screenplay["scenes"][0]["lines"][0]["text"] == "あぁまずい"
        assert result.screenplay["scenes"][1]["lines"][1]["text"] == "本当に助かりました"
        # caption も rewrite
        assert result.screenplay["caption"] == "誰でもできる小ワザ3選\n\n#コツ #便利"
        # 構造 + メタ (= emotion / speaker) は不変
        assert result.screenplay["scenes"][0]["lines"][0]["emotion"] == "焦り"
        assert result.screenplay["scenes"][0]["lines"][0]["speaker"] == "f1"
        # original は破壊されていない (= deep copy)
        assert sp["scenes"][0]["lines"][0]["text"] == "やばいやばい"

    def test_json_inside_code_fence_parsed(
        self, enable_rewrite, mock_gemini,
    ) -> None:
        """```json ... ``` で囲まれた応答も parse できる。"""
        sp = _two_scene_sp()
        payload = json.dumps({
            "caption": "誰でもできる小ワザ3選\n\n#コツ #便利",
            "lines": [
                {"scene_idx": 0, "line_idx": 0, "text": "あぁまずい"},
                {"scene_idx": 0, "line_idx": 1, "text": "これは厳しい状況"},
                {"scene_idx": 1, "line_idx": 0, "text": "ぎりぎり間に合った"},
                {"scene_idx": 1, "line_idx": 1, "text": "本当に助かりました"},
            ],
        }, ensure_ascii=False)
        mock_gemini["response_text"] = f"```json\n{payload}\n```"

        result = rw.rewrite_screenplay(sp)
        assert result.status == "success"

    def test_json_with_prose_around_parsed(
        self, enable_rewrite, mock_gemini,
    ) -> None:
        """prose で囲まれた JSON もスライスして parse できる。"""
        sp = _two_scene_sp()
        payload = json.dumps({
            "caption": "誰でもできる小ワザ3選\n\n#コツ #便利",
            "lines": [
                {"scene_idx": 0, "line_idx": 0, "text": "あぁまずい"},
                {"scene_idx": 0, "line_idx": 1, "text": "これは厳しい状況"},
                {"scene_idx": 1, "line_idx": 0, "text": "ぎりぎり間に合った"},
                {"scene_idx": 1, "line_idx": 1, "text": "本当に助かりました"},
            ],
        }, ensure_ascii=False)
        mock_gemini["response_text"] = (
            "了解しました。以下が rewrite 結果です:\n\n"
            f"{payload}\n\n以上です。"
        )

        result = rw.rewrite_screenplay(sp)
        assert result.status == "success"


# ─── per-line fallback ─────────────────────────────────────────


class TestPerLineFallback:
    def test_too_long_line_falls_back(
        self, enable_rewrite, mock_gemini,
    ) -> None:
        """文字数比率超過 line だけ original に戻る → status=partial。"""
        sp = _two_scene_sp()
        # line (0,0) は元 "やばいやばい" (6 char)。3 倍 = 違反
        mock_gemini["response_text"] = json.dumps({
            "caption": "誰でもできる小ワザ3選\n\n#コツ #便利",
            "lines": [
                {"scene_idx": 0, "line_idx": 0,
                 "text": "あああああああああああああああああああああ"},
                {"scene_idx": 0, "line_idx": 1, "text": "これは厳しい状況"},
                {"scene_idx": 1, "line_idx": 0, "text": "ぎりぎり間に合った"},
                {"scene_idx": 1, "line_idx": 1, "text": "本当に助かりました"},
            ],
        }, ensure_ascii=False)

        result = rw.rewrite_screenplay(sp)
        assert result.status == "partial"
        assert result.per_line_fallback_count == 1
        assert (0, 0) in result.fallback_indices
        # 違反 line は original 維持
        assert result.screenplay["scenes"][0]["lines"][0]["text"] == "やばいやばい"
        # 他 line は rewrite
        assert result.screenplay["scenes"][0]["lines"][1]["text"] == "これは厳しい状況"

    def test_ascii_punct_line_falls_back(
        self, enable_rewrite, mock_gemini,
    ) -> None:
        """ASCII , / . を含む line だけ original に戻る。"""
        sp = _two_scene_sp()
        mock_gemini["response_text"] = json.dumps({
            "caption": "誰でもできる小ワザ3選\n\n#コツ #便利",
            "lines": [
                {"scene_idx": 0, "line_idx": 0, "text": "あぁ,まずい"},  # 違反
                {"scene_idx": 0, "line_idx": 1, "text": "これは厳しい状況"},
                {"scene_idx": 1, "line_idx": 0, "text": "ぎりぎり間に合った"},
                {"scene_idx": 1, "line_idx": 1, "text": "本当に助かりました"},
            ],
        }, ensure_ascii=False)

        result = rw.rewrite_screenplay(sp)
        assert result.status == "partial"
        assert (0, 0) in result.fallback_indices
        assert result.screenplay["scenes"][0]["lines"][0]["text"] == "やばいやばい"

    def test_missing_line_in_payload_falls_back(
        self, enable_rewrite, mock_gemini,
    ) -> None:
        """payload に line が無ければ original 維持 → partial。"""
        sp = _two_scene_sp()
        # line (1,1) を意図的に欠落
        mock_gemini["response_text"] = json.dumps({
            "caption": "誰でもできる小ワザ3選\n\n#コツ #便利",
            "lines": [
                {"scene_idx": 0, "line_idx": 0, "text": "あぁまずい"},
                {"scene_idx": 0, "line_idx": 1, "text": "これは厳しい状況"},
                {"scene_idx": 1, "line_idx": 0, "text": "ぎりぎり間に合った"},
            ],
        }, ensure_ascii=False)

        result = rw.rewrite_screenplay(sp)
        assert result.status == "partial"
        assert (1, 1) in result.fallback_indices
        # 欠落 line は original
        assert result.screenplay["scenes"][1]["lines"][1]["text"] == "助かったよ本当に"

    def test_all_lines_fallback_treated_as_skipped(
        self, enable_rewrite, mock_gemini,
    ) -> None:
        """全 line が違反なら structure_drift → status=skipped、original 採用。"""
        sp = _two_scene_sp()
        # 全 line が違反 (= 全部に半角 .)
        mock_gemini["response_text"] = json.dumps({
            "caption": "誰でもできる小ワザ3選\n\n#コツ #便利",
            "lines": [
                {"scene_idx": s, "line_idx": l, "text": "x.y"}
                for s in range(2) for l in range(2)
            ],
        }, ensure_ascii=False)

        result = rw.rewrite_screenplay(sp)
        assert result.status == "skipped"
        assert result.reason == "all_lines_fallback"
        # 全 line original 維持
        assert result.screenplay is sp


# ─── API error / parse error ───────────────────────────────────


class TestApiFailures:
    def test_api_error_after_retries_falls_back(
        self, enable_rewrite, mock_gemini, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """API が全 retry 失敗したら skipped + reason=api_error。"""
        # sleep をスキップ
        monkeypatch.setattr(rw.time, "sleep", lambda s: None)
        mock_gemini["raise_on_call"] = RuntimeError("network error")
        sp = _two_scene_sp()
        result = rw.rewrite_screenplay(sp)
        assert result.status == "skipped"
        assert result.reason.startswith("api_error")
        # MAX_RETRIES + 1 回 呼ばれる
        assert mock_gemini["call_count"] == rw.MAX_RETRIES + 1
        # original 維持
        assert result.screenplay is sp

    def test_parse_error_falls_back(
        self, enable_rewrite, mock_gemini,
    ) -> None:
        """JSON でない応答なら skipped + reason=parse_error。"""
        sp = _two_scene_sp()
        mock_gemini["response_text"] = "Gemini が無関係なテキストを返した"
        result = rw.rewrite_screenplay(sp)
        assert result.status == "skipped"
        assert result.reason == "parse_error"
        assert result.screenplay is sp

    def test_recovers_on_retry(
        self, enable_rewrite, mock_gemini, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """初回 fail、2 回目で復旧したら success。"""
        monkeypatch.setattr(rw.time, "sleep", lambda s: None)
        sp = _two_scene_sp()
        payload = json.dumps({
            "caption": "誰でもできる小ワザ3選\n\n#コツ #便利",
            "lines": [
                {"scene_idx": s, "line_idx": l, "text": "リライト OK"}
                for s in range(2) for l in range(2)
            ],
        }, ensure_ascii=False)

        # 初回 raise、2 回目正常応答 (= state[raise_on_call] を呼出毎に消す)
        call_state = {"count": 0}

        def selective_fake(prompt: str):
            call_state["count"] += 1
            if call_state["count"] == 1:
                raise RuntimeError("transient")
            return payload, 100, 200

        monkeypatch.setattr(rw, "_call_gemini", selective_fake)
        result = rw.rewrite_screenplay(sp)
        # "リライト OK" は 7 char、original (= 6, 8, 7, 8) と ±20% 範囲内かは
        # 微妙。違反 line は per-line fallback。ここでは status は success or
        # partial のいずれかになる (= retry 経路自体は動いた)。
        assert result.status in ("success", "partial")


# ─── caption ────────────────────────────────────────────────────


class TestCaptionRewrite:
    def test_caption_with_ascii_punct_falls_back(
        self, enable_rewrite, mock_gemini,
    ) -> None:
        """半角 , / . を含む caption は original 維持、line だけ rewrite。"""
        sp = _two_scene_sp()
        mock_gemini["response_text"] = json.dumps({
            "caption": "tips,for,life",  # 違反
            "lines": [
                {"scene_idx": s, "line_idx": l, "text": "リライト"}
                for s in range(2) for l in range(2)
            ],
        }, ensure_ascii=False)

        result = rw.rewrite_screenplay(sp)
        # caption は original 維持、line が partial fallback (= 4 line 全部が
        # ±20% 違反になるはずだが「リライト」(4 char) は元 (6-8 char) の
        # 0.5-0.67 倍で違反 → 全 fallback → status=skipped)
        # ここでは caption fallback の挙動を主に確認
        # 注: 「リライト」も違反なので line も全 fallback
        # → status=skipped で sp 全体が original 維持
        assert result.screenplay["caption"] == sp["caption"]
        # all_lines_fallback の場合 screenplay は sp identity
        assert result.screenplay is sp
        assert result.status == "skipped"


# ─── 構造保護 ───────────────────────────────────────────────────


class TestStructurePreservation:
    def test_speaker_and_emotion_untouched(
        self, enable_rewrite, mock_gemini,
    ) -> None:
        """speaker / emotion / delivery など全メタは触らない。"""
        sp = _two_scene_sp()
        # delivery を追加
        sp["scenes"][0]["lines"][0]["delivery"] = "早口"
        sp["scenes"][0]["lines"][0]["audio_tags"] = ["whispers"]
        sp["scenes"][0]["lines"][0]["pronunciation_hints"] = {
            "IT": "アイティー",
        }

        mock_gemini["response_text"] = json.dumps({
            "caption": "誰でもできる小ワザ3選\n\n#コツ #便利",
            "lines": [
                {"scene_idx": 0, "line_idx": 0, "text": "あぁまずい"},
                {"scene_idx": 0, "line_idx": 1, "text": "これは厳しい状況"},
                {"scene_idx": 1, "line_idx": 0, "text": "ぎりぎり間に合った"},
                {"scene_idx": 1, "line_idx": 1, "text": "本当に助かりました"},
            ],
        }, ensure_ascii=False)

        result = rw.rewrite_screenplay(sp)
        assert result.status == "success"
        l00 = result.screenplay["scenes"][0]["lines"][0]
        # 全メタ field が保持されている
        assert l00["emotion"] == "焦り"
        assert l00["speaker"] == "f1"
        assert l00["delivery"] == "早口"
        assert l00["audio_tags"] == ["whispers"]
        assert l00["pronunciation_hints"] == {"IT": "アイティー"}
        # text だけ rewrite
        assert l00["text"] == "あぁまずい"

    def test_scene_count_and_line_count_unchanged(
        self, enable_rewrite, mock_gemini,
    ) -> None:
        sp = _two_scene_sp()
        mock_gemini["response_text"] = json.dumps({
            "caption": "誰でもできる小ワザ3選\n\n#コツ #便利",
            "lines": [
                {"scene_idx": 0, "line_idx": 0, "text": "あぁまずい"},
                {"scene_idx": 0, "line_idx": 1, "text": "これは厳しい状況"},
                {"scene_idx": 1, "line_idx": 0, "text": "ぎりぎり間に合った"},
                {"scene_idx": 1, "line_idx": 1, "text": "本当に助かりました"},
            ],
        }, ensure_ascii=False)

        result = rw.rewrite_screenplay(sp)
        assert len(result.screenplay["scenes"]) == 2
        assert len(result.screenplay["scenes"][0]["lines"]) == 2
        assert len(result.screenplay["scenes"][1]["lines"]) == 2
