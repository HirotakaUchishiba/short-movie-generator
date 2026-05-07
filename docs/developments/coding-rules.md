# コーディング規約

本ドキュメントは tensyoku_movie_generator の Python / TypeScript コードと付随するドキュメントの記述ルールを集約する。CLAUDE.md からの切り出し + 補強。

新たなルールを増やすときはここに追記し、末尾の最終更新日を更新する。

---

## 1. 全般原則

| 原則                             | 補足                                                                                         |
| -------------------------------- | -------------------------------------------------------------------------------------------- |
| 要求された変更だけを行う         | 周辺リファクタや「ついでに」は別 PR に分ける                                                 |
| 既存スタイルに揃える             | 同ファイル / 同モジュールの書き方を尊重する。一人だけ違う書き方をしない                      |
| import 文の整理を勝手にしない    | 本質変更と関係ない import の並び替えは PR を汚すので原則禁止 (= ruff の auto-fix 適用時のみ) |
| 仮想要件のために抽象を導入しない | 「将来必要になりそう」で 3 派生クラスを先回りで作らない。実需が出てから refactor             |
| 後方互換のためのシムを残さない   | 廃止した関数・引数の残骸 (`_unused`, `// removed`, 旧名リエクスポート) を放置しない          |

---

## 2. ログ

`logging` モジュール経由で出力する。`print()` は禁止 (= scripts/ 内の CLI 補助でも極力使わない。`logger.info` で代替する)。

```python
import logging
logger = logging.getLogger(__name__)

def run_stage(...):
    logger.info("stage 4 (kling) start ts=%s scene=%s", ts, scene_idx)
    try:
        ...
    except FalClientError:
        logger.exception("kling failed for scene=%s", scene_idx)
        raise
```

| ルール                                    | 理由                                                                             |
| ----------------------------------------- | -------------------------------------------------------------------------------- |
| `logger = logging.getLogger(__name__)`    | フィルタ・level 制御をモジュール単位で効かせる                                   |
| 例外時は `logger.exception(...)`          | stack trace を自動付加する                                                       |
| f-string は使わず `%s` placeholder        | log level が DEBUG 以下のときに format コストを払わない                          |
| 機密情報を log に出さない                 | API key / OAuth token / refresh token / 個人情報を `logger.debug` 含めて出さない |
| 進行ログは原則 `INFO`、内部状態は `DEBUG` | `LOG_LEVEL=DEBUG` で詳細が出る運用                                               |
| 失敗ログは黙って握り潰さない              | `try / except / pass` で握るのは禁止。最低でも `logger.warning` を残す           |

---

## 3. エラーハンドリング

| ルール                                               | 例                                                                                            |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| 同一パターンの関数群はエラーハンドリングを統一       | 全 stage 関数で「外部 API 失敗 → ログ + 例外 raise」「I/O 失敗 → preflight で先に検知」       |
| 外部データのパースは防御的に                         | `int(value)` / `float(value)` / JSON フィールドアクセス / 配列インデックスは事前検証 or `try` |
| 想定外の状態は早期に raise                           | `if not allowed_value: raise ValueError(...)` で fail-fast                                    |
| 例外は具体的な型を catch                             | `except Exception:` ではなく `except FalClientError:` のように原因を絞る                      |
| エラーメッセージはコンテキストを含める               | `f"failed to load screenplay {path}: {reason}"` のように特定可能な識別子を含める              |
| 復旧不能なエラーは `RuntimeError` / 専用例外で raise | 「retry しても無理」と判明している場合は黙って continue しない                                |

ドメイン専用例外は各モジュールが定義 (例: `FalClientError`, `LipsyncClientError`, `ValidationError`)。新規例外を増やすときは既存 hierarchy に揃える。

---

## 4. 命名規則

### 4.1 Python

| 種別             | 規則                                    | 例                                          |
| ---------------- | --------------------------------------- | ------------------------------------------- |
| モジュール       | snake_case                              | `scene_gen.py`, `final_import/core.py`      |
| 関数 / メソッド  | snake_case                              | `compose_screenplay`, `run_tts_stage`       |
| クラス           | PascalCase                              | `Screenplay`, `LipsyncClient`               |
| 定数             | UPPER_SNAKE_CASE                        | `EMOTION_AUDIO_TAGS`, `DEFAULT_LOCATION`    |
| プライベート     | 先頭 `_`                                | `_resolve_speaker_to_ref`                   |
| Boolean          | `is_*` / `has_*` / `can_*` / `should_*` | `is_canonical`, `has_audio`, `should_retry` |
| 型変数 / Generic | PascalCase + 短く                       | `T`, `Item`                                 |

### 4.2 TypeScript / React (frontend)

| 種別           | 規則                     | 例                                                        |
| -------------- | ------------------------ | --------------------------------------------------------- |
| ファイル       | kebab-case か PascalCase | `stage-overlay.tsx` / `StageOverlay.tsx` (どちらかで統一) |
| コンポーネント | PascalCase               | `StageOverlay`                                            |
| 関数 / 変数    | camelCase                | `loadProject`, `selectedStage`                            |
| 定数           | UPPER_SNAKE_CASE         | `DEFAULT_PRIVACY`                                         |

### 4.3 ドメイン用語

ドメイン語彙 (= screenplay / scene / line / canonical / lipsync 等) は **`docs/developments/ubiquitous-language.md` の表と同じ表記** を必ず使う。コードで `cap` と書いて文書で `caption` と書く、のような不一致は避ける。

---

## 5. 禁止パターン

