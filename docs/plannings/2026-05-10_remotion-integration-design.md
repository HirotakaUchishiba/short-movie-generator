# Remotion 統合 設計案

> **⚠️ SUPERSEDED**: 本 doc は議論の途中スナップショットで、字幕レンダラ単独のスコープに閉じている。
> 統合・拡張版は **`2026-05-10_compositional-architecture.md`** を参照。

**date**: 2026-05-10 / **base branch**: `main` / **status**: superseded

Stage 6 (字幕オーバーレイ) を中心に **Remotion (= React で動画を宣言的に作るレンダラ)**
を本プロジェクトのパイプラインに段階導入する設計案。AI 生成 (TTS / Imagen / Kling /
Sync.so) は一切置き換えず、**「決まった素材と決まった編集方針を最終 mp4 に焼く」工程**
だけを置き換える。プラットフォーム別バリアント生成 / プレビューと最終出力の見た目一致 /
字幕表現の柔軟化を狙う。

---

## 0. 動機 (= なぜ Remotion か)

### 0.1 現状の痛み

| 場所                               | 痛み                                                                                                                                                                                                                                                                                  |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `compositor.py` の `drawtext` 経路 | ffmpeg `drawtext` filter で字幕を焼くため、CSS 相当の表現 (= 単語 karaoke / 感情別カラー / fade-in / bouncing) が事実上書けない。`_build_overlay_filter` は filter_complex の文字列組み立てが肥大化していて、新スタイル追加のたびに `_escape_fontfile` 等の枝が増える                 |
| `StageOverlay.tsx` のプレビュー    | `<video src="overlaid.mp4">` で **焼き込み済みの mp4** を再生する仕組み。手動チャンク編集後に「保存して焼き直し」ボタンを押すまで見た目が更新されない (= 1 回 30 秒 - 1 分の ffmpeg overlay 待ち)。さらに、UI 上の編集表示と最終出力の見た目が完全には一致しない (= フォント描画の差) |
| Stage 8 公開フロー                 | `output/reels_<TS>.mp4` が **3 platform 共通** で同じファイルを使う。YouTube Shorts / IG Reels / TikTok でテロップ位置・字幕スタイル・end card を出し分けたい場合、現状は手動編集に頼るしかない                                                                                       |
| アスペクト比                       | 9:16 縦のみ。同じ素材を 1:1 / 16:9 にも転用したい場合 (= YouTube 通常動画 / X 投稿) は手動 crop が必要                                                                                                                                                                                |

### 0.2 Remotion で解ける / 解けない

| 領域                                               | 効果 | 理由                                                                                                                                         |
| -------------------------------------------------- | ---- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| **字幕の表現力 (Stage 6)**                         | ◎    | `<AbsoluteFill>` + CSS で宣言的。emotion 別カラー / 単語 karaoke / fade / bouncing が React で書ける                                         |
| **プレビューと最終出力の一致 (Stage 6 UI)**        | ◎    | `<Player>` (= ブラウザ内プレビュー) と `npx remotion render` (= サーバ side レンダリング) が **同じ Composition** を再生するためピクセル一致 |
| **プラットフォーム別バリアント生成 (Stage 6 → 8)** | ◎    | テンプレを props で切り替えるだけで YouTube / IG / TikTok 用 mp4 を 3 本同時に吐ける。Kling / TTS の再生成は不要 (= 課金ゼロ)                |
| **アスペクト比違いの量産 (Stage 6 → 8)**           | ○    | `<OffthreadVideo>` を crop / scale で 9:16 / 1:1 / 16:9 を生成可能。被写体センターは要事前指定                                               |
| **過去 TS のシーンを混ぜたコンピレーション**       | △    | 技術的には可能だが TTS の文脈が切れて品質低下する。スコープ外とする                                                                          |
| **AI 生成の高速化 / コスト削減 (Stage 2-5)**       | ✕    | Remotion は AI を呼ばない。ここは効かない                                                                                                    |
| **無音区間の自動カット / 顔追跡リフレーミング**    | ✕    | Remotion 領域外 (= ffmpeg silencedetect / OpenCV の領域)                                                                                     |

