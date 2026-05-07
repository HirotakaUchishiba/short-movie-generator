# テスト戦略

本ドキュメントは tensyoku_movie_generator のテスト方針・観点・ファイル配置・命名・モック・カバレッジ目標を 1 ページに集約する。実装スタックは pytest 8.x。

---

## 1. 戦略の基本

| 原則                                      | 意味                                                                                              |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------- |
| **外部 API は呼ばない**                   | ElevenLabs / Imagen / Kling / Sync.so / YouTube は monkeypatch で必ず差し替える                   |
| **ファイルシステムは tmp_path 経由**      | 本番の `data/` / `temp/` / `output/` を絶対に汚さない                                             |
| **観点 3 セットを必ず通る**               | 正常系 / バリデーション / エラーハンドリング (= §3)                                               |
| **テスト命名は対象ファイルとの 1:1 対応** | `scene_gen.py` の試験は `tests/test_scene_gen_*.py` (機能でファイル分割可)                        |
| **autouse fixture を信頼する**            | `conftest.py` で本番パスから自動隔離されるので、個別テストでは再宣言不要                          |
| **flaky なテストを書かない**              | 時刻・乱数・スレッド競合に依存する場合は `freezegun` / シード固定 / 同期化で必ず deterministic に |

---

## 2. ディレクトリ構成と命名

```
tests/
  conftest.py                   ← autouse fixture 集約 (§5)
  test_<module>.py              ← 1 module = 1 ファイル基本
  test_<module>_<aspect>.py     ← 機能で分割 (例: test_scene_gen_lipsync.py)
  test_preview_server_<api>.py  ← API 単位で分割 (preview_server は大きいので)
  factories/                    ← (新設推奨) ドメインオブジェクトの生成ヘルパー
    screenplay.py / scene.py / line.py / project.py
  fixtures/                     ← (新設推奨) 外部 API のレスポンス JSON
    elevenlabs/ / imagen/ / kling/ / syncso/ / youtube/
```

### 命名規則

- ファイル名: `test_<対象 module>[_<aspect>].py`
- 関数名: `test_<対象>_<状況>_<期待結果>` のように **状況と期待結果を含める**

```python
def test_scene_gen_kling_部分失敗時_該当シーンのみ再試行する():
    ...

def test_screenplay_validator_text_に_ascii_カンマがある場合_reject():
    ...
```

英語名でも構わないが、**ドメイン語彙は日本語のまま** にして良い (= ubiquitous-language.md と一貫させる)。docstring 1 行で意図を補うのは推奨。

---

## 3. テスト観点 3 セット

新規実装 / 修正に対しては **必ずこの 3 観点をカバーする**:

### 3.1 正常系 (happy path)

代表的な入力で**期待通りの出力を得る**ことを確認。1 シナリオで十分。

```python
def test_compose_screenplay_標準入力_完全台本を返す():
    abstract = make_abstract_screenplay(scenes=[...])
    result = compose_screenplay(abstract, speaker_to_ref={"speaker_1": "f1__office"})
    assert result.scenes[0].character_refs == ["f1__office"]
```

### 3.2 バリデーション (= 不正な入力への対処)

ドメインルール違反を**ちゃんと reject する**ことを確認。

- screenplay: ASCII `,` `.` を含む text → reject
- subtitles[]: start のみ指定 / end のみ指定 → reject
- 解決済み ref: 存在しない wardrobe → reject
- license_status が `"unconfirmed"` の reference → analyze に進めない (Phase 1+)

```python
def test_screenplay_validator_subtitles_の_片方時刻指定_は_reject():
    sp = make_screenplay(lines=[make_line(subtitles=[{"text": "a", "start": 0.0}])])
    with pytest.raises(ValidationError, match="both start and end"):
        validate(sp)
```

### 3.3 エラーハンドリング (= 外部要因での失敗)

外部 API の失敗・I/O エラー・タイムアウトに対して**期待した形で振る舞う**ことを確認。

- ElevenLabs API timeout → 適切な例外を raise する
- Kling 429 → 5 回 backoff 後に最終失敗 (`fal_video_client`)
- Sync.so 20MB 超過 → `LipsyncClientError` で fallback chain
- ディスク不足 → `preflight` で停止

```python
def test_fal_video_client_429_最大リトライ後に_FalClientError():
    monkeypatch.setattr(...)
    with pytest.raises(FalClientError):
        run_with_fake_429_response()
```

---

## 4. ファクトリ (= ドメインオブジェクトの生成ヘルパー)

新規テストでは **`tests/factories/` のヘルパーを使い、screenplay 構造を直接書かない**。既存テストでも該当のヘルパーが使える形にリファクタが推奨される (= 必須ではない)。

```python
# tests/factories/screenplay.py
def make_line(text="やばい", emotion="焦り", start=0.0, end=1.0, **overrides) -> Line:
    return Line(text=text, emotion=emotion, start=start, end=end, **overrides)

def make_scene(lines=None, location_ref="home_office", **overrides) -> Scene:
    return Scene(
        lines=lines or [make_line()],
        location_ref=location_ref,
        animation_prompt="subject reacts naturally",
        character_refs=["f1__office"],
        **overrides,
    )

def make_screenplay(scenes=None, caption="テスト用キャプション", **overrides) -> Screenplay:
    return Screenplay(caption=caption, scenes=scenes or [make_scene()], **overrides)
```

ドメインモデルが変わったときの修正点を**この 1 ファイルに集約**する。

---

## 5. モック / fixture 規約

### 5.1 既に autouse で動いているもの (`tests/conftest.py`)

