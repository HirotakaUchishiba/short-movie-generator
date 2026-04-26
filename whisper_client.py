import logging
import os

logger = logging.getLogger(__name__)


class WhisperClientError(Exception):
    pass


def transcribe(audio_path: str, language: str = "ja",
               api_key: str | None = None,
               local_model: str = "large-v3") -> dict:
    """音声を文字起こししword単位timestampsを返す。

    OPENAI_API_KEYがあればOpenAI Whisper APIを使い、無ければfaster-whisperで
    ローカル実行する。両方失敗時はWhisperClientErrorをraise。

    Returns:
        {
            "text": "全体のテキスト",
            "segments": [{"start": 0.0, "end": 2.3, "text": "..."}, ...],
            "words":    [{"start": 0.1, "end": 0.6, "word": "8時"}, ...],
            "duration": 50.5,
        }
    """
    if not os.path.exists(audio_path):
        raise WhisperClientError(f"音声ファイルが見つかりません: {audio_path}")

    key = api_key or os.getenv("OPENAI_API_KEY")
    if key:
        return _transcribe_openai(audio_path, language, key)
    logger.info("OPENAI_API_KEY未設定 → faster-whisper(local)で文字起こし")
    return _transcribe_local(audio_path, language, local_model)


def _transcribe_local(audio_path: str, language: str, model_size: str) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise WhisperClientError(
            "faster-whisper未インストール。`pip install faster-whisper` を実行してください"
        ) from e

    logger.info("faster-whisper モデルロード: %s", model_size)
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    segments_iter, info = model.transcribe(
        audio_path,
        language=language,
        word_timestamps=True,
        vad_filter=True,
    )

    segments_list = []
    words_list = []
    full_text_parts = []
    for seg in segments_iter:
        seg_text = (seg.text or "").strip()
        if seg_text:
            full_text_parts.append(seg_text)
        segments_list.append({
            "start": float(seg.start),
            "end": float(seg.end),
            "text": seg_text,
        })
        for w in (seg.words or []):
            words_list.append({
                "start": float(w.start),
                "end": float(w.end),
                "word": w.word.strip(),
            })

    return {
        "text": " ".join(full_text_parts),
        "segments": segments_list,
        "words": words_list,
        "duration": float(info.duration or 0.0),
    }


def _transcribe_openai(audio_path: str, language: str, key: str) -> dict:
    from openai import OpenAI

    client = OpenAI(api_key=key)

    logger.info("Whisper API呼び出し: %s", os.path.basename(audio_path))
    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language=language,
            response_format="verbose_json",
            timestamp_granularities=["segment", "word"],
        )

    segments = []
    for seg in getattr(response, "segments", None) or []:
        segments.append({
            "start": float(seg.start if hasattr(seg, "start") else seg["start"]),
            "end": float(seg.end if hasattr(seg, "end") else seg["end"]),
            "text": str(seg.text if hasattr(seg, "text") else seg["text"]).strip(),
        })

    words = []
    for w in getattr(response, "words", None) or []:
        words.append({
            "start": float(w.start if hasattr(w, "start") else w["start"]),
            "end": float(w.end if hasattr(w, "end") else w["end"]),
            "word": str(w.word if hasattr(w, "word") else w["word"]),
        })

    return {
        "text": response.text,
        "segments": segments,
        "words": words,
        "duration": float(getattr(response, "duration", 0.0) or 0.0),
    }