### 0.3 採用基準

- 既存 `compositor.py` (= 644 行) を完全に置き換えるのではなく、**並列の overlay backend** として導入し、
  `config.OVERLAY_BACKEND = "ffmpeg" | "remotion"` で切替可能にする
- Phase 1 で Stage 6 だけを Remotion 化し、Phase 2 で UI プレビュー、Phase 3 で platform バリアントへ拡張
- いずれの Phase でも **Kling / Imagen / TTS / Sync.so の再呼出は発生しない** ことを設計上の不変条件とする

---

## 1. スコープ

### 1.1 含むもの

| カテゴリ                       | 内容                                                                                                                                                                                                     |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Remotion 学習用 minimum viable | `frontend/remotion/` ディレクトリに Remotion Composition (= `<ScreenplayComposition>`) を 1 本作る。`screenplay.json` + `temp/<TS>/tmp/scene_*.mp4` を読み込んで現状 ffmpeg overlay と同等の見た目を出す |
| Stage 6 (overlay) の置き換え   | `compositor.compose_video()` の代替として `compositor_remotion.compose_video_remotion()` を新設。`config.OVERLAY_BACKEND` で切替                                                                         |
| Stage 6 UI のプレビュー一致    | `StageOverlay.tsx` の `<video src="overlaid.mp4">` を Remotion `<Player>` に置き換え。手動チャンク編集が **リアルタイムで反映** される (= ffmpeg overlay の焼き直しを待たない)                           |
| platform 別テンプレ            | `frontend/remotion/templates/{youtube,instagram,tiktok}.tsx` を追加。Stage 8 公開時に `--platform` を指定すると対応テンプレで render                                                                     |
| metadata.json 拡張             | `final_versions[]` に `template: "youtube" \| "instagram" \| "tiktok" \| "raw"` フィールドを追加。canonical 切替時に platform 単位で選択可能に                                                           |

### 1.2 含まないもの

- **Kling / Imagen / TTS / Sync.so の置き換え** — Remotion は AI を呼ばない。Stage 2-5 は不変
- **過去 scene を混ぜたコンピレーション動画** — TTS の文脈が切れるため品質的に不可
- **無音カット / 顔追跡 / カラーグレーディング** — 別ツールの領域 (= Remotion でやるべきでない)
- **手書き screenplay からの逸脱** — CLAUDE.md の「指示の範囲を超えない」「台本は人間が作成する」を守る。Remotion はあくまで **screenplay に書かれた内容を映像化するレンダラ** であり、勝手に文言を変えたりシーンを足したりしない

---

## 2. アーキテクチャ

### 2.1 全体図 (= Remotion 統合後)

```
[screenplay.json]                                          ← 入力 (人間 or analyze pipeline)
   ↓
[Stage 1-5: 既存パイプライン (TTS / BG / Kling / Sync.so)]  ← AI 課金あり、変更なし
   ↓
[temp/<TS>/tmp/scene_<S>.mp4 + tts_<S>_<L>.mp3 + bg_<S>.png] ← 既存キャッシュ群、変更なし
   ↓
[Stage 6: composeBackend で分岐]
   ├─ config.OVERLAY_BACKEND = "ffmpeg"   → compositor.compose_video()         (現行)
   └─ config.OVERLAY_BACKEND = "remotion" → compositor_remotion.compose_video_remotion()
                                              ↓
                                            [render_plan.json を作成]
                                              ↓
                                            [npx remotion render --props=render_plan.json]
                                              ↓
                                            [output/reels_<TS>.mp4]
   ↓
[Stage 7: final_import が canonical 化] ← 既存 (auto_loop 経由のみ)
   ↓
[Stage 8: 公開]
   ├─ --platform youtube   → templates/youtube.tsx で再 render → output/reels_<TS>__youtube.mp4
   ├─ --platform instagram → templates/instagram.tsx で再 render → output/reels_<TS>__instagram.mp4
   └─ --platform tiktok    → templates/tiktok.tsx で再 render → output/reels_<TS>__tiktok.mp4
```

