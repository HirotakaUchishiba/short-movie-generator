"""外部 API client の共通基盤。

retry / backoff / exception hierarchy / response parsing を一元化する。
各 API client (elevenlabs / imagen / fal_video / lipsync / video_analyzer /
gemini_rewriter) は本モジュールから ``APIClientError`` を継承し、共通の
分類規約と retry interface に合わせる。

段階移行: 既存 client の retry 機構は当面据え置き、新規 client / 改修 client
から ``call_with_retry()`` を採用する。最終的には 6 client すべてを
本モジュール経由に集約する (= 計画書 §3.2 完了条件)。

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.2
"""

from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

T = TypeVar("T")

_logger = logging.getLogger(__name__)


class APIClientError(RuntimeError):
    """全外部 API client 例外の親クラス。

    既存 ``ElevenLabsClientError`` / ``FalClientError`` / ``LipsyncClientError``
    は本クラスを継承する (= caller が ``except APIClientError`` で provider
    非依存に拾える形に統一)。

    Attributes:
        status: HTTP status code (= API が status を返さない / SDK 経由の場合は
            None)。
        retryable: caller が retry すべきかの hint (= 情報用、retry は通常
            ``call_with_retry()`` の classify 関数で判定する)。
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def call_with_retry(
    fn: Callable[[], T],
    *,
    max_retries: int,
    backoff_seconds: list[float],
    classify: Callable[[BaseException], str] | None = None,
    logger: logging.Logger | None = None,
    context: str = "API",
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """``fn`` を retry + backoff 付きで呼び出す。

    ``classify(exc) -> "retry" | "fail"`` で例外を分類。``"fail"`` は即座に
    raise、``"retry"`` は backoff 後に再試行。``max_retries`` 回試して失敗
    したら最後の例外を再 raise する。``classify=None`` なら全例外を retry
    扱い。

    ``backoff_seconds[i]`` は i 回目失敗後の待ち秒数。
    ``len(backoff_seconds) < max_retries`` なら末尾値を流用する。

    ``sleep`` は test 時に ``lambda _: None`` で差し替え可能。
    """
    log = logger or _logger
    last_exc: BaseException | None = None
    for attempt in range(max_retries):
        try:
            return fn()
        except BaseException as exc:
            last_exc = exc
            classification = classify(exc) if classify else "retry"
            if classification == "fail":
                raise
            if attempt >= max_retries - 1:
                break
            wait = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
            log.warning(
                "%s 失敗 (%d回目/%d): %s — %.1f秒後にリトライ",
                context, attempt + 1, max_retries, exc, wait,
            )
            sleep(wait)
    assert last_exc is not None
    raise last_exc
