# リファクタリングチェックリスト

## 基本的な問題検出

### 重複処理

- [ ] 同じロジックが複数箇所に存在しないか
- [ ] コピペされたコードブロック
- [ ] 類似した関数・コンポーネント (= プロバイダ別 lipsync ハンドラ等)

### 未使用コード

- [ ] import されていないモジュール
- [ ] 呼び出されていない関数
- [ ] 使用されていない変数・定数
- [ ] 廃止された後方互換シム (`# removed` / `_unused_*`)

### 不適切な export

- [ ] 内部でのみ使用される関数が外部に公開されている
- [ ] `from x import *` の使用 (= 名前付き import に変換)

### 複雑性

- [ ] 過度に長い関数 (50 行以上、`docs/developments/coding-rules.md` §5)
- [ ] 深いネスト (3 層以上)
- [ ] 複雑な条件分岐

### 責務分離

- [ ] 1 つのファイルに複数の責務
- [ ] UI とビジネスロジックの混在 (= `preview_server.py` のエンドポイントにロジックが直接書かれている等)
- [ ] パイプライン Stage 関数に外部 API 呼び出しが直接埋め込まれている (= DI 化推奨)

## ガイドライン違反

### Python 固有ルール (`docs/developments/coding-rules.md`)

- [ ] `print()` の使用 (= `logger.info` に置換)
- [ ] `logging.info()` を直接呼んでいる (= `logger = logging.getLogger(__name__)` を経由)
- [ ] `except Exception: pass` / `except: pass` の silent swallow
- [ ] f-string のログ呼び出し (= `%s` placeholder に置換、debug level で format コストを払わない)
- [ ] 命名規則違反 (= snake*case 関数 / UPPER_SNAKE_CASE 定数 / Boolean は `is*/has*/can*/should\_`)
- [ ] マジックナンバー (= timeout / threshold / size を `config.py` に集約していない)
- [ ] mutable default 引数 (`def f(xs=[])`) — list / dict / set はデフォルトで `None` から始める
- [ ] `Any` 型の濫用 / `cast` での強制変換

### 外部入力の防御

- [ ] Flask endpoint の `int(args.get(...))` / `json.loads(text)` が try-guard 無しで例外を出す
- [ ] 環境変数のパース (= `int(os.environ.get(...))`) がガード無し
- [ ] subprocess 呼び出しに `timeout` 引数が無い
- [ ] 外部 API レスポンス (= Claude / Imagen / Kling 等) のキー存在チェック無し

### 一時ファイル / project state

- [ ] `temp/<TS>/` の中間ファイルを stage 失敗時に cleanup していない
- [ ] `os.path.exists` だけで skip 判定していて `artifact_integrity` を通っていない
- [ ] `staged_pipeline` (オーケストレータ層) を生成・編集層から直接 import している (= `project_state.py` 経由が筋)

## パフォーマンス問題

### Python 関連

- [ ] 巨大ファイルを `with open(...).read()` で全部読み込んでいる
- [ ] 同じ subprocess を複数回呼んでいる (= ffprobe の duration を各 stage で再取得など)
- [ ] `concurrent.futures.ThreadPoolExecutor` で外部 API 並列度を制御していない

### React 関連 (frontend)

- [ ] 不要な再レンダリングの原因
- [ ] `useMemo` / `useCallback` が必要な箇所
- [ ] 重いコンポーネントのメモ化不足

### バンドルサイズ (frontend)

- [ ] 大きすぎるモジュール
- [ ] 動的 import が適切でない箇所
- [ ] 未使用の依存関係

## アーキテクチャ問題

### レイヤー分離 (`docs/developments/architecture.md` §2)

- [ ] エントリ層 (CLI / HTTP) にドメインロジックが混在
- [ ] 外部 API クライアント層が上層 (オーケストレータ) を import
- [ ] `analyze/` と `analytics/` が orthogonal を破っている
- [ ] 循環 import

### データフロー

- [ ] 複雑な props drilling (frontend)
- [ ] 不適切な state 管理
- [ ] 非同期処理の問題 (= `threading.Lock` 取得忘れ、`watchdog` の race condition)

## セキュリティ・品質

### セキュリティ

- [ ] XSS 脆弱性の可能性 (= `preview_server` の HTML レスポンス)
- [ ] SQL インジェクションのリスク (= `analytics.db.py` の生 SQL)
- [ ] 機密情報のハードコード (= API key / OAuth token)
- [ ] log への機密情報の流出

### エラーハンドリング (`docs/developments/coding-rules.md` §3)

- [ ] try / catch の欠落
- [ ] エラーの握りつぶし (= silent swallow)
- [ ] 不適切なエラーメッセージ (= 識別子を含まない)
- [ ] 同一パターン関数群でのエラーハンドリング不統一 (= 全 stage 関数で「外部 API 失敗 → ログ + 例外 raise」が揃っていない)

## ファイル構成

### サイズ

- [ ] 500 行を超えるファイル
- [ ] 1000 行を超えるファイル (= 要分割)

### 命名

- [ ] 命名規則の不統一
- [ ] 意味不明な変数名
- [ ] 略語の多用
- [ ] ドメイン用語のドリフト (= `docs/developments/ubiquitous-language.md` から逸脱: `cap` vs `caption` 等)

## short_movie_generator 固有の観点

### 8-stage パイプライン

- [ ] Stage 番号表記が混在 (= 旧 9-stage 表記の残骸)
- [ ] `progress_store.py` のゲート条件をバイパスする抜け道が新設されていないか
- [ ] `temp/<TS>/tmp-progress.json` への直接書き込み (= `progress_store` 経由が筋)

### コスト追跡

- [ ] 新規 stage / API 呼び出しで `cost_recorder.record_*` が漏れていないか
- [ ] `data/cost_records.jsonl` を本番から汚染するテスト (= `_isolate_cost_records` autouse fixture を信頼)

### template / snapshot 分離

- [ ] `screenplays/<name>.json` (= template) と `temp/<TS>/screenplay.json` (= snapshot) を混同していないか
- [ ] Stage 1〜6 で template を直接書き換えてしまっていないか