### 2.2 Remotion 側の構造 (`frontend/remotion/`)

```
frontend/remotion/
  Root.tsx                     ← registerRoot で Composition を登録
  compositions/
    ScreenplayComposition.tsx  ← 親 Composition。screenplay + asset paths を props で受ける
  components/
    Scene.tsx                  ← 1 シーン = <Sequence> + <OffthreadVideo> + <Audio>
    Subtitles.tsx              ← line / chunk 単位で字幕を描画 (= drawtext の代替)
    SubtitleChunk.tsx          ← 1 chunk の表示 + emotion 別スタイル + fade
  templates/
    base.tsx                   ← 共通の baseline (= 現行 ffmpeg overlay と同じ見た目)
    youtube.tsx                ← end card / チャンネル誘導 2 秒
    instagram.tsx              ← IG 風太字字幕 + 1 秒ホールド冒頭
    tiktok.tsx                 ← 単語 karaoke + 字幕位置を画面下 1/3 に
  hooks/
    useSceneOffsets.ts         ← scene_videos の実尺累積で offset を計算
  schemas/
    renderPlan.ts              ← Zod スキーマ (= compositor_remotion から渡す JSON の型)
```

### 2.3 backend 側 (`compositor_remotion.py`)

責務は **render_plan.json を組み立てて `npx remotion render` を起動するだけ**:

```python
def compose_video_remotion(
    scene_videos: list[str],
    screenplay: dict,
    temp_dir: str,
    output_path: str,
    template: str = "base",   # "base" | "youtube" | "instagram" | "tiktok"
) -> str:
    plan = _build_render_plan(scene_videos, screenplay, temp_dir)
    plan_path = os.path.join(temp_dir, "render_plan.json")
    with open(plan_path, "w") as f:
        json.dump(plan, f, ensure_ascii=False)

    cmd = [
        "npx", "remotion", "render",
        "frontend/remotion/Root.tsx",
        f"Screenplay-{template}",      # Composition ID
        output_path,
        "--props", plan_path,
        "--concurrency", str(config.REMOTION_CONCURRENCY),
        "--codec", "h264",
        "--crf", "18",
    ]
    subprocess.run(cmd, check=True, timeout=900)
    return output_path
```

`_build_render_plan()` の責務は現状の `_build_overlay_filter()` とほぼ同じで、
**実 timeline (= scene\_<S>.mp4 の実尺累積)** で line / chunk の絶対秒を解決する。
`_resolve_subtitle_timings()` (= 既存) はそのまま再利用する。

---

## 3. データフロー (= render_plan の中身)

`render_plan.json` のスキーマ (Zod 定義は `frontend/remotion/schemas/renderPlan.ts`):

```json
{
  "video": {
    "width": 1080,
    "height": 1920,
    "fps": 60,
    "duration_frames": 1800
  },
  "subtitle_y_from_bottom": 950,
  "scenes": [
    {
      "index": 0,
      "video_path": "/abs/temp/.../tmp/scene_001.mp4",
      "duration_sec": 3.45,
      "offset_sec": 0.0,
      "lines": [
        {
          "text": "やばいやばい",
          "emotion": "焦り",
          "hidden": false,
          "chunks": [
            {
              "text": "やばい",
              "start_abs_sec": 0.0,
              "end_abs_sec": 0.6,
              "anchor_kind": "auto"
            },
            {
              "text": "やばい",
              "start_abs_sec": 0.6,
              "end_abs_sec": 1.2,
              "anchor_kind": "manual"
            }
          ]
        }
      ]
    }
  ],
  "style": {
    "font_path": "/System/Library/Fonts/ヒラギノ角ゴシック W7.ttc",
    "font_size": 76,
    "font_color": "#FFFFFF",
    "border_color": "#000000",
    "border_width": 6,
    "line_gap": 14
  },
  "template": "base"
}
```

