# Phase 2 実装記録 (= 自動 QA Validator)

**date**: 2026-05-08 / **PR**: #70 / **branch**: `feat/phase-2-qa`

`docs/plannings/2026-05-07_full-automation-implementation-plan.md` §4 (Phase 2) の C-2.1 / C-2.2 / C-2.3 / B-2.4 を一括実装。

## 設計判断 (= 計画書原案からの逸脱)

| 計画書原案                                                | 実装                                                                               | 理由                                                                                                                                                                              |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| しきい値は実データ (qa_failures) からチューニング後に確定 | **暫定値で固定 + `eval_validators` で運用者が判断**                                | しきい値を決める前にコード実装が無いと auto_loop が回らず、データも貯まらない。鶏卵を解くため、Phase 0 の正常データを参考に保守的初期値を入れて運用しながら baseline を取り直す。 |
| CLIP / U²-Net / opencv は必須依存                         | **optional + `skipped_result` で吸収**                                             | CI / dev に重い ML 依存を強制すると単純なコード修正でも ROC 取得まで CI が走る。本実装は ML 依存が揃った環境でのみ有効化する建付け。                                              |
| stage 全体 retry                                          | **per-scene retry (= ValidationResult.scene_idx 単位)**                            | Kling 1 シーン $0.6 vs 全シーン $3.4。validator が scene_idx を返すなら局所修正の方がコスト効率良い。fail が stage 全体 (scene_idx=None) のときだけ full regen にフォールバック。 |
| QA 全体の on/off は config フラグ                         | **2 段階: `QA_VALIDATORS_ENABLED` (全 off) + `QA_VALIDATOR_BLACKLIST` (個別 off)** | 個別の重量級 validator (CLIP / lipsync_quality) を運用環境ごとに on/off できるように。:`/`,` 区切りどちらも受ける。                                                               |
| retry 上限は固定                                          | **stage 別 (`QA_RETRY_LIMITS`)**                                                   | TTS は 1 線で 30 文字 5 秒なので retry が安く、Kling は 1 retry $3.4。stage の単価で retry 回数を変える。                                                                         |

## ValidationResult のスキーマ

```python
@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    score: float                     # 0.0 (= fail) - 1.0 (= 完璧) — retry の優先順位用
    reason: str                      # fail 時の人間 / Slack 表示
    metrics: dict[str, float]        # silence_ratio / clip_distance / wpm 等
    scene_idx: int | None            # None なら stage 全体
    line_idx: int | None
    tag: str | None                  # qa.categories.QA_FAILURE_TAGS の 1 つ
```

`tag` は fail 時のみ意味あり。`auto_loop` が `qa_failures` に書き込むタグになる。

## stage 別 validator マッピング

| stage     | validators                                        | 備考                                                                |
| --------- | ------------------------------------------------- | ------------------------------------------------------------------- |
| `tts`     | `audio_silence`, `audio_clipping`, `story_pacing` | per-line で実行、`tts_<S>_<L>.mp3` を全部チェック                   |
| `bg`      | `subtitle_overlap`                                | bg 画像の下 1/3 の stddev (= 視覚要素過多検出)                      |
| `kling`   | `character_drift`                                 | CLIP が無ければ skip                                                |
| `scene`   | `lipsync_quality`                                 | opencv + librosa が無ければ skip                                    |
| `overlay` | `subtitle_readability`                            | screenplay の chunk 文字長で代用 (= overlay 動画フレーム解析は重い) |

## `generation_records.validator_scores` のスキーマ

```json
{
  "tts": { "count": 5, "passed": 4, "failed": 1, "avg_score": 0.78 },
  "bg": { "count": 3, "passed": 3, "failed": 0, "avg_score": 0.92 },
  "kling": { "count": 3, "passed": 0, "failed": 0, "avg_score": 0.0 }
}
```

stage 単位の集計のみ保存。個別 ValidationResult は残さない (= `qa_failures` に scene_idx/line_idx ベースの failure 行があるので、横断分析はそちら経由)。

## per-scene retry の挙動

```python
for stage in INTERNAL_STAGES:
    max_retries = QA_RETRY_LIMITS.get(stage, 1)
    _run_one_stage(...)            # 初回生成
    retries = 0
    while True:
        results = _validate_stage(ts, stage)   # registry 経由
        fails = [r for r in results if not r.passed]
        if not fails:
            break
        if retries >= max_retries:
            raise AutoLoopAborted(...)
        retries += 1
        _retry_failed_scenes(sp_name, ts, stage, fails)
        # ↑ ValidationResult.scene_idx ごとに staged_pipeline.regen(scene_idx=N)
        #   scene_idx=None の fails が混ざっていれば full-stage regen にフォールバック
