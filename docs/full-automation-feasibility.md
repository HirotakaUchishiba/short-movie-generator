# フルオートループ実現可能性の判定

本ドキュメントは「cron で参考動画を取得 → 抽象台本生成 → 本パイプラインを完全自動実行 → SNS 公開 → メトリクス取得 → 次回生成へフィードバック」という閉ループ運用が現状の実装でどこまで成立するかを判定し、足りない部分の段階的な埋め方を残す。

判定の根拠は 2026-05-07 時点のリポジトリスナップショットに基づく。

---

## 1. 結論

**技術的には可能。ただし「現状のまま cron に乗せる」と 15〜20% は見るに堪えない出力になる。**

- ループの骨格は **7〜8 割実装済み**。残り 2〜3 割は薄い実装で繋がる
- 一方で **品質保証** と **メトリクス → 次回生成へのフィードバック閉ループ** は事実上ゼロ
- フィードバック無しの open-loop なら **1〜2 週間** で組める
- 「フィードバックを得て改善」まで含めた closed-loop は別途 **1〜2 ヶ月** の実装が必要

---

## 2. 構成要素別判定

| 要素                          | 状態                                     | 根拠                                                                                                                                                                  |
| ----------------------------- | ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| cron 発火                     | ❌ 未実装 (= 外部 scheduler で十分)      | リポジトリに cron コード無し                                                                                                                                          |
| 参考動画の自動 DL             | ❌ 未実装 (= yt-dlp で薄く包めば OK)     | `yt-dlp` / `youtube-dl` / `scrape` / `trending` の grep ヒットゼロ。`reference_videos` テーブル (`analytics/schema.sql:130-137`) は source URL 列を持たない           |
| analyze → 抽象台本            | ✅ ヘッドレス完結                        | `scripts/analyze_video.py` はローカルパスを渡すだけで `screenplays/auto_<sha>.json` を吐く                                                                            |
| 話者マッピング                | 🟡 単一キャラなら fallback で抜けられる  | `analyze/compose.py:43-64` の `_resolve_speaker_to_ref` に「empty speaker → fallback_ref」の逃げ道                                                                    |
| 承認ゲート (Stage 1〜6)       | 🟡 auth 無しの REST で叩き放題           | `POST /api/projects/<TS>/approve` (`preview_server.py:340-355`) は token / CSRF なし。`progress_store.mark_approved()` 直叩きでも可                                   |
| Stage 7 取込                  | 🟡 raw を canonical 化すれば CapCut 不要 | `final_import.import_final` は audio fingerprint 失敗を warning でスルー (`core.py:167`)。`output/reels_<TS>.mp4` をそのまま流して通る                                |
| Stage 8 / YouTube             | ✅ refresh token で完全 headless         | `platform_clients/youtube.py:228-237`。ただし quota 403 は未ハンドル (`platform_clients/youtube.py:280`)                                                              |
| Stage 8 / IG・TikTok 公開     | ❌ Graph API upload 未実装               | `platform_clients/instagram.py` `tiktok.py` は **insights / stats fetch だけ実装済**。upload は `pbcopy + open -a` の半自動止まり (`final_import/publish.py:263-335`) |
| metrics 取得                  | ✅ 3 プラットフォームとも headless 動作  | `scripts/fetch_metrics.py` 経由。env を揃えれば人手ゼロ                                                                                                               |
| メトリクス → 次回生成への反映 | ❌ ダッシュボード表示のみ                | `v_performance` view を読むのは `scripts/dashboard.py` だけ。`improvement` / `feedback` / `optimize` / `best_*` の grep ヒットゼロ                                    |

---

## 3. 真のブロッカー

### 3.1 品質検証がほぼ無い

現在自動で守られているのは以下のみ:

- **アーティファクト破損検知**: `artifact_integrity.py` が PNG / MP4 / 音声の truncation を検出
- **Imagen storyboard 再試行**: `scene_gen.py:456-489` が漫画風コマ割り出力を検出して negative prompt 付きで再生成
- **screenplay スキーマ検証**: `screenplay_validator.py`

人間が承認時に弾いている **キャラ崩壊・音声クリッピング・字幕視認性・リップシンク誤差** は完全に未検出。フルオートに移すと、これらが警告無しで本番にすり抜ける。

### 3.2 TTS / lipsync にリトライが無い

- Kling は 5 回 exponential backoff (`fal_video_client.py:18-118`)
- Imagen は 2 回 + storyboard re-prompt (`scene_gen.py:456`)
- **ElevenLabs は素通り**。`elevenlabs_client` に retry 無し
- **Sync.so / FAL / DomoAI も素通り** (リトライをプロバイダ任せ)

1 日数本の cron なら API 揺らぎが直で品質劣化に響く。

### 3.3 closed-loop を成立させるコードがゼロ

「フィードバックを得て改善」を本気で組むなら、以下が必要だが **どれも未実装**:

- 投稿後メトリクスを hook_type / tone / emotion / theme でランキング
- 高パフォーマンスの軸を **次回 analyze / compose の prompt に注入**
- (任意) Claude Haiku で `v_performance` を要約 → 自動 screenplay 生成のシステムプロンプトに mix

現状は `scripts/dashboard.py` が `v_performance` を **人間が眺めるための** Streamlit UI に出すだけ。

---

## 4. コストと throughput の現実

