# ユビキタス言語

本ドキュメントは tensyoku_movie_generator のドメイン用語と実装上の名前の対応表。会話・ドキュメント・コードで同じ概念を別名で呼ばないようにするための辞書。

新しい概念を導入したらここに必ず追記する。鮮度を保つため末尾の最終更新日を更新する。

---

## 1. コンテンツ構造

| 用語              | コード/型                        | 説明                                                                               |
| ----------------- | -------------------------------- | ---------------------------------------------------------------------------------- |
| 台本 (screenplay) | `screenplay.json` / `Screenplay` | 1 動画分の構造化された JSON。`caption` と `scenes[]` を持つ                        |
| キャプション      | `screenplay.caption`             | SNS 投稿用本文 + ハッシュタグ                                                      |
| シーン            | `screenplay.scenes[]` / `Scene`  | 1 Kling クリップに対応する単位。`lines[]` `location_ref` `animation_prompt` を持つ |
| ライン (line)     | `scenes[].lines[]` / `Line`      | シーン内の 1 セリフ。`text` `emotion` `delivery` `start` `end`                     |
| 抽象台本          | analyze pipeline 出力            | ビジュアル要素を持たない台本。speaker は `speaker_1`, `speaker_2` の匿名 ID        |
| 完全台本          | compose 後                       | 抽象台本 + 話者マッピング + scene 個別フィールドを compose した最終形              |
| 話者マッピング    | `speaker_to_ref`                 | 匿名 `speaker_N` を実 character ref に対応付ける辞書                               |

## 2. アセット

| 用語               | コード/パス                             | 説明                                                                                |
| ------------------ | --------------------------------------- | ----------------------------------------------------------------------------------- |
| キャラ (character) | `characters/<base>/...`                 | 被写体エンティティ。`voice.json` + 衣装バリアント PNG を持つ                        |
| ベース ID          | `<base>` (例: `f1`, `m1`)               | 顔・体型・髪型が同じ人物の ID                                                       |
| 衣装バリアント     | `<wardrobe>` (例: `office`)             | 同じ base の衣装違い                                                                |
| 解決済み ref       | `<base>__<wardrobe>` (例: `f1__office`) | screenplay の `character_refs` に入る形式。衣装無しは `<base>` 単独                 |
| ロケーション       | `locations/<id>.json`                   | `decor` + `lighting` + `color_palette` + `props` + `camera_distance` を持つ撮影設定 |
| ロケ参照           | `scenes[].location_ref`                 | scene が使う `location_id`                                                          |
| ロケサムネ         | `locations/<id>.preview.png`            | UI 一覧表示用                                                                       |

## 3. パイプライン構造

| 用語                         | コード/パス                   | 説明                                                                                |
| ---------------------------- | ----------------------------- | ----------------------------------------------------------------------------------- |
| ステージ (stage)             | 1〜8                          | 生成 → 編集 → 公開を 8 段階に分割した単位                                           |
| プロジェクト (project)       | `temp/<TS>/`                  | 1 本の動画分の作業ディレクトリ。`TS` は `YYYYMMDD_HHMMSS`                           |
| TS                           | `<TS>`                        | プロジェクト識別子                                                                  |
| テンプレート                 | `screenplays/<name>.json`     | 新規 project 作成時の素材 (git 追跡)                                                |
| プロジェクトスナップショット | `temp/<TS>/screenplay.json`   | template から copy された immutable な作業コピー。Stage 1〜6 の読み書きはここだけ   |
| 進捗                         | `temp/<TS>/tmp-progress.json` | 各 stage の `generated_at` / `approved_at` / `regen_count`                          |
| 中間アーティファクト         | `temp/<TS>/tmp/*`             | 各 stage の中間成果物 (`tts_*.mp3` / `bg_*.png` / `kling_*.mp4` / `scene_*.mp4` 等) |
| pipeline raw                 | `output/reels_<TS>.mp4`       | Stage 7 で書き出される字幕焼き込み済み動画 (= 編集前の最終形)                       |
| メタデータ                   | `temp/<TS>/metadata.json`     | screenplay sha / `analyze_job_id` / `final_versions[]` / `published_posts[]`        |