```

retry が走るたびに `_archive_before_retry(scene_idx=...)` が前世代を `regenerate_implicit` で `qa_failures` に残す。これは Phase 0 の reject API 経由の archive と同じ source 値で、Phase 3 のしきい値学習に同列で使える。

## eval_validators.py の運用

```bash
python3 qa/eval_validators.py --days 30
# → data/validator_eval/<YYYY-Wxx>.json
```

直近 30 日の `qa_failures` を `(ts, scene_idx, line_idx)` で集合演算:

| set                       | 意味                                                        |
| ------------------------- | ----------------------------------------------------------- |
| `human`                   | UI で人間が NG と reject したもの (`source="human_reject"`) |
| `auto`                    | validator が NG と判定したもの (`source="auto_flagged"`)    |
| `both = human ∩ auto`     | validator が正しく検出した不良                              |
| `recall = both / human`   | validator がどれだけ取り漏らしたか                          |
| `precision = both / auto` | validator が誤検出をどれだけ含むか                          |

しきい値の自動チューニングはまだ実装しない (= Phase 3 以降)。週次で出した数値を運用者が読み、`SILENCE_RATIO_FAIL` 等の constant を直接いじる。

## 出口 KPI チェック

> Phase 2 出口 KPI: 直近 30 本で reject 率 < 5% / recall ≥ 80% / precision ≥ 70%

| 項目                           | 状態                                                               |
| ------------------------------ | ------------------------------------------------------------------ |
| validator スイート完備         | ✅ 7 軸全て skeleton 投入                                          |
| stage 別 retry 上限            | ✅ `QA_RETRY_LIMITS`                                               |
| auto_loop 統合                 | ✅ registry 経由 + per-scene retry                                 |
| `validator_scores` 永続化      | ✅ `generation_records.validator_scores` (JSON)                    |
| eval スクリプト                | ✅ `qa/eval_validators.py`                                         |
| recall ≥ 80% / precision ≥ 70% | ⏳ **実運用検証**。Phase 1 で蓄積された qa_failures を入力に評価   |
| reject 率 < 5%                 | ⏳ **実運用検証**。Phase 1 + Phase 2 の auto_loop を回しながら測定 |

つまり**コードの validator スイートは揃った** が、しきい値の妥当性は実データでの evaluator 結果を見ながらチューニングする。

## Phase 3 着手時の TODO

- 重量級 validator の本実装 (= CLIP / opencv 依存を `requirements.txt` に追加するか、 dockerfile で固める)
- `improvement/bandit.py` (= ε-greedy) と `improvement/prompt_injector.py` で `validator_scores` を意思決定の入力に使う
- `experiment_assignments` テーブル + `IMPROVEMENT_STRATEGY` の 3 値切替
- `v_axis_performance` view: hook_type / tone / dominant_emotion / theme で post_metrics の集計
- recall / precision のしきい値到達後、自動チューニング (= ROC で `SILENCE_RATIO_FAIL` 等を更新) を Phase 3.5 として検討

## 残課題

- `subtitle_overlap.py` の stddev ベースは精度低い (= 単色 bg + キャラ立位 が誤検出されやすい)。U²-Net で被写体 mask を取って IoU 計算する本実装は Phase 3.5 で
- `character_drift.py` の閾値 (`CHAR_DRIFT_DISTANCE_FAIL = 0.35`) は適当な暫定値。実運用 CLIP embedding distribution を見て調整
- `lipsync_quality.py` の 1 fps サンプリングは粗い。Phase 3.5 で 5-10 fps + mouth-mask 切り出し精緻化
- `subtitle_readability.py` は overlay 動画フレームの font size / contrast を見ない (= screenplay の文字長のみ)。Phase 3.5 で ASS スタイル / フレーム解析を加える
- `validator_scores` には個別 ValidationResult を含まない (= `qa_failures` 側を見れば再構築可能)。Phase 3 で後悔したら追加する
