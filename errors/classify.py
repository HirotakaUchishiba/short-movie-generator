"""error 文字列から error_type を推定し、UI 表示用の actionable_hint を返す。

設計方針:
- 例外型 introspection は SDK 依存が広がるので避け、**文字列 match のみ** で
  分類する。例外を渡された場合は str(exc) に変換してから match する。
- 確実な順序で match (= 上から優先)。複数マッチ可能な場合は明示的に先勝ち。
- 未分類は ``unknown``。actionable_hint は固定文言にし、message は raw を残す。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# ─────────── 既知 type 一覧 (= 8 種 + unknown) ───────────

ERROR_TYPES: tuple[str, ...] = (
    "credit_exhausted",
    "rate_limit",
    "auth_failure",
    "quota_exceeded",
    "context_too_long",
    "safety_filter",
    "network_timeout",
    "disk_full",
    "unknown",
)

# 各 type のデフォルト actionable_hint (= UI に表示する固定文言)。
_DEFAULT_HINTS: dict[str, str] = {
    "credit_exhausted": (
        "API クレジットが不足しています。"
        "プロバイダのダッシュボードでクレジット購入後、リトライしてください。"
    ),
    "rate_limit": "API レート制限に達しました。数分待ってリトライしてください。",
    "auth_failure": (
        "API 認証に失敗しました。.env の API key / OAuth token を確認してください。"
    ),
    "quota_exceeded": (
        "API クォータを超過しました。"
        "翌日のクォータ復帰を待つか、別アカウントに切替えてください。"
    ),
    "context_too_long": (
        "入力が大きすぎます (= context window 超過)。"
        "動画を短くするか fps を下げてリトライしてください。"
    ),
    "safety_filter": (
        "プロバイダの safety filter に該当しました。"
        "プロンプト / 入力を調整して再試行してください。"
    ),
    "network_timeout": (
        "ネットワーク接続が不安定です。接続を確認して再試行してください。"
    ),
    "disk_full": (
        "ディスク容量が不足しています。空き容量を確保してリトライしてください。"
    ),
    "unknown": "原因の自動分類はできませんでした。詳細は message を確認してください。",
}

# message :2000 字截断 (= 巨大 JSON / stack trace の混入を抑止)
_MESSAGE_MAX_LEN = 2000

# request_id の抽出 (= Anthropic / OpenAI 等は req_xxx 形式)。
_REQUEST_ID_RE = re.compile(
    r"(req[_-][A-Za-z0-9]+|request[_-]id['\":\s]+([A-Za-z0-9_-]+))",
    re.IGNORECASE,
)


def classify_error(error: Exception | str | None) -> str:
    """error message を 9 種類 (8 + unknown) のいずれかに分類する。

    例外を渡された場合は ``str(error)`` で文字列化してから match する。
    None / 空文字は "unknown"。
    """
    if error is None:
        return "unknown"
    text = str(error) if not isinstance(error, str) else error
    if not text:
        return "unknown"
    low = text.lower()

    # 1. credit_exhausted (= 最頻出、最優先で判定)
    # 既知のパターン:
    # - Anthropic: "Your credit balance is too low"
    # - fal.ai: "exhausted balance"
    # - OpenAI: "exceeded your current quota" (= billing-related quota も含む)
    # - 汎用: "out of credit" / "insufficient credit" / "balance is too low"
    if any(
        kw in low
        for kw in (
            "credit balance",
            "out of credit",
            "exhausted balance",
            "insufficient credit",
            "balance is too low",
            "balance too low",
            "billing",
        )
    ):
        return "credit_exhausted"

    # 2. context_too_long (= 400 系で credit より先に判定)
    if any(
        kw in low
        for kw in (
            "input is too long",
            "context window",
            "context_length",
            "maximum context",
        )
    ):
        return "context_too_long"

    # 3. auth_failure (= 401 / 403 / "invalid api key")
    if any(
        kw in low
        for kw in (
            "invalid api key",
            "authentication_error",
            "unauthenticated",
            "unauthorized",
            "401",
            "403 ",  # 末尾 space で quota_exceeded の "403:" と区別
        )
    ):
        # 「403」単独 (= quota の可能性) は次の quota check に譲る
        if "quota" not in low and "rate" not in low:
            return "auth_failure"

    # 4. rate_limit
    if any(kw in low for kw in ("rate_limit", "rate limit", "429", "too many requests")):
        return "rate_limit"

    # 5. quota_exceeded
    if any(
        kw in low
        for kw in (
            "quota",
            "daily limit",
            "monthly limit",
            "usage limit",
            "quotaexceeded",
        )
    ):
        return "quota_exceeded"

    # 6. safety_filter
    if any(
        kw in low
        for kw in (
            "safety",
            "policy violation",
            "blocked by",
            "responsibleai",
            "content_filter",
        )
    ):
        return "safety_filter"

    # 7. network_timeout
    if any(
        kw in low
        for kw in (
            "apiconnectionerror",
            "apitimeouterror",
            "connection error",
            "timed out",
            "timeout",
            "socket",
            "network is unreachable",
            "name resolution",
        )
    ):
        return "network_timeout"

    # 8. disk_full
    if any(
        kw in low
        for kw in (
            "no space left",
            "enospc",
            "disk full",
            "disk space",
        )
    ):
        return "disk_full"

    return "unknown"


def _extract_request_id(text: str) -> str | None:
    """error message から request_id を抽出する (= Anthropic / OpenAI 等)。"""
    m = _REQUEST_ID_RE.search(text)
    if not m:
        return None
    # group(1) が "req_xxx" 形式 or "request_id: xxx" の前半。
    # 後者の場合 group(2) が実 id。
    raw = m.group(1)
    if raw.lower().startswith(("req_", "req-")):
        return raw
    # "request_id: xxx" 形式
    return m.group(2)


def build_error_detail(
    error: Exception | str | None,
    *,
    retry_cost_estimate_usd: float | None = None,
    occurred_at: str | None = None,
    actionable_hint: str | None = None,
    failed_phase: str | None = None,
) -> dict[str, Any]:
    """構造化 error envelope を生成する。

    Args:
        error: 例外 or message 文字列
        retry_cost_estimate_usd: pricebook 履歴 median から算定した retry コスト
        occurred_at: ISO8601 タイムスタンプ (= 省略時は now)
        actionable_hint: type 既定の hint を上書きする場合に指定
        failed_phase: 失敗した sub-phase 名 (= analyze の claude / whisper 等)。
            外側 stage と区別したい時に使う。Stage 1-6 では None で良い。

    Returns:
        ``{type, message, request_id, actionable_hint, retry_cost_estimate_usd,
        occurred_at, failed_phase}`` の dict。すべて UI 側で optional 扱い。
    """
    text = "" if error is None else str(error)
    truncated = text[:_MESSAGE_MAX_LEN]
    err_type = classify_error(text)
    return {
        "type": err_type,
        "message": truncated,
        "request_id": _extract_request_id(text),
        "actionable_hint": actionable_hint or _DEFAULT_HINTS[err_type],
        "retry_cost_estimate_usd": retry_cost_estimate_usd,
        "occurred_at": occurred_at or datetime.now().isoformat(timespec="seconds"),
        "failed_phase": failed_phase,
    }
