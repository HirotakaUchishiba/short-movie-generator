# analytics_pending queue 撤去 + publish 側保証の現状追認

| 項目       | 値                                                                                                                                  |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| 作成       | 2026-05-10                                                                                                                          |
| ステータス | proposal & implementation (= 本 PR で全 phase 実施)                                                                                 |
| 関連       | `analytics/db.py`, `final_import/publish.py`, `routes/analytics.py`, `preview_server.py`, `frontend/src/components/ProjectList.tsx` |
| スコープ   | pending queue 機構の完全撤去 + publish() の失敗時挙動の整理。analytics_db schema / fetch_metrics / dashboard は触らない             |

---

## 1. 問題定義

### 1.1 観測された負債

`data/analytics_pending.jsonl` に「**削除済みプロジェクトの publish 試行**」が永遠に残り続ける現象を観測した:

- `truncate` で 0 byte にしても、preview_server 起動時の auto-replay や UI の「今すぐ同期」ボタンが走ると、メモリに保持された (= ファイル truncate 直後に新しい publish 試行があった場合) 失敗 entry が `rewrite()` でファイルに書き戻される
- 該当 entry は対応する `videos` 行が DB に無いので `register_post()` が FOREIGN KEY 違反で永久に失敗
- UI に「analytics 同期保留 N 件」が常時露出して運用者の心理的負担を生む

### 1.2 機構の本来目的

pending queue は「**publish (= YouTube/IG/TikTok アップロード) は成功したが、analytics DB への登録が失敗した**」という split-brain (= 動画は世界に出たのに DB に記録なし) を後追いで埋める救済として導入された:

```
[A] YouTube アップロード成功 (= 動画は公開済み)
[B] analytics DB に posts INSERT 試行
   ├─ 成功 → 完了
   └─ 3 回失敗 → analytics_pending.jsonl に append (= 「後で同期する」を意味)
```

[A] が成功したのに [B] で失敗するケースを想定:

| シナリオ                              | 既存防御                                                                               |
| ------------------------------------- | -------------------------------------------------------------------------------------- |
| **1. SQLite ロック (= 並行 write)**   | `analytics/db.py:35` で `PRAGMA journal_mode=WAL` 有効化済み                           |
| **2. SQLite busy timeout**            | `analytics/db.py:36` で `PRAGMA busy_timeout=5000` (= 5 秒内蔵 retry) 済み             |
| **3. video 行が DB に無い (FK 違反)** | `final_import/publish.py:311-361` の `_ensure_video_in_analytics()` で先行 upsert 済み |
| **4. fsync 起因の遅延**               | `analytics/db.py:37` で `PRAGMA synchronous=NORMAL` 済み                               |
| **5. 外部キー無効化バグ**             | `analytics/db.py:34` で `PRAGMA foreign_keys=ON` 強制                                  |

つまり **想定された split-brain シナリオは既に publish 側の防御で潰されている**。

### 1.3 残された失敗モード (= 極めてまれ)

- disk full / permission (= preflight 不在、運用者が気付くべきレベル)
- SQLite 内部エラー (= ライブラリ bug、実観測なし)
- 操作ミス (= 重複 publish → UNIQUE 制約違反、`scripts/register_post.py` で resolvable)

これらは **頻度が極めて低い** (= 個人運用 MVP で年に 0 〜 数回)。常設機構 (= pending queue + UI バッジ + 起動時 auto-replay + 関連テスト) を維持するコストに見合わない。

---

## 2. 設計方針

### 2.1 主張

**pending queue を完全撤去し、DB 登録失敗は loud error log + 手動復旧 (= `register_post.py`) で対処する運用に振る。**

publish() の挙動は以下に整理する:

| publish アクション       | DB 登録  | publish() の return | Stage 8 mark_generated | UI 通知                        |
| ------------------------ | -------- | ------------------- | ---------------------- | ------------------------------ |
| YouTube アップロード成功 | 成功     | success             | ✅ 即時                | (通常通り)                     |
| YouTube アップロード成功 | 失敗     | success + warning   | ✅ 即時                | warning フィールドを表示 + log |
| YouTube アップロード失敗 | 試行なし | fail                | ❌                     | error 表示                     |

**重要**: YouTube アップロード成功後に DB 登録だけ失敗した場合でも publish() は **success return** + Stage 8 mark_generated する。理由:

