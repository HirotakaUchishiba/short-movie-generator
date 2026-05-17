"""scripts/ 配下 CLI の共通基盤。

各 CLI script が個別に書いていた boilerplate (= sys.path 追加 /
``log_setup.setup()`` / logger 初期化) をここに集約する。新規 script は
本モジュールから ``get_logger`` を import し、boilerplate を再実装しない。

直接実行 (``python3 scripts/xxx.py``) と ``python -m scripts.xxx`` の
両方で動く。

Usage:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts._cli_base import get_logger

    logger = get_logger(__name__)

    def main() -> int:
        ...

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.4
"""

import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import log_setup  # noqa: E402

log_setup.setup()


def get_logger(name: str) -> logging.Logger:
    """script 用 logger を返す (= ``LOG_LEVEL`` / ``LOG_FILE`` env 反映済)。"""
    return logging.getLogger(name)