## 4. 生成・編集

| 用語         | コード                     | 説明                                                             |
| ------------ | -------------------------- | ---------------------------------------------------------------- |
| analyze      | `scripts/analyze_video.py` | 参考動画から抽象台本 JSON を逆算生成                             |
| compose      | `analyze/compose.py`       | 抽象台本 + 話者マッピング + visual fields を組んで完全台本にする |
| 再生成       | UI の各カードのボタン      | 該当 stage の単位アーティファクトを再実行                        |
| TTS          | Stage 2                    | ElevenLabs eleven_v3 で screenplay 全体を **1-shot** 生成        |
| 背景生成     | Stage 3 / Imagen           | scene ごとの `bg_<S>.png`                                        |
| Kling        | Stage 4 / fal.ai Kling V3  | I2V でシーン動画を生成                                           |
| シーン合成   | Stage 5                    | 音声重ねと lipsync で `scene_<S>.mp4` を仕上げる                 |
| オーバーレイ | Stage 7                    | 字幕の焼き込み (`overlaid.mp4` → `output/reels_<TS>.mp4`)        |

## 5. 品質保証 (Stage 1〜6 の承認サイクル)

| 用語            | コード                                                               | 説明                                                                      |
| --------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| 承認 (approve)  | `POST /api/projects/<TS>/approve` / `progress_store.mark_approved()` | 当該 stage を OK 判定し次 stage を解除                                    |
| 否認 (reject)   | (Phase 0 で実装予定)                                                 | 不良としてマークし `data/qa_failures/` に dump                            |
| 承認解除 (連鎖) | regenerate 時の自動処理                                              | 後続 stage の承認も解除して再判定を要求                                   |
| バリデータ      | `qa/validators/*.py` (Phase 2)                                       | 自動 QA。silence / clipping / character drift / subtitle overlap 等を判定 |

## 6. 音声・字幕

| 用語                | コード                           | 説明                                                                                                    |
| ------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------- |
| inline audio tag    | `[surprised]`, `[whispers]` 等   | eleven_v3 用の TTS 内タグ。`line.text` 先頭に挿入される                                                 |
| emotion             | `lines[].emotion`                | 感情ラベル。`config.EMOTION_AUDIO_TAGS` で audio tag に、`EMOTION_MOTION_ADDONS` で Kling motion に変換 |
| delivery            | `lines[].delivery`               | 話し方の自然言語記述。`config.DELIVERY_TAG_ENABLED` 時に inline tag 化                                  |
| audio_tags          | `lines[].audio_tags[]`           | per-line で手動指定する audio tag                                                                       |
| pronunciation_hints | `lines[].pronunciation_hints`    | TTS 送信前のテキスト置換辞書                                                                            |
| subtitle chunk      | `lines[].subtitles[]`            | 字幕の手動分割。両時刻指定 (= 手打ち) または両省略 (= auto) のいずれか                                  |
| auto chunk          | `subtitles[]` の time 両省略要素 | 文字数比例で時刻を解決                                                                                  |

## 7. リップシンク

| 用語           | コード                 | 説明                                                                               |
| -------------- | ---------------------- | ---------------------------------------------------------------------------------- |
| lipsync        | `lipsync_client.apply` | Sync.so 公式 API (`/v2/generate` multipart + polling) で口の動きを音声に同期       |
| Sync.so モデル | `SYNCSO_LIPSYNC_MODEL` | `lipsync-2` (既定) / `lipsync-2-pro` / `lipsync-1.9.0-beta` / `react-1` / `sync-3` |

## 8. 取込 (Stage 8)

| 用語          | コード                                         | 説明                                                                           |
| ------------- | ---------------------------------------------- | ------------------------------------------------------------------------------ |
| final import  | `final_import.import_final()`                  | CapCut 編集後 (or raw のまま) の動画を取り込む処理                             |
| watchdog      | `temp/<TS>/final/*.mp4` 監視                   | size 安定 3 秒で自動取込発火                                                   |
| final version | `metadata.json.final_versions[]`               | 取り込まれた final 動画のバージョン履歴                                        |
| canonical     | `final_versions[].is_canonical`                | analytics と publish が指す正本 (= 1 プロジェクトに 1 本)                      |
| 音声指紋      | `final_import.fingerprint.compute_match_score` | TTS 音声が final にも残っているかを `[0, 1]` で判定。閾値 `0.6` 未満は warning |