| パターン                                     | 代替                                                                              |
| -------------------------------------------- | --------------------------------------------------------------------------------- |
| マジックナンバー                             | 定数化 + 名前で意味を表す (`FINGERPRINT_THRESHOLD = 0.6`)                         |
| 3 層以上の `if` / `for` ネスト               | 早期 return / 関数抽出                                                            |
| 関数 50 行超                                 | 分割検討。やむを得ない場合はコメントで「なぜ分割しないか」を 1 行残す             |
| `# TODO:` / `# FIXME:` 単独                  | 必ず理由 + (任意で issue 番号 or 期限) を付ける: `# TODO: ratelimit 対策後に削除` |
| `except Exception:` で握りつぶし             | 具体型に絞る or 再 raise する                                                     |
| `print()` で進捗表示                         | `logger.info`                                                                     |
| 廃止コードの `// removed` / `# removed` 残置 | 直接消す                                                                          |
| 不要な `_unused_arg` リネーム                | 引数自体を消す。残す場合は `*` で区切る or 注釈                                   |

---

## 6. コメント / docstring

| 原則                                  | 補足                                                                                               |
| ------------------------------------- | -------------------------------------------------------------------------------------------------- |
| 既定はコメントを書かない              | 名前で意味が伝われば十分                                                                           |
| 書くのは **WHY が非自明な時だけ**     | 「なぜこうしたか」「外部の制約」「過去のバグ回避」「微妙な不変条件」                               |
| WHAT を書かない                       | コード自体を読めばわかることを冗長に書かない                                                       |
| 現タスク・PR・著者の名前は書かない    | `# 2026-05-07 Hirotaka added` のようなものは git blame で十分                                      |
| docstring は最大 1 行                 | 多段落の説明は別途 docs/ に書く。コード内に長文を埋めない                                          |
| 注意点が長くなるなら docs/ に切り出す | コード内に 5 行超の注釈が必要なら、`docs/developments/<topic>.md` に書いて `# see docs/...` で参照 |

---

## 7. 設計書とコード

| 原則                                                 | 意味                                                                                     |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| 設計書はコードを書きすぎない                         | 「どういう関数を作るか」よりも **WHY / WHAT / HOW** を書く。具象 API 仕様は別で良い      |
| ドキュメントは進捗を ordered list / checkbox で残す  | フロー文書 (`docs/plannings/*.md`) は checkbox で進捗管理。完了ものは打ち消さず `[x]` 化 |
| 1 PR = 1 ドキュメントの粒度                          | 大改訂を 1 PR に積まない                                                                 |
| 静的文書は `docs/developments/*.md` に置く           | アーキテクチャ / コーディング規約 / 用語集等                                             |
| フロー文書は `docs/plannings/YYYY-MM-DD_*.md` に置く | 計画 / 実装記録 / 監査結果。日付 prefix で時系列を保持                                   |

---

## 8. import / 依存関係

- ファイルの先頭に集約。関数内 import は遅延ロードが必要なときだけ
- ruff (`ruff format` + `ruff check`) を信頼する。手で並び替えない
- 外部依存を増やすときは `requirements.txt` を更新 + 1 行コメントで用途を明記 (例: `librosa  # final_import の音声指紋検証で使用`)
- 循環 import は避ける。`docs/developments/architecture.md` のレイヤと依存方向に従う

---

## 9. 機密情報

| ルール                                                                           | 例                                              |
| -------------------------------------------------------------------------------- | ----------------------------------------------- |
| API key / OAuth token / refresh token はコード / log / コミットに含めない        | `.env` 経由で読み込み、log には絶対出さない     |
| `.env` を git に commit しない                                                   | `.gitignore` に登録済みであることを確認         |
| ステージングと本番で同じ token を使わない                                        | (Phase 4 で本番運用に入る時に env を分ける想定) |
| 機密の更新が必要な場合は `docs/developments/publishing.md` (= 将来作成) に手順化 | YouTube refresh token のローテーション等        |

---

## 10. 一時ファイル

- 一時ファイルは **リポジトリ内 `temp/` または `tests/tmp_path` 配下** に置き、`/tmp` (= OS の global tmp) を使わない
- `temp/<TS>/tmp/` は本番パイプラインの中間アーティファクト用なので、テストや開発用には使わない
- テストでは `pytest` の `tmp_path` fixture を使う

---

## 11. ドキュメント命名

| 種別                | パス                                   | 例                                                   |
| ------------------- | -------------------------------------- | ---------------------------------------------------- |
| 静的 (規約・設計)   | `docs/developments/<topic>.md`         | `architecture.md` / `testing.md` / `coding-rules.md` |
| フロー (計画・記録) | `docs/plannings/YYYY-MM-DD_<topic>.md` | `2026-05-07_full-automation-feasibility.md`          |
| ドメイン強制ルール  | `CLAUDE.md` (root)                     | プロジェクト全体の前提・段階的ゲート方式の説明等     |
| ユーザー global     | `~/.claude/CLAUDE.md`                  | 個人の既定ルール (応答言語等)                        |

---

## 12. レビュー時の自己チェック

PR を出す前 (or merge 前) に最低限自分で確認:

- [ ] 命名 / log / エラー処理が §2-§5 に沿っているか
- [ ] 該当の docs/ を更新したか (アーキ変更なら `architecture.md`、新用語なら `ubiquitous-language.md`)
- [ ] テストの観点 3 セット (`docs/developments/testing.md` §3) を埋めたか
- [ ] 不要な `print` / TODO / コメント / 廃止コードを残していないか
- [ ] 機密情報を log や fixture に書いていないか
- [ ] 関数 50 行超 / ネスト 3 層超のものを意図的に許容したか (= 理由をコメントで)

---

最終更新: 2026-05-07
