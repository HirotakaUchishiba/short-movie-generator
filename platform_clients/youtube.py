"""YouTube Data API v3 / Analytics API クライアント + resumable uploader。

環境変数:
    YOUTUBE_API_KEY                  公開統計(views/likes/comments/duration)用
    YOUTUBE_OAUTH_CLIENT_ID          Analytics / Upload API 用 (OAuth Desktop App)
    YOUTUBE_OAUTH_CLIENT_SECRET
    YOUTUBE_REFRESH_TOKEN            初回認可後に取得、.env保存推奨
                                     (upload を使うなら youtube.upload scope 同意必須)
    YOUTUBE_PROFILE                  (任意) 投稿先チャンネル切替用の profile 名。
                                     設定すると同名 suffix の env を優先する
                                     (例: YOUTUBE_PROFILE=BRAND →
                                      YOUTUBE_OAUTH_CLIENT_ID_BRAND を読む)。
                                     未設定なら従来通り suffix なし env を読む。
"""
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import io_utils

# resumable upload state を保存する JSON のキー (= temp/<TS>/upload_state_youtube.json)。
# YouTube の resumable upload URL 公式 TTL は 7 日だが、unstable network での
# stale link を避けるため 24h で破棄する保守設定。
UPLOAD_STATE_TTL_SEC = 24 * 3600

logger = logging.getLogger(__name__)

DATA_API_BASE = "https://www.googleapis.com/youtube/v3"
ANALYTICS_API_BASE = "https://youtubeanalytics.googleapis.com/v2"
UPLOAD_API_BASE = "https://www.googleapis.com/upload/youtube/v3/videos"
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
DEFAULT_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
DEFAULT_CATEGORY_ID = "22"  # People & Blogs

REFRESH_TOKEN_GUIDANCE = (
    "YOUTUBE_REFRESH_TOKEN が無効です (取り消し / 期限切れの可能性)。"
    "OAuth flow で再取得してください "
    "(https://developers.google.com/youtube/v3/quickstart/python)"
)


def _resolve_privacy(requested: str) -> str:
    """``AUTO_LOOP_ALLOW_PUBLIC=0`` の間は ``public`` を ``unlisted`` に書き換える。

    Phase 4 まで本番アカウント公開は人間 gate を通すための保険。
    意図的に public を出したい場合は env を ``1`` にするか直接 YouTube Studio で
    切り替える運用。

    比較は case-insensitive。YouTube API 自体は lowercase を要求するので、
    入力が "Public" / "PUBLIC" 等の場合も降格判定をくぐらせ、戻り値は
    必ず lowercase に正規化する (= caller が誤った casing を渡しても
    API レイヤで弾かれる前にここで吸収)。
    """
    import config
    normalized = (requested or "").strip().lower()
    if normalized == "public" and not config.AUTO_LOOP_ALLOW_PUBLIC:
        logger.warning(
            "[youtube] privacy=public が指定されましたが AUTO_LOOP_ALLOW_PUBLIC=0 の "
            "ため unlisted に強制します。意図的に public 公開したい場合は "
            "AUTO_LOOP_ALLOW_PUBLIC=1 を設定してください。",
        )
        return "unlisted"
    return normalized or requested


def _iso_duration_to_seconds(dur: str) -> float:
    """ISO 8601 duration 'PT1M30S' → 90.0"""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur or "")
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h or 0) * 3600 + int(mi or 0) * 60 + int(s or 0)