| fixture                  | 効果                                                                                                              |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| `_isolate_cost_records`  | `COST_RECORDS_PATH` を `tmp_path` へ。本番 `data/cost_records.jsonl` を汚さない                                   |
| `_isolate_job_store`     | `JOB_STORE_DIR` を `tmp_path` へ。本番 `data/jobs.json` を汚さない                                                |
| `_stub_character_images` | `analyze.character_meta.list_character_images` を空リストに stub。`@pytest.mark.real_characters_dir` で個別解除可 |

新規 autouse は安易に増やさない (= 隠れた依存になる)。本番パス汚染リスクが新たに見つかった場合のみ追加する。

### 5.2 外部 API クライアントのモック

`monkeypatch.setattr` で client の関数を fake に差し替える。レスポンス JSON は `tests/fixtures/<provider>/*.json` に置いて再利用する。

```python
def test_tts_one_shot_標準ケース(monkeypatch, tmp_path):
    fake_response = json.loads(Path("tests/fixtures/elevenlabs/one_shot_ok.json").read_text())
    monkeypatch.setattr(
        elevenlabs_client, "generate_with_timestamps",
        lambda **kwargs: fake_response,
    )
    ...
```

### 5.3 HTTP モック

requests を直接叩く client は `requests_mock` (= 既に依存にあれば) または `monkeypatch.setattr(requests, "post", ...)` で。フル WSGI のリクエストは `preview_server.app.test_client()` を使う。

### 5.4 時刻 / 乱数 / スリープ

- 時刻: `monkeypatch.setattr(<module>, "_now", lambda: datetime(2026, 5, 7, 12))`
- 乱数: テスト先頭で `random.seed(0)` か `numpy.random.seed(0)`
- `time.sleep`: backoff 含むテストでは `monkeypatch.setattr(time, "sleep", lambda _: None)`

### 5.5 watchdog / threading

`final_import.watcher` のような長寿命 thread は **`tmp_path` に対して短命に起動 → 期待イベント発火 → 停止** までを 1 テストで完結させる。`time.sleep` の代わりに `threading.Event.wait(timeout=2)` でデッドロック検知をしやすくする。

---

## 6. カスタムマーカー

`tests/conftest.py` で扱う or 個別テストで宣言する:

| marker                | 意味                                                                                      |
| --------------------- | ----------------------------------------------------------------------------------------- |
| `real_characters_dir` | `_stub_character_images` を skip し、`characters/` の物理存在を前提にした検証を回す       |
| `slow`                | 1 ケース 1 秒超のテスト。CI 高速ジョブから除外したい場合に使う (= `pytest -m "not slow"`) |
| `external_api`        | 環境変数で本物の API key を渡したときだけ走らせる E2E テスト (基本 skip)                  |

`pytest.ini` / `pyproject.toml` は現状無い。カスタムマーカーが増えた時点で `pyproject.toml` の `[tool.pytest.ini_options]` に登録する。

---

## 7. カバレッジ目標 (層別)

| 層                      | 対象例                                                                                                                          | 目標カバレッジ          |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------- | ----------------------- |
| ドメインロジック        | `screenplay_validator.py` / `analyze/compose.py` / `progress_store.py` / `final_import/core.py` / `final_import/fingerprint.py` | **90%+**                |
| 外部 API クライアント   | `elevenlabs_client.py` / `imagen_client.py` / `fal_video_client.py` / `lipsync_client.py` / `platform_clients/*.py`             | **80%+**                |
| Stage 実装 (生成・編集) | `scene_gen.py` / `compositor.py` / `staged_pipeline.py` / `audio_dynamics.py`                                                   | **75%+**                |
| エントリ層 (CLI / HTTP) | `main.py` / `preview_server.py` の主要 endpoint                                                                                 | **60%+**                |
| Streamlit dashboard     | `scripts/dashboard.py`                                                                                                          | 対象外                  |
| React フロント          | `frontend/`                                                                                                                     | 対象外 (E2E は将来検討) |

カバレッジ計測は `pytest-cov` を導入したらこのターゲットを CI で gate する想定。現時点では計測自体が任意。

---

## 8. 実行コマンド

```bash
# 全テスト
pytest

# 特定ファイル
pytest tests/test_final_import.py

# 特定関数
pytest tests/test_final_import.py::test_import_final_標準ケース

# キーワードマッチ
pytest -k "fingerprint"

# slow を除外
pytest -m "not slow"

# 失敗箇所の詳細
pytest -x -vv

# カバレッジ (pytest-cov 導入後)
pytest --cov --cov-report=term-missing --cov-report=html
```

---

## 9. 新規 stage / API client を足すとき

順序を守ると壊れたテストが書きづらくなる:

1. ドメインモデルの **正常系** を 1 本書く (= ファクトリで作って期待値を assert)
2. **バリデーション** を 1〜3 本 (= 不正入力で reject される)
3. **エラーハンドリング** を 1〜3 本 (= 外部 API timeout / 429 / 不正レスポンス)
4. 必要なら **integration** を 1 本 (= staged_pipeline 経由で 1 stage 通す)
5. CI 想定で `pytest -k <new>` が 5 秒以内に終わることを確認

---

## 10. 既存テストとの整合性

- 既存 80+ テストは順次 §4 のファクトリ / §5 の fixture 規約に寄せていくが、**一気にリファクタしない**。新規テストから新規約で書き、既存テストは触る機会があるときに合わせる
- 大幅な変更を伴う修正 (= ファクトリ導入 / カバレッジ計測導入) は別 PR に分ける

---

## 11. CI 想定 (将来)

CI が立ち上がった時点で gate するもの:

- `pytest -m "not slow and not external_api"` の全パス
- カバレッジが §7 のターゲット未満なら fail
- ruff format / ruff check が clean
- frontend は `npm run build` が通る

---

最終更新: 2026-05-07