**重要な不変条件**:

- `chunks[].start_abs_sec` / `end_abs_sec` は **すでに `_resolve_subtitle_timings()` で解決済み** の値。
  Remotion 側ではこれをそのまま `<Sequence from end>` の境界として使う (= 解決ロジックの 2 重実装を避ける)
- `scenes[].duration_sec` は **scene\_<S>.mp4 の実尺** (= ffprobe 計測値)。screenplay の想定 duration ではない
- `scenes[].offset_sec` は実尺累積。これも backend 側で解決して props に詰める

これにより Remotion 側は「貰った数値を信じてレンダリングするだけ」になり、
タイミング解決ロジックの SSOT は backend (= `compositor.py` 既存関数) のままになる。

---

## 4. 移行段階

### Phase 0: 学習 + minimum viable (= 1 週間)

| 項目         | 内容                                                                                                                                        |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Goal         | 既存 1 TS の screenplay + scene_videos を Remotion で再生し、現行 `overlaid.mp4` と **見た目が同等** な mp4 を吐く                          |
| 成果物       | `frontend/remotion/` 一式 + `compositor_remotion.py` の試作                                                                                 |
| 検証         | 既存 1 TS (= 適当な完了済 project) で `npx remotion render` を回して、目視で字幕位置 / フォント / 色 が ffmpeg overlay と一致することを確認 |
| 不変条件     | `config.OVERLAY_BACKEND = "ffmpeg"` 既定のまま。本番経路には影響しない                                                                      |
| Out of scope | platform バリアント / UI 統合 / emotion 別スタイル                                                                                          |

### Phase 1: Stage 6 backend 切替 (= 2 週間)

| 項目         | 内容                                                                                                                                                                                                  |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Goal         | `config.OVERLAY_BACKEND = "remotion"` で本番パイプラインを通す。出力 mp4 の見た目は ffmpeg と同等                                                                                                     |
| 変更点       | `staged_pipeline.run_overlay()` の `_apply_overlays(...)` 呼び出しを `_apply_overlays_dispatch()` に差し替え。backend は env / config で選択                                                          |
| テスト       | `tests/test_compositor_remotion.py` を新設。既存 `tests/test_compositor.py` のシナリオを Remotion backend でも通す (= snapshot 比較ではなく「字幕が指定秒に表示されているか」を ffprobe + OCR で検証) |
| 監視         | `data/cost_records.jsonl` に `remotion_render_sec` を計測して追加。ffmpeg より遅い場合の許容範囲を決める (= 現状 ffmpeg overlay は 60 秒前後)                                                         |
| ロールバック | `OVERLAY_BACKEND=ffmpeg` に戻すだけ。両 backend を当面並列維持                                                                                                                                        |

### Phase 2: Stage 6 UI プレビュー統合 (= 1 週間)

| 項目     | 内容                                                                                                                                                          |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Goal     | `StageOverlay.tsx` の `<video src="overlaid.mp4">` を Remotion `<Player>` に置き換え。手動チャンク編集が **リアルタイム** で反映される                        |
| 変更点   | フロントから `/api/projects/<TS>/render-plan` を叩いて render_plan.json を取得 → `<Player component={ScreenplayComposition} inputProps={plan} />` で再生      |
| 利点     | 「保存して焼き直し」ボタンの 60 秒待ちが消える。チャンクの time を変えた瞬間に字幕表示位置が動く                                                              |
| 注意     | `<Player>` は `<OffthreadVideo>` の代わりに `<Video>` を使う必要がある (= ブラウザ再生)。素材の URL は `/asset/<ts>/...` 経由 (= preview_server が既に配信中) |
| 副次効果 | 「保存して焼き直し」を押したときの最終出力が、UI で見ていたものと **完全一致** する (= drawtext と CSS の差がなくなる)                                        |

