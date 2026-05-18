"""グローバルキャッシュ関連の設定 (= BG_CACHE / KLING_CACHE / CLIP_LIBRARY)。

config/__init__.py から段階分割 (= §3.1.4-b)。Stage 3 / Stage 4 で別動画
でも入力が同一なら使い回すための cache 設定。判定階層 L1-L4 の詳細は
docs/developments/clip-library.md を参照。

BASE_DIR は config/__init__.py 経由で再計算する (= 循環依存回避のため
ここでも独自計算)。
"""

import os

# config/__init__.py と同じ BASE_DIR 計算 (= project root を指す)。
# package 化後の __file__ は config/ 配下なので dirname を 2 段上げる。
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Stage 3 背景画像のグローバルキャッシュ (= 別動画でも入力が同一なら使い回す)。
# キャッシュキーは bg_cache.compute_bg_cache_key で background_prompt +
# character_refs sha + location sha + Imagen モデル ID から派生される。
BG_CACHE_DIR = os.path.join(_BASE_DIR, "cache", "bg_images")
BG_CACHE_ENABLED = os.getenv("BG_CACHE_ENABLED", "1") not in ("0", "false", "False")
BG_CACHE_VERSION = os.getenv("BG_CACHE_VERSION", "v1")
# L3: 元プロジェクトで Stage 3 が承認済みのものだけ hit させるか
BG_CACHE_REQUIRE_APPROVAL = os.getenv(
    "BG_CACHE_REQUIRE_APPROVAL", "0") not in ("0", "false", "False")
# L3: cache age TTL (日)
BG_CACHE_TTL_DAYS = int(os.getenv("BG_CACHE_TTL_DAYS", "365"))

# Stage 4 Kling 動画のグローバルキャッシュ。
# キャッシュキーは kling_cache.build_cache_key で augmented_animation_prompt +
# kling_duration + bg_image_sha + model_id + aspect_ratio + cache_version から派生。
# 最終的には外部 SSD (= KLING_CACHE_DIR を /Volumes/SSD4TB/... に上書き) で運用。
KLING_CACHE_DIR = os.environ.get(
    "KLING_CACHE_DIR", os.path.join(_BASE_DIR, "cache", "kling_videos"))
KLING_CACHE_ENABLED = os.getenv("KLING_CACHE_ENABLED", "1") not in ("0", "false", "False")
KLING_CACHE_VERSION = os.getenv("KLING_CACHE_VERSION", "v1")
# LRU prune の容量上限。デフォルト 2TB = 4TB SSD の半分。
KLING_CACHE_MAX_BYTES = int(os.environ.get("KLING_CACHE_MAX_GB", "2000")) * 1024 ** 3
# store のたびに自動 prune するか
KLING_CACHE_AUTO_PRUNE = os.getenv("KLING_CACHE_AUTO_PRUNE", "1") not in ("0", "false", "False")
# L2 適合度: 元 audio との乖離率上限 (= 30% 違うと reject)
KLING_CACHE_MISMATCH_THRESHOLD = float(os.getenv("KLING_CACHE_MISMATCH_THRESHOLD", "0.30"))
# L3: 元プロジェクトで Stage 4 が承認済みのものだけ hit させるか
KLING_CACHE_REQUIRE_APPROVAL = os.getenv(
    "KLING_CACHE_REQUIRE_APPROVAL", "0") not in ("0", "false", "False")
# L3: cache age TTL (日)
KLING_CACHE_TTL_DAYS = int(os.getenv("KLING_CACHE_TTL_DAYS", "365"))

# Compositional Architecture Layer 1 (Clip Library)
# screenplay の identity (= character_refs / location_ref / start_emotion /
# camera_distance) が一致するクリップ群を 1 つの "pool" として扱い、その中から
# annotation でランクして top-k を variant pool として返す。同じ identity の
# 別 screenplay は同じ pool を参照するため、warm 状態で AI 課金が大幅に減る。
CLIP_LIBRARY_DIR = os.environ.get(
    "CLIP_LIBRARY_DIR", os.path.join(_BASE_DIR, "cache", "clips"))
CLIP_LIBRARY_ENABLED = os.getenv(
    "CLIP_LIBRARY_ENABLED", "0") not in ("0", "false", "False")
# Major 改修時に bump して全 pool を miss 化する手動 invalidation の鍵。
CLIP_LIBRARY_VERSION = os.getenv("CLIP_LIBRARY_VERSION", "v1")
# 1 identity あたり pool に貯める variant の目標数 (= 既定 10)。
CLIP_POOL_TARGET_SIZE = int(os.getenv("CLIP_POOL_TARGET_SIZE", "10"))
# lookup_clip_pool が返す top-k の k。variant 選択は seed で決定論的に行う。
CLIP_POOL_TOP_K = int(os.getenv("CLIP_POOL_TOP_K", "10"))
# LRU prune 上限 (= GB)。デフォルト 100GB。超過時に hit_count + last_used_at で
# 80% まで縮退する。
CLIP_POOL_MAX_TOTAL_GB = int(os.getenv("CLIP_POOL_MAX_TOTAL_GB", "100"))
# 新規 entry の status: pending_review (= 既定、UI 承認待ち) か active 直送か
CLIP_POOL_AUTO_APPROVE = os.getenv(
    "CLIP_POOL_AUTO_APPROVE", "0") not in ("0", "false", "False")
