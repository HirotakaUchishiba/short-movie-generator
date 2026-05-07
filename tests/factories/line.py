"""Line (= 1 セリフ) のファクトリ。"""

from typing import Any


def make_line(
    text: str = "やばい",
    *,
    start: float = 0.0,
    end: float = 1.0,
    emotion: str = "焦り",
    delivery: str | None = None,
    audio_tags: list[str] | None = None,
    pronunciation_hints: dict[str, str] | None = None,
    voice_overrides: dict[str, Any] | None = None,
    **overrides: Any,
) -> dict:
    line: dict = {
        "text": text,
        "start": start,
        "end": end,
        "emotion": emotion,
    }
    if delivery is not None:
        line["delivery"] = delivery
    if audio_tags is not None:
        line["audio_tags"] = audio_tags
    if pronunciation_hints is not None:
        line["pronunciation_hints"] = pronunciation_hints
    if voice_overrides is not None:
        line["voice_overrides"] = voice_overrides
    line.update(overrides)
    return line