### Phase 3: platform バリアント生成 (= 2-3 週間)

| 項目                      | 内容                                                                                                                                                                                                                               |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Goal                      | Stage 8 公開時に platform 別の動画を自動生成                                                                                                                                                                                       |
| `templates/youtube.tsx`   | 末尾 2 秒に end card (= チャンネル登録 CTA)、字幕は控えめサイズ                                                                                                                                                                    |
| `templates/instagram.tsx` | 冒頭 1 秒「ホールド」 (= 静止画 + caption 大表示)、字幕は太字大きめ・中央寄せ                                                                                                                                                      |
| `templates/tiktok.tsx`    | 単語ごと karaoke ハイライト (= word-level timestamps が必要)、字幕位置を画面下 1/3 に                                                                                                                                              |
| 変更点                    | `routes/final_publish.py` で platform 指定時に `compose_video_remotion(template=platform)` を呼ぶ。出力先は `output/reels_<TS>__<platform>.mp4`                                                                                    |
| metadata 拡張             | `final_versions[]` に `template: "raw" \| "youtube" \| "instagram" \| "tiktok"` を追加。canonical を platform 単位で持つ                                                                                                           |
| 課金影響                  | **AI 課金ゼロ** (= 同じ素材を再合成するだけ)。Remotion レンダリング時間 × 3 platform 分の CPU 時間のみ                                                                                                                             |
| word-level timestamps     | TikTok の karaoke 用に必要。Stage 2 (TTS) で ElevenLabs から取得済の char-level timestamps を word boundary に丸めて `metadata.json.tts_alignment` に保存。Phase 3 開始前に `scene_gen.py` で alignment を保存する pre-task が必要 |

### Phase 4 (任意): アスペクト比バリアント

| 項目 | 内容                                                                                                                                                     |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Goal | 同じ素材から 9:16 / 1:1 / 16:9 を生成 (= YouTube 通常動画 / X 投稿に転用)                                                                                |
| 実装 | Composition の `width / height` を props で切替。`<OffthreadVideo style={{transform: "scale(...)"}}>` で被写体センター crop                              |
| 制約 | Kling 出力は 9:16 縦のみなので、横長転用時に画面端が欠ける。Phase 4 を本格化するなら Stage 4 (Kling) で別アスペクトも併走生成する設計が必要 (= 課金倍増) |
| 判断 | Phase 3 で十分な ROI が出てから検討。**初期スコープには含めない**                                                                                        |

---

## 5. 影響範囲 (= ファイル単位)

### 5.1 新規

| ファイル                                                           | 内容                                                                                        |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| `compositor_remotion.py`                                           | render_plan 組み立て + `npx remotion render` 起動。ffmpeg compositor と同じインターフェース |
| `frontend/remotion/Root.tsx`                                       | `registerRoot` で Composition を登録                                                        |
| `frontend/remotion/compositions/ScreenplayComposition.tsx`         | 親 Composition (= scenes を sequence)                                                       |
| `frontend/remotion/components/{Scene,Subtitles,SubtitleChunk}.tsx` | 子コンポーネント                                                                            |
| `frontend/remotion/templates/{base,youtube,instagram,tiktok}.tsx`  | platform 別テンプレ (Phase 3)                                                               |
| `frontend/remotion/schemas/renderPlan.ts`                          | Zod スキーマ                                                                                |
| `frontend/remotion/hooks/useSceneOffsets.ts`                       | offset 計算ヘルパ                                                                           |
| `tests/test_compositor_remotion.py`                                | backend テスト (= ffprobe + OCR で字幕検証)                                                 |
| `frontend/remotion/__tests__/Subtitles.test.tsx`                   | コンポーネント単体テスト                                                                    |
| `docs/plannings/2026-05-10_remotion-integration-design.md`         | 本ファイル                                                                                  |

### 5.2 修正