def fetch_public_stats(video_id: str, api_key: str | None = None) -> dict:
    """YouTube Data API v3 で公開統計を取得。"""
    import requests

    key = api_key or os.getenv("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY未設定")

    resp = requests.get(
        f"{DATA_API_BASE}/videos",
        params={
            "id": video_id,
            "part": "statistics,contentDetails,snippet",
            "key": key,
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    items = data.get("items") or []
    if not items:
        raise RuntimeError(f"YouTube動画が見つかりません: {video_id}")

    item = items[0]
    stats = item.get("statistics", {})
    content = item.get("contentDetails", {})
    snippet = item.get("snippet", {})

    return {
        "views": int(stats.get("viewCount", 0) or 0),
        "likes": int(stats.get("likeCount", 0) or 0),
        "comments": int(stats.get("commentCount", 0) or 0),
        "favorites": int(stats.get("favoriteCount", 0) or 0),
        "duration_sec": _iso_duration_to_seconds(content.get("duration", "")),
        "title": snippet.get("title"),
        "published_at": snippet.get("publishedAt"),
        "raw_response": item,
    }


def _resolve_oauth_env() -> tuple[str | None, str | None, str | None]:
    """OAuth 3 値を env から解決する (= profile 切替対応)。

    ``YOUTUBE_PROFILE`` が設定されていれば suffix 付き env を優先する
    (例: profile=BRAND → YOUTUBE_OAUTH_CLIENT_ID_BRAND を読む)。
    suffix 付き env が空 / 未設定なら suffix なし env (= 従来動作) を返す。

    Returns: ``(client_id, client_secret, refresh_token)`` — いずれも
    ``None`` の可能性があり、呼び出し側で ``all()`` チェックする。
    """
    profile = (os.environ.get("YOUTUBE_PROFILE") or "").strip().upper()

    def _get(name: str) -> str | None:
        if profile:
            v = os.environ.get(f"YOUTUBE_{name}_{profile}")
            if v:
                return v
        return os.environ.get(f"YOUTUBE_{name}")

    return _get("OAUTH_CLIENT_ID"), _get("OAUTH_CLIENT_SECRET"), _get("REFRESH_TOKEN")


def _resolve_channel_label() -> dict:
    """投稿先チャンネルの診断情報を返す (= channel guard / debug 用)。

    取得可能な範囲で ``profile`` / ``aud`` / ``scopes`` / ``title`` /
    ``channel_id`` / ``error`` を返す。``title`` と ``channel_id`` は
    ``youtube.readonly`` (もしくは ``youtube`` / ``youtube.force-ssl``)
    scope が同意済みのときだけ取れる。
    """
    import requests

    profile_raw = (os.environ.get("YOUTUBE_PROFILE") or "").strip()
    info: dict = {"profile": profile_raw or "(default)"}

    cid, csec, rtok = _resolve_oauth_env()
    if not all([cid, csec, rtok]):
        info["error"] = "OAuth env (CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN) 未設定"
        return info

    try:
        token = _oauth_access_token(cid, csec, rtok)
    except Exception as e:
        info["error"] = f"oauth token 取得失敗: {e}"
        return info

    try:
        r = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"access_token": token},
            timeout=10,
        )
        if r.ok:
            d = r.json()
            info["aud"] = d.get("aud")
            info["scopes"] = (d.get("scope") or "").split()
    except Exception as e:
        logger.warning("[youtube] tokeninfo 取得失敗: %s", e)

    has_read = any(
        s in info.get("scopes", [])
        for s in (
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/youtube",
            "https://www.googleapis.com/auth/youtube.force-ssl",
        )
    )
    if has_read:
        try:
            r = requests.get(
                f"{DATA_API_BASE}/channels",
                params={"part": "snippet", "mine": "true"},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if r.ok:
                items = r.json().get("items", [])
                if items:
                    sn = items[0].get("snippet", {})
                    info["title"] = sn.get("title")
                    info["channel_id"] = items[0].get("id")
        except Exception as e:
            logger.warning("[youtube] channels?mine=true 取得失敗: %s", e)

    return info


def _oauth_access_token(client_id: str, client_secret: str,
                        refresh_token: str) -> str:
    """refresh_token から access_token を取得。

    transient エラー (5xx / ConnectionError) は exponential backoff で 2 回 retry。
    400/401 (= refresh_token 自体が無効) は即座に明示的な RuntimeError を上げる
    (= ユーザに OAuth 再取得を促す)。
    """
    import requests

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=15,
            )
        except requests.ConnectionError as e:
            last_exc = e
            if attempt < 2:
                time.sleep(2 ** attempt)
                logger.warning("oauth token endpoint 接続失敗 (retry %d/2): %s",
                               attempt + 1, e)
                continue
            raise
        if resp.status_code in (400, 401):
            raise RuntimeError(REFRESH_TOKEN_GUIDANCE)
        if 500 <= resp.status_code < 600:
            last_exc = RuntimeError(
                f"oauth token endpoint {resp.status_code}: {resp.text[:200]}",
            )
            if attempt < 2:
                time.sleep(2 ** attempt)
                logger.warning("oauth token endpoint 5xx (retry %d/2): %s",
                               attempt + 1, resp.status_code)
                continue
            raise last_exc
        resp.raise_for_status()
        return resp.json()["access_token"]
    if last_exc:
        raise last_exc
    raise RuntimeError("oauth token 取得に失敗しました")


