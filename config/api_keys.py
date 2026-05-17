"""API key 環境変数の集約。各 client は ``from config import X`` で参照する
(= config パッケージ移行中は ``from config.api_keys import X`` も両方動く)。

参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.1.4
"""

import os

from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
FAL_API_KEY = os.getenv("FAL_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SYNCSO_API_KEY = os.getenv("SYNC_API_KEY") or os.getenv("SYNCSO_API_KEY")