| ファイル                                          | 修正内容                                                                                                     |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `staged_pipeline.py:run_overlay`                  | `_apply_overlays(...)` を backend dispatch に差し替え                                                        |
| `config.py`                                       | `OVERLAY_BACKEND` (default `"ffmpeg"`), `REMOTION_CONCURRENCY` (default `4`) を追加                          |
| `frontend/src/components/stages/StageOverlay.tsx` | `<video>` を `<Player>` に置換 (Phase 2)。`useShellCtx().detail.render_plan` を新たに参照                    |
| `preview_server.py`                               | `GET /api/projects/<TS>/render-plan` endpoint 追加 (Phase 2)                                                 |
| `routes/final_publish.py`                         | `--platform` 引数で template 切替 (Phase 3)                                                                  |
| `final_import/core.py`                            | `final_versions[]` に `template` フィールド追加 (Phase 3)                                                    |
| `frontend/package.json`                           | `remotion`, `@remotion/player`, `@remotion/cli`, `zod` を追加                                                |
| `frontend/src/types.ts`                           | `RenderPlan` 型を export                                                                                     |
| `requirements.txt`                                | (変更なし — Remotion は Node 側依存のみ)                                                                     |
| `CLAUDE.md`                                       | Stage 6 のテーブルに「OVERLAY_BACKEND で remotion 切替可能」を追記、Stage 8 に platform バリアント説明を追加 |

### 5.3 削除なし

ffmpeg compositor (= `compositor.py`) は **当面残す**。理由:

- Remotion は Node + Chromium 依存が増えるため、CI 環境やトラブル時のフォールバックを維持したい
- `_resolve_subtitle_timings` / `_split_into_chunks` 等のロジックは backend 共通で再利用するため、`compositor.py` を消すと SSOT がなくなる

将来 Phase 3 が完了して半年運用しても問題なければ削除を再検討。

---

## 6. リスクとトレードオフ

### 6.1 技術リスク

| リスク                                                            | 影響  | 対策                                                                                                                                                                                                                       |
| ----------------------------------------------------------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Node + Chromium 依存追加**                                      | 中    | フォールバック (= ffmpeg backend) を残す。CI では `playwright install chromium` を pre-step に置く                                                                                                                         |
| **Remotion render が ffmpeg overlay より遅い**                    | 中    | 計測して許容範囲を決める。1.5x 程度なら許容。3x 以上なら `--concurrency` を上げる or Phase 1 を保留                                                                                                                        |
| **Composition の見た目が ffmpeg overlay と完全一致しない**        | 低-中 | フォントレンダリングは Chromium と libfreetype で差がある。Phase 0 で目視 diff を取り、許容できる差にとどまるか確認。違いが大きい場合は Remotion 側のフォント描画を ffmpeg と揃える設定 (= subpixel rendering 等) を試す   |
| **`<Video>` ブラウザ再生のフレーム精度**                          | 低    | Player の `<Video>` はブラウザの仕様上 frame-accurate ではない。プレビューと render 結果が微妙に違う可能性。`<OffthreadVideo>` は render 専用なので、Player では Video のまま受け入れる                                    |
| **scene_videos の実尺と Composition `durationInFrames` がずれる** | 中    | `_build_render_plan` 内で ffprobe 計測値を frame に変換して `durationInFrames` に詰める。fps ずれ (= scene\_<S>.mp4 が 30fps、Composition が 60fps) は ffmpeg merge と同じく `setsar=1,fps=60` を Composition 側で吸収する |
| **Phase 2 で `<Player>` のパフォーマンス**                        | 中    | 4 シーン以上の重いプロジェクトで重くなる可能性。`<OffthreadVideo>` 相当の最適化はブラウザでは効かないため、`<Video>` の `playsInline` + `preload="auto"` で凌ぐ                                                            |
| **TikTok karaoke 用 word-level timestamps の取得失敗**            | 中    | `metadata.json.tts_alignment` が無い TS では karaoke を無効化して通常字幕にフォールバック                                                                                                                                  |

### 6.2 運用リスク