def fetch_analytics(video_id: str,
                    start_date: str | None = None,
                    end_date: str | None = None) -> dict:
    """YouTube Analytics API で詳細メトリクスを取得（要OAuth、自チャンネル動画のみ）。"""
    import requests

    client_id, client_secret, refresh_token = _resolve_oauth_env()
    if not all([client_id, client_secret, refresh_token]):
        raise RuntimeError(
            "YouTube Analytics認証情報が未設定 "
            "(YOUTUBE_OAUTH_CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN)"
        )

    token = _oauth_access_token(client_id, client_secret, refresh_token)

    if not start_date:
        start_date = (date.today() - timedelta(days=30)).isoformat()
    if not end_date:
        end_date = date.today().isoformat()

    # core metrics は単一 request で。`impressions` / `impressionsClickThroughRate`
    # は同一 query に混ぜると YouTube 側で 400 になるケースがあるので別 request
    # (= _fetch_impressions_metrics) に分離する。
    metrics = ",".join([
        "views", "likes", "comments", "shares",
        "averageViewDuration", "averageViewPercentage",
        "estimatedMinutesWatched", "subscribersGained",
    ])

    resp = requests.get(
        f"{ANALYTICS_API_BASE}/reports",
        params={
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
            "metrics": metrics,
            "filters": f"video=={video_id}",
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    rows = data.get("rows") or []
    if not rows:
        return {"raw_response": data}

    headers = [h["name"] for h in data.get("columnHeaders", [])]
    values = rows[0]
    m = dict(zip(headers, values))

    watch_sec = float(m.get("estimatedMinutesWatched", 0) or 0) * 60.0
    avg_view_duration = float(m.get("averageViewDuration", 0) or 0)
    avg_view_pct = float(m.get("averageViewPercentage", 0) or 0)

    result: dict[str, Any] = {
        "views": int(m.get("views", 0) or 0),
        "likes": int(m.get("likes", 0) or 0),
        "comments": int(m.get("comments", 0) or 0),
        "shares": int(m.get("shares", 0) or 0),
        "watch_time_sec": watch_sec,
        "avg_view_duration": avg_view_duration,
        "completion_rate": avg_view_pct / 100.0 if avg_view_pct else None,
        # schema v10: subscribersGained は core query に含まれるので即座に拾う。
        "subscribers_gained": int(m.get("subscribersGained", 0) or 0),
        "raw_response": data,
    }

    # impressions / CTR は別 query (= dimension / metrics 互換性の都合)。
    # 失敗しても core 値の return は壊さず、None を残す。
    try:
        impressions_data = _fetch_impressions_metrics(
            video_id, token, start_date, end_date,
        )
        result["impressions"] = impressions_data.get("impressions")
        result["ctr"] = impressions_data.get("ctr")
    except Exception as e:
        logger.info("YouTube impressions/CTR 取得スキップ (%s): %s", video_id, e)
        result["impressions"] = None
        result["ctr"] = None

    return result


def _fetch_impressions_metrics(video_id: str, token: str,
                               start_date: str, end_date: str) -> dict:
    """impressions / impressionsClickThroughRate を別 request で取る。

    YouTube Analytics は metrics 同居制約 (= 一部 metric は他と同 query 不可) が
    あるため、core metrics とは分離した request にする。``rows`` が空の場合は
    両方 None を返す (= 視聴閾値未満で API がデータを返さないケース)。
    """
    import requests

    resp = requests.get(
        f"{ANALYTICS_API_BASE}/reports",
        params={
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
            "metrics": "impressions,impressionsClickThroughRate",
            "filters": f"video=={video_id}",
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    rows = data.get("rows") or []
    if not rows:
        return {"impressions": None, "ctr": None}
    headers = [h["name"] for h in data.get("columnHeaders", [])]
    m = dict(zip(headers, rows[0]))
    impressions_raw = m.get("impressions")
    ctr_raw = m.get("impressionsClickThroughRate")
    return {
        "impressions": int(impressions_raw) if impressions_raw not in (None, "") else None,
        "ctr": (float(ctr_raw) / 100.0) if ctr_raw not in (None, "") else None,
    }


# 主要 trafficSourceType ラベル → post_metrics の percent 列のマッピング。
# YouTube Analytics の insightTrafficSourceType は他にも CHANNEL / NOTIFICATION
# 等があるが、PDCA で見たい "アルゴリズム配信 vs 検索 vs 外部" を区別するための
# 4 区分に集約する。未知のラベルは "other" 扱いで合計算出には使うが書き戻さない。
_TRAFFIC_TYPE_TO_KEY = {
    "YT_BROWSE": "traffic_browse_pct",
    "RELATED_VIDEO": "traffic_suggested_pct",
    "YT_SEARCH": "traffic_search_pct",
    "EXT_URL": "traffic_external_pct",
}


def fetch_traffic_sources(video_id: str,
                          start_date: str | None = None,
                          end_date: str | None = None) -> dict:
    """dimensions=insightTrafficSourceType で流入経路別の views share を返す。

    Browse / Suggested / Search / External の 4 区分を percent (0.0-1.0) で
    返す。``rows`` が空 (= 視聴数 0) の場合は raw_response のみ返す。
    """
    import requests

    client_id, client_secret, refresh_token = _resolve_oauth_env()
    if not all([client_id, client_secret, refresh_token]):
        raise RuntimeError(
            "YouTube Analytics認証情報が未設定 "
            "(YOUTUBE_OAUTH_CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN)"
        )

    token = _oauth_access_token(client_id, client_secret, refresh_token)

    if not start_date:
        start_date = (date.today() - timedelta(days=30)).isoformat()
    if not end_date:
        end_date = date.today().isoformat()

    resp = requests.get(
        f"{ANALYTICS_API_BASE}/reports",
        params={
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": "insightTrafficSourceType",
            "metrics": "views",
            "filters": f"video=={video_id}",
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    rows = data.get("rows") or []
    if not rows:
        return {"raw_response": data}

    by_type: dict[str, int] = {}
    total = 0
    for row in rows:
        if len(row) < 2:
            continue
        ts_type = str(row[0])
        views = int(row[1] or 0)
        by_type[ts_type] = views
        total += views

    if total <= 0:
        return {"raw_response": data}

    out: dict[str, Any] = {"raw_response": data}
    for label, key in _TRAFFIC_TYPE_TO_KEY.items():
        out[key] = by_type.get(label, 0) / total
    return out


def fetch_retention_curve(video_id: str,
                          start_date: str | None = None,
                          end_date: str | None = None,
                          duration_sec: float | None = None) -> dict:
    """dimensions=elapsedVideoTimeRatio で audience retention curve を返す。

    Returns:
        ``{"curve": [{elapsed_pct, ratio, elapsed_sec?}, ...], "raw_response": ...}``
        視聴数が YouTube の閾値に届かない動画では空 curve が返る (= API 仕様)。
        ``duration_sec`` を渡すと elapsed_sec も補完して dashboard の x 軸を
        秒で書ける。
    """
    import requests

    client_id, client_secret, refresh_token = _resolve_oauth_env()
    if not all([client_id, client_secret, refresh_token]):
        raise RuntimeError(
            "YouTube Analytics認証情報が未設定 "
            "(YOUTUBE_OAUTH_CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN)"
        )

    token = _oauth_access_token(client_id, client_secret, refresh_token)

    if not start_date:
        start_date = (date.today() - timedelta(days=30)).isoformat()
    if not end_date:
        end_date = date.today().isoformat()

    resp = requests.get(
        f"{ANALYTICS_API_BASE}/reports",
        params={
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": "elapsedVideoTimeRatio",
            "metrics": "audienceWatchRatio,relativeRetentionPerformance",
            "filters": f"video=={video_id}",
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    rows = data.get("rows") or []
    curve: list[dict] = []
    for row in rows:
        if len(row) < 2:
            continue
        try:
            elapsed_pct = float(row[0])
            ratio = float(row[1] or 0.0)
        except (TypeError, ValueError):
            continue
        point: dict[str, Any] = {"elapsed_pct": elapsed_pct, "ratio": ratio}
        if duration_sec is not None:
            point["elapsed_sec"] = elapsed_pct * float(duration_sec)
        curve.append(point)
    curve.sort(key=lambda p: p["elapsed_pct"])
    return {"curve": curve, "raw_response": data}


def _load_upload_state(state_path: Path | None,
                       file_size: int) -> dict | None:
    """state file が valid (= 24h 以内 + file_size 一致) なら読んで返す。"""
    if state_path is None or not state_path.exists():
        return None
    try:
        with state_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("[youtube] upload_state 読込失敗 (%s): %s",
                       state_path, e)
        return None
    started_at_iso = data.get("started_at")
    if not started_at_iso:
        return None
    try:
        started_at = datetime.fromisoformat(started_at_iso)
    except ValueError:
        return None
    age = (datetime.now(timezone.utc) - started_at).total_seconds()
    if age > UPLOAD_STATE_TTL_SEC:
        logger.info("[youtube] upload_state が %.0fs 経過 → 破棄して新規 upload", age)
        return None
    if data.get("file_size") != file_size:
        logger.info("[youtube] upload_state.file_size mismatch (%s vs %s) → 破棄",
                    data.get("file_size"), file_size)
        return None
    if not data.get("upload_url"):
        return None
    return data


def _save_upload_state(state_path: Path | None, state: dict) -> None:
    if state_path is None:
        return
    state_path.parent.mkdir(parents=True, exist_ok=True)
    io_utils.atomic_write_json(str(state_path), state)


def _clear_upload_state(state_path: Path | None) -> None:
    if state_path is None:
        return
    try:
        state_path.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("[youtube] upload_state 削除失敗 (%s): %s", state_path, e)


def upload_video(
    file_path: Path | str,
    title: str,
    description: str,
    tags: list[str] | None = None,
    privacy: str = "private",
    is_short: bool = True,
    category_id: str = DEFAULT_CATEGORY_ID,
    chunk_size: int = DEFAULT_UPLOAD_CHUNK_SIZE,
    made_for_kids: bool = False,
    state_path: Path | str | None = None,
) -> dict:
    """Resumable upload で YouTube に動画をアップロード、video_id と URL を返す。

    privacy: "private" / "unlisted" / "public"。既定は "private" で安全側。
    is_short: True なら description 末尾に `#Shorts` を自動付加し、Shorts URL を返す。

    Raises:
        RuntimeError: 認証情報不足 / Location ヘッダ欠落 / 異常レスポンス
        requests.HTTPError: HTTP エラー (403 はスコープ不足の可能性)
    """
    import requests

    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"video not found: {file_path}")
    file_size = file_path.stat().st_size
    if file_size <= 0:
        raise ValueError(f"empty file: {file_path}")

    privacy = _resolve_privacy(privacy)

    client_id, client_secret, refresh_token = _resolve_oauth_env()
    if not all([client_id, client_secret, refresh_token]):
        raise RuntimeError(
            "YOUTUBE_OAUTH_CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN が必要 "
            "(upload には youtube.upload スコープ同意済みの token が必要)",
        )

    token = _oauth_access_token(client_id, client_secret, refresh_token)

    if is_short and "#Shorts" not in description:
        description = (description.rstrip() + "\n\n#Shorts").strip()

    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": (tags or [])[:30],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }

    def _do_init(t: str):
        return requests.post(
            f"{UPLOAD_API_BASE}?uploadType=resumable&part=snippet,status",
            json=metadata,
            headers={
                "Authorization": f"Bearer {t}",
                "X-Upload-Content-Length": str(file_size),
                "X-Upload-Content-Type": "video/*",
            },
            timeout=30,
        )

    state_p: Path | None = Path(state_path) if state_path is not None else None
    resumed_state = _load_upload_state(state_p, file_size)

    if resumed_state is not None:
        upload_url = resumed_state["upload_url"]
        logger.info("[youtube] resume 既存 upload (%s, started_at=%s)",
                    file_path.name, resumed_state.get("started_at"))
    else:
        init_resp = _do_init(token)
        if init_resp.status_code in (401, 403):
            logger.info("youtube upload init: %d → access_token 失効と判断して refresh",
                        init_resp.status_code)
            token = _oauth_access_token(client_id, client_secret, refresh_token)
            init_resp = _do_init(token)
        transient_retries = 0
        while 500 <= init_resp.status_code < 600 and transient_retries < 2:
            time.sleep(2 ** transient_retries)
            transient_retries += 1
            logger.warning("youtube upload init 5xx (retry %d/2): %d",
                           transient_retries, init_resp.status_code)
            init_resp = _do_init(token)
        init_resp.raise_for_status()
        upload_url = init_resp.headers.get("Location")
        if not upload_url:
            raise RuntimeError("resumable upload init で Location header が返らなかった")
        if state_p is not None:
            _save_upload_state(state_p, {
                "upload_url": upload_url,
                "file_size": file_size,
                "bytes_uploaded": 0,
                "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "file_path": str(file_path),
            })

    with open(file_path, "rb") as f:
        # resume の場合、サーバーから現在の受領済 offset を問い合わせる
        if resumed_state is not None:
            queried = _query_resumable_offset(upload_url, file_size)
            if queried == "complete":
                # サーバはもう完了している (= 前回 PUT は届いていたが client 側で
                # response を受け取れずに落ちた)。state を消して return 同等の経路
                # に乗せたいが、upload 結果 (video_id) を再取得する経路はないので
                # state を破棄して新規 upload を init し直す
                logger.info("[youtube] resume 試行で server は complete 状態 — state 破棄して再 init")
                _clear_upload_state(state_p)
                # raise すると caller が再実行 (= 新規 init) してくれる
                raise RuntimeError(
                    "previous upload appears complete on server but client lost "
                    "the video_id response; retry will start fresh",
                )
            offset = queried if isinstance(queried, int) else 0
            logger.info("[youtube] resume offset=%d / %d (%.1f%%)",
                        offset, file_size, offset / max(file_size, 1) * 100)
        else:
            offset = 0
        last_response_data: dict = {}
        unknown_range_retries = 0
        max_unknown_range_retries = 5
        while offset < file_size:
            f.seek(offset)
            chunk = f.read(chunk_size)
            if not chunk:
                break
            chunk_end = offset + len(chunk) - 1
            r = requests.put(
                upload_url,
                data=chunk,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{chunk_end}/{file_size}",
                },
                timeout=600,
            )
            if r.status_code in (200, 201):
                try:
                    last_response_data = r.json()
                except Exception:
                    last_response_data = {}
                break
            if r.status_code == 308:
                acked = _parse_range_offset(r.headers)
                if acked is not None:
                    offset = acked
                    unknown_range_retries = 0
                    logger.info(
                        "youtube upload: %d / %d bytes (%.0f%%)",
                        offset, file_size, offset / file_size * 100,
                    )
                    if state_p is not None:
                        _save_upload_state(state_p, {
                            "upload_url": upload_url,
                            "file_size": file_size,
                            "bytes_uploaded": offset,
                            "started_at": (resumed_state or {}).get(
                                "started_at",
                                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            ),
                            "file_path": str(file_path),
                        })
                    continue
                # Range が無い 308 は server がどこまで受領したか不明 →
                # 楽観的に offset を進めると byte gap で upload が壊れる。
                # まず status query (空 PUT + `Content-Range: bytes */<size>`)
                # で受領済み offset を取り直す。
                queried = _query_resumable_offset(upload_url, file_size)
                if queried == "complete":
                    last_response_data = {}
                    offset = file_size
                    break
                if isinstance(queried, dict):
                    last_response_data = queried
                    offset = file_size
                    break
                if isinstance(queried, int):
                    offset = queried
                    unknown_range_retries = 0
                    continue
                # status query でも Range 無し → 同じ offset で retry
                unknown_range_retries += 1
                if unknown_range_retries > max_unknown_range_retries:
                    raise RuntimeError(
                        f"308 from server without Range info "
                        f"(retries={unknown_range_retries}, offset={offset}); "
                        "upload aborted to avoid byte gap",
                    )
                logger.warning(
                    "youtube upload: 308 without Range (retry %d/%d, offset=%d)",
                    unknown_range_retries, max_unknown_range_retries, offset,
                )
                continue
            r.raise_for_status()
            raise RuntimeError(
                f"upload PUT 想定外の status: {r.status_code} {r.text[:300]}",
            )

    video_id = last_response_data.get("id")
    if not video_id:
        raise RuntimeError(
            f"upload 完了後に video_id が取得できませんでした: {last_response_data}",
        )
    url = (f"https://youtube.com/shorts/{video_id}" if is_short
           else f"https://youtu.be/{video_id}")
    _clear_upload_state(state_p)
    return {
        "video_id": video_id,
        "url": url,
        "raw_response": last_response_data,
    }


def _parse_range_offset(headers) -> int | None:
    """`Range: bytes=0-N` から次に送るべき offset (= N+1) を返す。

    ヘッダ欠落 / フォーマット不正は None。"""
    rh = headers.get("Range") or headers.get("range")
    if not rh:
        return None
    if "-" not in rh:
        return None
    try:
        end = int(rh.rsplit("-", 1)[-1].strip())
    except ValueError:
        return None
    if end < 0:
        return None
    return end + 1


def _query_resumable_offset(upload_url: str, file_size: int):
    """空 PUT で受領済み offset を server に問い合わせる。

    Returns:
      - int: server が受領済みの byte 数 (= 次の offset)
      - "complete": 200/201 で完了応答 (= 既にアップロード済み)
      - dict: 200/201 のレスポンス本文 (= video resource)
      - None: 308 だが Range 無し (= server もまだわからない)
    """
    import requests
    try:
        r = requests.put(
            upload_url, data=b"",
            headers={
                "Content-Length": "0",
                "Content-Range": f"bytes */{file_size}",
            },
            timeout=60,
        )
    except requests.RequestException as e:
        logger.warning("status query 失敗: %s", e)
        return None
    if r.status_code in (200, 201):
        try:
            data = r.json()
            if data:
                return data
        except ValueError as e:
            logger.warning("[youtube] status JSON parse 失敗: %s", e)
        return "complete"
    if r.status_code == 308:
        return _parse_range_offset(r.headers)
    logger.warning(
        "status query: unexpected status %d (%s)",
        r.status_code, r.text[:200],
    )
    return None


def fetch_metrics_for_post(post: dict) -> dict:
    """db から取った 1 post dict に対して metrics を取得する。

    schema v10 で追加された traffic source / retention curve も合流する:
    - traffic_*_pct → 直接 result に積み、insert_metrics が post_metrics へ書き込む
    - retention curve → underscore prefix キー ``_retention_curve`` で渡し、
      caller (= fetch_metrics.py) が post_retention_curves へ別経路で persist する
    """
    video_id = post["platform_post_id"]
    result: dict = {}

    try:
        analytics = fetch_analytics(video_id)
        result.update({k: v for k, v in analytics.items() if v is not None})
    except Exception as e:
        logger.info("YouTube Analytics 取得スキップ (%s): %s", video_id, e)

    try:
        public = fetch_public_stats(video_id)
        for k, v in public.items():
            if k not in result or result.get(k) in (None, 0):
                result[k] = v
    except Exception as e:
        logger.warning("YouTube public stats 取得失敗 (%s): %s", video_id, e)

    try:
        traffic = fetch_traffic_sources(video_id)
        for k, v in traffic.items():
            if k == "raw_response" or v is None:
                continue
            result[k] = v
    except Exception as e:
        logger.info("YouTube traffic source 取得スキップ (%s): %s", video_id, e)

    duration_sec = result.get("duration_sec") or post.get("video_duration_sec")
    try:
        retention = fetch_retention_curve(video_id, duration_sec=duration_sec)
        if retention.get("curve"):
            result["_retention_curve"] = retention["curve"]
    except Exception as e:
        logger.info("YouTube retention curve 取得スキップ (%s): %s", video_id, e)

    return result