- アップロード済みの動画は世界に出ているので、UI で「失敗」表示してユーザーが再 publish すると **YouTube に重複動画** が出る (= split-brain よりも致命的)
- DB 登録失敗は operational error として扱い、警告 log + 手動復旧で吸収する

### 2.2 retry 戦略の簡略化

`_record_analytics_with_retry` の 3 回 backoff retry (= 1+2+4=7 秒) を撤去 → 1 回 INSERT に簡略化。理由:

- SQLite `busy_timeout=5000` が **内蔵 retry として既に効いている** (= ロック検出時 5 秒待ち)
- アプリケーションレベルの追加 retry は冗長
- 失敗時の error log + 手動復旧フローを明確化

---

## 3. アーキテクチャ詳細

### 3.1 削除対象

| 対象                                                                         | 理由                                                              |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `analytics/pending_queue.py`                                                 | queue 自体を撤去                                                  |
| `scripts/sync_pending_analytics.py`                                          | queue replay の手動実行スクリプト                                 |
| `routes/analytics.py` の `/api/analytics/pending` (GET)                      | 件数 / 状態取得 endpoint                                          |
| `routes/analytics.py` の `/api/analytics/pending/sync` (POST)                | 「今すぐ同期」ボタン用 endpoint                                   |
| `preview_server.py:1580-1614` の `_replay_pending_analytics()`               | 起動時 auto-replay                                                |
| `final_import/publish.py:546-573` の `finalize_pending_publish()`            | published_posts.analytics_pending flag を flip + Stage 8 昇格     |
| `final_import/publish.py:254-308` の `_record_analytics_with_retry`          | retry + queue 落ちロジック (= 簡略版で置換)                       |
| `frontend/src/components/ProjectList.tsx:234-287` の `PendingAnalyticsBadge` | 30 秒ポーリング + バッジ + 同期ボタン UI                          |
| `frontend/src/api.ts` の `analyticsPendingStatus` / `analyticsPendingSync`   | 関連 API client メソッド                                          |
| `data/analytics_pending.jsonl`                                               | 既存ファイル (= 削除済みプロジェクトの残骸のみ含むことを確認済み) |
| `.gitignore` の `data/analytics_pending.jsonl` 行                            | 不要に                                                            |

### 3.2 置換: `_record_analytics_with_retry` → `_record_analytics`

```python
# Before (= 簡略化対象)
def _record_analytics_with_retry(...) -> bool:
    for attempt in range(ANALYTICS_RETRY_ATTEMPTS):
        try:
            init_db()
            _ensure_video_in_analytics(ts_path)
            register_post(...)
            return True  # 成功
        except Exception:
            if attempt < ANALYTICS_RETRY_ATTEMPTS - 1:
                time.sleep(BACKOFF[attempt])
                continue
            pending_queue.append({...})  # 全失敗 → queue
            return False

# After (= 簡略版)
def _record_analytics(...) -> dict[str, Any]:
    """analytics DB に記録する。失敗時は warning を返すが publish 自体は止めない。"""
    try:
        init_db()
        _ensure_video_in_analytics(ts_path)
        register_post(...)
        return {"persisted": True}
    except Exception as e:
        logger.error(
            "[analytics] DB 登録失敗 — publish 自体は成功しています。"
            " scripts/register_post.py で手動復旧してください: %s",
            e,
            exc_info=True,
        )
        return {"persisted": False, "error": str(e)}
```

呼び出し側 (`_publish_youtube` / `_publish_instagram_api`) は戻り値の `persisted` を `analytics_persisted` フィールドとして上に伝えるだけ。

### 3.3 `_record_publish` の簡略化

`published_posts[].analytics_pending` フラグと「Stage 8 mark_generated 保留」ロジックを削除。Stage 8 は publish アップロード成功で **即時 mark_generated**。

```python
# Before
mark_generated_pending = not analytics_persisted
# After
# (= 即時 mark_generated、analytics_persisted は警告フィールドとして残す)
```

`published_posts[]` のスキーマは:

```json
{
  "platform": "youtube",
  "platform_post_id": "...",
  "url": "...",
  "posted_at": "...",
  "analytics_persisted": true // 後方互換のため残す。false なら手動復旧待ち
}
```

`analytics_pending` キー (= 既存 entry に残っているもの) は読み取り側で **無視** する (= 後方互換)。

---

## 4. 実装プラン

