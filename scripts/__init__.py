"""scripts/ パッケージ。CLI 直接実行 (``python3 scripts/xxx.py``) と
``python -m scripts.xxx`` の両方をサポート。

``python -m scripts.xxx`` のときは本ファイル経由で ``_cli_base`` が import
され、sys.path 追加 + ``log_setup.setup()`` が事前に走る。直接実行のときは
各 script 先頭の ``from scripts._cli_base import get_logger`` が同じ
副作用を起こす (= ``_cli_base`` import 時に sys.path / log_setup が設定)。
"""

from . import _cli_base  # noqa: F401