| リスク                                                     | 対策                                                                                                                                                                                                                                            |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **複雑性の増加 (= 「字幕の SSOT が 2 箇所?」)**            | タイミング解決ロジック (= `_resolve_subtitle_timings` / `_split_into_chunks`) は backend 側に固定。Remotion 側は **解決済みの値を表示するだけ** という不変条件を厳守。レビュー時に「Remotion 側にロジックを書いていないか」をチェック項目にする |
| **CLAUDE.md「指示の範囲を超えない」原則からの逸脱誘惑**    | Remotion で「もうちょい派手にしようか」「シーンを足そうか」と Composition で勝手に演出を追加するのを禁止する。テンプレ追加は **設計 md にレビュー済の場合のみ**                                                                                 |
| **Phase 3 で platform バリアント増えると metadata 肥大化** | `final_versions[]` の上限を `MAX_FINAL_VERSIONS = 16` 等で設ける。古いバリアントは `is_canonical: false` のまま LRU 削除                                                                                                                        |
| **「これでなんでもできる」感による越権**                   | Remotion の用途は本ドキュメントの 1.1 (= 含むもの) に固定。実写素材編集 / 自動カット / 自動 B-roll は **別プロジェクト**としてスコープを切り直す                                                                                                |

### 6.3 採算性

| 項目                           | 影響                                                                                                                                                    |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **AI 課金 (Kling/Imagen/TTS)** | **不変** (= Remotion は AI 呼ばない)                                                                                                                    |
| **CPU 時間**                   | Remotion render が ffmpeg overlay の 1-2 倍。Phase 3 では platform 3 種で 3 倍                                                                          |
| **開発時間**                   | Phase 0-3 で計 5-7 週間 (= 主に platform テンプレ調整)                                                                                                  |
| **学習コスト**                 | Remotion 経験者がいないため、Phase 0 (= 1 週間) は学習に充てる必要あり                                                                                  |
| **得られる価値**               | 1) 字幕表現の柔軟化 2) UI と最終出力の見た目一致 3) platform 別バリアントの自動生成 — **3) が最大の ROI** (= 各 platform の CTR / 完遂率を最適化できる) |

---

## 7. テスト戦略

### 7.1 backend (= `compositor_remotion.py`)

| 観点                   | テスト                                                                                                                                                        |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| render_plan の組み立て | `test_build_render_plan_with_manual_chunks` — 既存 `_resolve_subtitle_timings` を経由していること、anchor の競合警告が伝播すること                            |
| scene 実尺の解決       | `test_render_plan_uses_real_scene_durations` — scene\_<S>.mp4 が想定 duration より長い場合、render_plan の `duration_sec` が実測値になること                  |
| backend dispatch       | `test_overlay_backend_dispatch_remotion` — `OVERLAY_BACKEND=remotion` で Remotion CLI が呼ばれ、`OVERLAY_BACKEND=ffmpeg` で従来経路が呼ばれる                 |
| 出力 mp4 の検証        | `test_remotion_overlay_smoke` — 既存 1 TS で render を回し、ffprobe で `width/height/fps/duration` が想定通りであること。字幕の OCR は Phase 1 終盤に追加検討 |

### 7.2 frontend (= Composition)

| 観点                         | テスト                                                                                                                                           |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `<Subtitles>` の表示         | `Subtitles.test.tsx` — given chunks の (start, end) で適切な frame に表示されること (= `@testing-library/react` + Remotion testing utilities)    |
| emotion 別カラー             | `SubtitleChunk.test.tsx` — emotion="焦り" のとき正しい color class が当たる                                                                      |
| template 切替                | `templates/youtube.test.tsx` — end card frame が末尾 120 frames に存在すること                                                                   |
| `<Player>` UI 統合 (Phase 2) | `StageOverlay.test.tsx` の追加ケース — render_plan を変更すると `<Player>` の見た目がリアルタイムで変わること (= `await screen.findByText(...)`) |

### 7.3 統合 (= e2e)