- 1 動画 約 **$4.70** (Imagen $1.34 + Kling $3.36, ElevenLabs はプラン内, `docs/architecture-decisions.md`)
- 5 本/日 で **約 $23.5/日 ≒ $700/月**
- 律速は **Kling V3 の同時 2 本** (= cost ではなく queue depth)
- Anthropic API のレート制限戦略は未整備だが、cron 数本/日のオーダーなら実質問題にならない

---

## 5. 段階プラン

| Phase                       | 内容                                                                                                        | 実装規模  |
| --------------------------- | ----------------------------------------------------------------------------------------------------------- | --------- |
| **Phase 1. Open-loop 量産** | cron + yt-dlp + 自動 approve curl + YouTube 公開 + metrics 蓄積                                             | 1〜2 週間 |
| **Phase 2. 品質保証**       | TTS / lipsync リトライ、ffmpeg で audio clip / silence 検出、IG・TikTok Graph API upload 実装               | 約 1 ヶ月 |
| **Phase 3. closed-loop**    | metrics → hook_type / tone のランキング → 次回 analyze / compose の prompt injection (Haiku で再ランクも可) | 1〜2 ヶ月 |

Phase 1 だけで「cron で勝手に YouTube に毎日上げ続けるシステム」は成立する。**Phase 3 まで踏まないと "改善ループ" とは呼べない** ので、ここをどこまで作るかが意思決定ポイント。

---

## 6. Phase 1 実装スケッチ

最小構成のコマンド連鎖は以下の形になる。新規実装が必要なのは a / b / e の薄いラッパーのみ。

```bash
# a. 参考動画を yt-dlp で取得 (新規スクリプト)
yt-dlp -f best <URL> -o "ref_$(date +%Y%m%d_%H%M%S).mp4"

# b. 抽象台本を生成 (既存)
python3 scripts/analyze_video.py ref_*.mp4
#   → screenplays/auto_<sha>.json

# c. プロジェクト作成 + Stage 1 起動 (既存)
python3 main.py auto_<sha>
#   → temp/<TS>/ が掘られる

# d. Stage 1〜6 を auto-approve でチェイン (新規 bash ループ)
TS=<生成された TS>
for stage in script tts bg kling scene overlay; do
  curl -s -X POST http://127.0.0.1:5555/api/projects/$TS/approve \
       -H "Content-Type: application/json" \
       -d "{\"stage\":\"$stage\"}"
  python3 main.py auto_<sha> --resume $TS
done

# e. Stage 7: raw を canonical として登録 (CapCut 編集をスキップ)
python3 main.py auto_<sha> --resume $TS \
  --import-final output/reels_$TS.mp4
python3 main.py auto_<sha> --resume $TS --canonical <imported_filename>

# f. Stage 8: YouTube に公開 (既存)
python3 main.py auto_<sha> --resume $TS --publish youtube --privacy unlisted

# g. メトリクス取得 (cron で別レーンに切る)
python3 scripts/fetch_metrics.py --platform youtube
```

### Phase 1 で **必ず** 同時にやること

- `auto_approve` ループの **タイムアウト** (= 1 ステージ最長 N 分で abort)
- 失敗時の **メール / Slack 通知** (= 人間レビューに戻す経路)
- `DISABLE_FINAL_WATCHER=1` をデフォルトに (= 自動取込経路と watchdog 経路の二重発火を防ぐ)
- 1 日の生成本数キャップ (= API rate / 課金事故防止)

---

## 7. 想定される落とし穴

| 罠                                   | 影響                                                                          | 対策                                                                |
| ------------------------------------ | ----------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| ElevenLabs の沈黙 / 歪みアウトプット | 字幕とリップシンクが全部ズレる                                                | 生成後に `ffmpeg volumedetect` で平均 dB と silence ratio を検査    |
| Kling のキャラ崩壊                   | 同一動画内で別人になる                                                        | scene 単位の人物検出 + reference image との embedding 距離で reject |
| YouTube quota 403                    | publish が止まる (`platform_clients/youtube.py:280` で例外がスローされたまま) | 403 を catch → 翌日にキューイング                                   |
| Sync.so 20MB 超過                    | lipsync が無音で返る恐れ                                                      | 入力前に bitrate を再計算してリエンコード                           |
| 多話者 screenplay の話者マッピング   | speaker_2 以降が fallback に潰れる                                            | analyze 段階で「単一話者の動画だけを cron 対象にする」フィルタ      |
| metrics 反映の遅延                   | 投稿直後のメトリクスは無に近い                                                | feedback ループは 24h 以上経過した posts のみを見る                 |

---

## 8. 参考: 既存実装のエントリポイント

| 役割                       | 場所                                              |
| -------------------------- | ------------------------------------------------- |
| ステージ進行管理           | `progress_store.next_stage()` / `mark_approved()` |
| 承認 REST                  | `preview_server.py:340-355`                       |
| 抽象台本 → 完成 screenplay | `analyze/compose.py:43-64`                        |
| Stage 7 取込               | `final_import/core.py:92-187`                     |
| YouTube 公開               | `platform_clients/youtube.py:199-367`             |
| YouTube refresh token      | `platform_clients/youtube.py:228-237`             |
| メトリクス取得             | `scripts/fetch_metrics.py`                        |
| Streamlit ダッシュボード   | `scripts/dashboard.py`                            |
| analytics view             | `analytics/schema.sql:140-166` (`v_performance`)  |