| Phase | 内容                                                                                                                                                                                      | 依存 |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| **A** | 設計 doc (= 本ファイル)                                                                                                                                                                   | -    |
| **B** | backend: `publish.py` 簡略化 (= `_record_analytics` 化、`finalize_pending_publish` 削除、保留ロジック削除)                                                                                | A    |
| **C** | backend: `pending_queue.py` / `scripts/sync_pending_analytics.py` / `routes/analytics.py` 該当 endpoint / `preview_server.py` auto-replay 削除                                            | B    |
| **D** | frontend: `PendingAnalyticsBadge` + `api.ts` 関連メソッド削除                                                                                                                             | C    |
| **E** | tests: `test_sync_pending_analytics.py` / `test_preview_server_pending_analytics.py` / `test_publish_flow.py:583-677` 削除 + 新規 (= DB 失敗時の publish() success return + warning) 追加 | B, C |
| **F** | docs: `CLAUDE.md` 等から関連記述削除 + 復旧手順追記                                                                                                                                       | -    |
| **G** | `data/analytics_pending.jsonl` 削除 + `.gitignore` から行削除                                                                                                                             | C    |

A〜G を **1 PR** にまとめる (= 段階的に分けると中間状態でテストが壊れる)。commit は logical な区切り (= 設計 doc / 実装 / docs / data) で複数に分割する。

---

## 5. リスクと未解決事項

### 5.1 既存 `published_posts[]` entries の `analytics_pending` フィールド

- 現存 publish 済みプロジェクトの `metadata.json` に `analytics_pending: true` が残っている可能性
- **対処**: 読み取り側で無視 (= 後方互換)。新規 publish からは書き込まれない
- 移行スクリプトは作らない (= 個人運用なのでデータ量が少ない)

### 5.2 既存 `data/analytics_pending.jsonl` の中身

- 観測済み: 削除済みプロジェクト (`ts: 20260506_160000`) の retry 残骸 1 件のみ
- 削除して問題なし (= 紐付く `videos` / `posts` 行が既に DB に存在しない)

### 5.3 失敗時の error log を見落とすリスク

- DB 登録失敗が「publish() success return」で隠れる懸念
- **対策**:
  - log level = `error` (= warning ではなく) で必ず可視化
  - error message に復旧手順 (= `scripts/register_post.py <video_id> <platform> <URL>`) を含める
  - `CLAUDE.md` のトラブルシューティング章に「analytics 登録失敗時の復旧」を追記

### 5.4 重複 publish 防止

- 撤去対象外: 既存の重複 publish 防止ロジック (= published_posts に同じ platform_post_id があるかチェック) は維持
- DB UNIQUE 制約 (= `posts.platform_post_id`) も維持

---

## 6. スコープ外

- `analytics/db.py` の schema 変更 (= v11 維持)
- `fetch_metrics.py` / `dashboard.py` の変更 (= pending queue とは独立)
- `architecture-decisions.md` の cost_tracking 仕様 (= 触らない)
- 過去 entry の analytics 自動補完 (= ユーザーが個別に register_post.py で対応)

---

## 7. 受け入れ基準

1. `data/analytics_pending.jsonl` が存在しない (= 削除済み)
2. `pending_queue.py` / `sync_pending_analytics.py` が存在しない
3. `/api/analytics/pending*` の HTTP 応答が 404
4. preview_server 起動 log に `[analytics-replay]` が出ない (= auto-replay 削除済み)
5. UI ヘッダーに「analytics 同期保留 N 件」バッジが表示されない
6. publish() の DB 登録失敗テストで:
   - publish() return = `{"analytics_persisted": false, "warning": "..."}`
   - Stage 8 が即時 `mark_generated` になっている
   - error log に復旧手順が含まれている
7. 既存 publish 済みプロジェクトの `metadata.json.published_posts[]` に `analytics_pending` フィールドが残っていても起動 / UI 表示が壊れない
8. `pytest` 全体が green

---

## 8. 関連

- `analytics/db.py:28-46` (= 既存 PRAGMA 設定、本 refactor で維持)
- `final_import/publish.py:254-308` (= `_record_analytics_with_retry` 削除対象)
- `final_import/publish.py:311-361` (= `_ensure_video_in_analytics` 維持)
- `final_import/publish.py:546-573` (= `finalize_pending_publish` 削除対象)
- `routes/analytics.py:18-59` (= 該当 endpoint 削除対象)
- `preview_server.py:1580-1614` (= auto-replay 削除対象)
- `frontend/src/components/ProjectList.tsx:234-287` (= UI 削除対象)
- `tests/test_publish_flow.py:583-677` (= queue 系テスト削除対象、新規テスト追加)