## 9. 配信 (Stage 8 / SNS)

| 用語            | コード                          | 説明                                                                 |
| --------------- | ------------------------------- | -------------------------------------------------------------------- |
| publish         | `main.py --publish <platform>`  | SNS への投稿処理                                                     |
| YouTube Shorts  | `platform_clients/youtube.py`   | Data API resumable upload で完全自動                                 |
| Instagram Reels | `platform_clients/instagram.py` | Phase 1 は半自動 (clipboard + アプリ起動)。Graph API は stub 済      |
| TikTok          | `platform_clients/tiktok.py`    | Phase 1 は半自動。Display API は stub 済。CSV 取込フォールバックあり |
| privacy         | `--privacy unlisted`            | YouTube の公開範囲 (`unlisted` / `private` / `public`)               |

## 10. 分析 (Analytics)

| 用語                | コード                            | 説明                                                                               |
| ------------------- | --------------------------------- | ---------------------------------------------------------------------------------- |
| screenplay 自動タグ | Claude Haiku                      | `hook_type` / `tone` / `dominant_emotion` / `theme` / `character_archetype` を付与 |
| post                | `analytics.posts` テーブル        | SNS 投稿レコード。`video_id` と `platform_url` で識別                              |
| post_metrics        | `analytics.post_metrics` テーブル | 時系列メトリクス (views / likes / comments / completion_rate)                      |
| v_performance       | view                              | 台本 × 動画 × 投稿 × 最新メトリクスの横断ビュー                                    |
| metrics fetch       | `scripts/fetch_metrics.py`        | YouTube / IG / TikTok から最新値を取得                                             |

## 11. ステージ遷移

```
Stage 1 (台本)
  → Stage 2 (TTS)
  → Stage 3 (背景)
  → Stage 4 (Kling)
  → Stage 5 (音声/リップシンク合成)
  → Stage 6 (字幕 / pipeline raw 書き出し)
  → [CapCut 等で外部編集]
  → Stage 7 (final import / canonical 確定)
  → Stage 8 (publish)
```

各 stage は **承認 (approve) を経るまで次 stage は実行できない**。Stage 7 / 8 はユーザの外部アクション (= ファイル drop / publish コマンド) が起点。

## 12. ステータス語彙

| 状態         | 意味                                                                            |
| ------------ | ------------------------------------------------------------------------------- |
| pending      | まだ generate されていない or generate されたが approve されていない            |
| generated    | アーティファクト出力済み・承認待ち                                              |
| approved     | 承認済み・次 stage 解除済み                                                     |
| auto_flagged | (Phase 2) validator が NG 判定し自動 retry/reject に回された                    |
| canonical    | (Stage 8) 取り込まれた final のうち analytics / publish の正本に指定された 1 本 |

## 13. emotion → 自動付与の対応 (抜粋)

`config.EMOTION_AUDIO_TAGS` と `config.EMOTION_MOTION_ADDONS` で定義される。詳細はコード参照。

| emotion    | inline audio tag | Kling motion addon (例)        |
| ---------- | ---------------- | ------------------------------ |
| 驚き       | `[surprised]`    | sudden head turn, widened eyes |
| 喜び       | `[happy]`        | bright smile, slight nod       |
| 焦り       | `[panicked]`     | quick hand movement            |
| 落胆       | `[disappointed]` | slumped shoulders              |
| 中立       | (なし)           | (なし)                         |
| 満足       | `[satisfied]`    | gentle smile                   |
| 困惑       | `[confused]`     | tilted head                    |
| 怒り       | `[angry]`        | clenched jaw                   |
| 恥ずかしさ | `[embarrassed]`  | averted gaze                   |

per-line で voice 表現を細かく制御したいときは `audio_tags[]` (例: `["whispers"]`, `["shouts"]`, `["crying"]`) を直接指定する。`config.AVAILABLE_AUDIO_TAGS` に候補一覧。

---

最終更新: 2026-05-07
