"""Lipsync / Sync.so 関連の設定 (= timeout / model / polling 間隔)。

config/__init__.py から段階分割 (= §3.1.4-b)。timeout は QUERY / SUBMIT /
UPLOAD / DOWNLOAD の 4 系統に分かれる (= lipsync provider への HTTP 用途別)。
"""

import os

# lipsync provider への HTTP request timeout (秒)
# QUERY = status / presigned upload, SUBMIT = task 作成,
# UPLOAD = multipart submit, DOWNLOAD = result fetch
LIPSYNC_HTTP_TIMEOUT_QUERY_SEC = 30
LIPSYNC_HTTP_TIMEOUT_SUBMIT_SEC = 60
LIPSYNC_HTTP_TIMEOUT_UPLOAD_SEC = 120
LIPSYNC_HTTP_TIMEOUT_DOWNLOAD_SEC = 300

LIPSYNC_ENABLED = os.getenv("LIPSYNC_ENABLED", "true").lower() == "true"
LIPSYNC_SYNC_MODE = os.getenv("LIPSYNC_SYNC_MODE", "cut_off")
# コスト単価は data/pricebook.json で管理し、実コストは cost_tracking モジュールが
# data/cost_records.jsonl に記録する (= ハードコード単価は廃止)。

# Sync.so 用 (POST /v2/generate multipart, GET /v2/generate/{id} polling)
# モデル: lipsync-2 (汎用), lipsync-2-pro (高品質), lipsync-1.9.0-beta (高速),
# react-1 (短尺・感情豊か), sync-3
SYNCSO_BASE_URL = os.getenv("SYNCSO_BASE_URL", "https://api.sync.so/v2")
SYNCSO_LIPSYNC_MODEL = os.getenv("SYNCSO_LIPSYNC_MODEL", "lipsync-2")
SYNCSO_POLL_INTERVAL_SEC = float(os.getenv("SYNCSO_POLL_INTERVAL_SEC", "3.0"))
SYNCSO_POLL_TIMEOUT_SEC = float(os.getenv("SYNCSO_POLL_TIMEOUT_SEC", "1800"))
SYNCSO_MAX_FILE_MB = 20
