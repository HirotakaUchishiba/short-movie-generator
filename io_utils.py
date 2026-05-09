"""ファイル I/O 共通ヘルパ。

外部 API (Imagen / FAL Kling / lipsync 各 provider) の生成物書き込みは
このモジュール経由でアトミックに行う。プロセス kill / クラッシュで
truncated PNG / mp4 が disk に残ると、再実行時に `os.path.exists` が
True を返してそのまま skip → 下流に破損ファイルが流れる事故を防ぐため。

書き込みパターン:
    1. `<path>.tmp` に全バイトを write して fsync
    2. `os.replace(<path>.tmp, <path>)` で atomic に rename
    3. tmp ファイルは失敗時に best-effort で削除
"""

import json
import logging
import os
import random
from typing import Any

logger = logging.getLogger(__name__)


def parse_retry_after(value: str | None) -> float | None:
    """HTTP `Retry-After` ヘッダを秒数 (float) に変換する。

    値は秒数 (= "30") か HTTP-date フォーマットを取り得る。HTTP-date は本プロジェクト
    では使われないので秒数のみ対応。パースできなければ None。
    """
    if not value:
        return None
    try:
        n = float(value.strip())
    except (TypeError, ValueError):
        return None
    return max(0.0, n)


def next_backoff_seconds(attempt: int, schedule: list[float] | tuple[float, ...],
                         *, jitter: float = 0.3,
                         retry_after: float | None = None) -> float:
    """retry の待ち秒数を返す。

    Args:
        attempt: 0-origin の試行番号 (= 失敗した直後の次の wait 計算)。
        schedule: ベース backoff 秒数のリスト。範囲外は最後の値で saturate。
        jitter: ±jitter 比率 (例 0.3 → ±30%)。0 なら deterministic。
        retry_after: HTTP `Retry-After` ヘッダ由来の秒数。指定があればそれを優先
            (= サーバが意図した cool-down)。ただし jitter は適用する (thundering herd 防止)。

    Returns:
        待ち秒数 (= 0 以上)。
    """
    if retry_after is not None:
        base = retry_after
    elif schedule:
        idx = min(attempt, len(schedule) - 1)
        base = float(schedule[idx])
    else:
        base = 1.0
    if jitter > 0:
        # ±jitter の一様乱数で thundering herd を散らす
        spread = base * jitter
        base += random.uniform(-spread, spread)
    return max(0.0, base)


def atomic_write_bytes(path: str, data: bytes) -> None:
    """data を path にアトミックに書き込む。

    途中失敗しても path は古い内容のまま残る (= 半端ファイルにならない)。
    """
    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError as e:
            logger.warning("[atomic-write] tmp %s 削除失敗: %s", tmp, e)
        raise


def atomic_write_text(path: str, text: str, encoding: str = "utf-8") -> None:
    """text を path にアトミックに書き込む (UTF-8 既定)。"""
    atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(path: str, obj: Any, *, indent: int = 2,
                      ensure_ascii: bool = False) -> None:
    """obj を JSON シリアライズして path にアトミックに書き込む。"""
    raw = json.dumps(obj, ensure_ascii=ensure_ascii, indent=indent)
    atomic_write_text(path, raw)