`tests/test_pipeline_e2e_remotion.py`:

- 既存の dummy screenplay + dummy scene_videos で `OVERLAY_BACKEND=remotion` のフルラン
- `output/reels_<TS>.mp4` が生成され、ffprobe で 30 秒以内・60fps・1080x1920 であること
- ffmpeg backend と Remotion backend の出力 mp4 を `ffmpeg -i ... -filter_complex psnr` で比較し、PSNR が 30dB 以上 (= 目視で見分けつかないレベル) であること

---

## 8. 開く議論 (= 設計レビュー時の論点)

1. **`OVERLAY_BACKEND` の切替単位は project ごと? グローバル?**
   - 案 A: グローバル (= `config.OVERLAY_BACKEND`)。シンプル
   - 案 B: project ごと (= `metadata.json.overlay_backend`)。A/B 比較しやすい
   - **推奨**: 案 A で開始、Phase 1 完了時に必要なら案 B に拡張

2. **Phase 3 で platform バリアントを生成するタイミング**
   - 案 A: Stage 6 完了時に **3 platform 同時生成** (= 公開時に選ぶだけ)
   - 案 B: Stage 8 公開時に **指定 platform のみ生成** (= 必要分だけレンダリング)
   - **推奨**: 案 B で開始。CPU 時間を節約 + 「使わない platform」のレンダを避ける

3. **Remotion `<Player>` の preview と最終 render の差をどこまで許容するか**
   - フォント描画差 / フレーム精度差は仕様上ゼロにできない
   - **推奨**: Phase 2 開始時に「許容差」を文章化 (= 「字幕の縦位置は ±2px、表示タイミングは ±1 frame まで許容」)

4. **CLAUDE.md「指示の範囲を超えない」と Remotion テンプレの関係**
   - YouTube テンプレで end card を勝手に足すのは「指示の範囲を超える」では?
   - **推奨**: end card のテキストは screenplay JSON に `end_card_text` フィールドで明示してもらう (= 人間が決める)。テンプレは描画方法だけを規定する

5. **Remotion を入れたら frontend (= preview_server に統合された UI) と Remotion 側の重複コードがどれくらい出るか**
   - 字幕の見た目を Player と最終 render で揃えるなら CSS は完全共通化したい
   - **推奨**: Phase 2 で `frontend/src/components/stages/StageOverlay.tsx` のプレビュー DOM を **削除し**、Remotion `<Player>` 経由に一本化する。重複しないようにする

---

## 9. 完了条件 (= ゴール状態)

このプランの全 Phase が完了した時点で:

- ✅ `config.OVERLAY_BACKEND = "remotion"` で本番パイプラインがフルラン (Stage 6 のみ Remotion)
- ✅ `StageOverlay.tsx` で手動チャンク編集がリアルタイム反映 (= 焼き直し待ちなし)
- ✅ `python3 main.py --resume <TS> --publish youtube` で YouTube 用 mp4 が自動生成
- ✅ 同様に `--publish instagram` / `--publish tiktok` で platform 別 mp4 が生成
- ✅ AI 課金は変動なし (= Kling / Imagen / TTS / Sync.so の呼び出し回数は不変)
- ✅ `compositor.py` の ffmpeg backend も保持 (= フォールバック可能)
- ✅ `data/cost_records.jsonl` に `remotion_render_sec` が記録され、ffmpeg backend の 2x 以内に収まる
- ✅ ドキュメント (CLAUDE.md / architecture.md / coding-rules.md) が更新済み

---

## 10. 次アクション (= 着手するとしたら)

1. このプランをレビューして第 8 章の論点を解決
2. Phase 0 (= 1 週間) を着手するかの判断
3. Go なら `frontend/remotion/` を作って既存 1 TS で Hello World render
4. Phase 0 完了時に Phase 1 の go/no-go を再判断 (= 学習コストと成果のバランス)

**ステータス**: 本ドキュメントは proposal。実装着手は未承認。
