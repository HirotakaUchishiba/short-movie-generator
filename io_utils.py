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
from typing import Any

logger = logging.getLogger(__name__)


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
