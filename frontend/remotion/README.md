# Remotion (Composition Engine)

`docs/plannings/2026-05-10_compositional-architecture.md` の Layer 3 (Composition Engine)
実装ディレクトリ。

## 役割分担

- **Production Pipeline (= 既存)**: Stage 1-5 で Kling / Imagen / TTS / Sync.so を呼んで
  パーツ (= scene*<S>.mp4 / bg.png / tts*<S>\_<L>.mp3) を製造し、cache に蓄える
- **Composition Engine (= 本ディレクトリ)**: 既製パーツを組み立てて最終 mp4 を吐く。
  AI 生成は **行わない**

## ディレクトリ構造

```
remotion/
  index.ts                   ← registerRoot エントリ
  Root.tsx                   ← Composition 一覧の登録
  PartRegistry.ts            ← Layer 2 part dispatch table (= category × id → component)
  compositions/
    HelloWorld.tsx           ← Phase 0 minimum viable (= 1 シーン + 1 字幕)
    ScreenplayBase.tsx       ← Phase 2-A 本番 composition + Phase 4-C/F 拡張
                                (filter_preset wrap + intro/outro_card)
    (将来) ScreenplayYoutube.tsx, ScreenplayInstagram.tsx, ScreenplayTikTok.tsx
  components/
    PartRenderer.tsx         ← category + id を resolve して params を spread
    SceneSequence.tsx        ← 1 scene = camera_move-wrapped OffthreadVideo +
                                subtitle / sticker / lower_third Sequences
  parts/                     ← Phase 4 で 6 categories 実装済み
    subtitles/               ← minimal / fade_in / karaoke_bold      (Phase 2-A, 4-A)
    stickers/                ← exclaim_red / question_mark / sparkle / thumbs_up / fire (Phase 4-B)
    filter_presets/          ← none / warm_cinematic / cool_blue / monochrome / vintage (Phase 4-C)
    camera_moves/            ← none / subtle_zoom_in / ken_burns / dolly_pull_back (Phase 4-D)
    lower_thirds/            ← name_banner / role_caption / quote_box (Phase 4-E)
    title_cards/             ← simple_intro / subscribe_outro / section_break (Phase 4-F)
    (将来) transitions/, frame_layouts/, bgm/, sfx/
  schemas/
    renderPlan.ts            ← Layer 3 への入力 Zod スキーマ (= compositor_remotion.py が組立)
  __tests__/
    HelloWorld.test.ts                ← schema パース系の単体テスト
    PartRegistry.test.ts              ← dispatch + isKnownPart テスト (= 全 6 categories)
    ScreenplayBase.test.ts            ← RenderPlan schema パース
    part_registry_yaml_drift.test.ts  ← yaml ↔ component の id 集合一致
                                         (= 全 categories を自動 iterate)
```

各 part category の SSOT は `config/part_registry/<category>.yaml`。
yaml の `component` フィールドと `parts/<category>/index.ts` の export 名は
drift test で常に一致が enforce される (= 片方だけ更新する事故を防ぐ)。

## 開発コマンド

```bash
# Composition の一覧確認
npx remotion compositions

# Studio (= Remotion 公式の preview UI) を起動
npm run remotion:studio

# 単体 render (= Composition id + 出力パス + props)
npm run remotion:render -- HelloWorld out.mp4 \
  --props='{"videoSrc":"path/under/public.mp4","subtitleText":"テスト"}'
```

## 動画素材の配置 (= 重要)

Remotion `<OffthreadVideo>` は `http(s)://` URL または `staticFile()` 経由の
`public/` 相対パスのみ受け付ける。`file://` 絶対パスは reject される。

Phase 1 以降で `compositor_remotion.py` を作る際は、scene\_<S>.mp4 を以下のいずれかで
公開する必要がある:

1. `frontend/public/<TS>/scene_<S>.mp4` に **シンボリックリンク** (= 推奨、容量ゼロ)
2. preview_server の `/asset/<ts>/...` 経由で http URL 化 (= 既存ルートと整合)

`HelloWorld.tsx` では `videoSrc` が `http(s)://` で始まれば直接、それ以外は
`staticFile(videoSrc)` で `public/` 相対として解決する分岐を持つ。

## Phase 0 完了条件

- [x] `remotion`, `@remotion/cli`, `@remotion/player`, `@remotion/bundler`,
      `@remotion/renderer`, `zod` を frontend に追加
- [x] `index.ts` + `Root.tsx` で Hello World Composition が登録される
- [x] `npx remotion compositions` で 1 件表示される
- [x] 既存 scene\_<S>.mp4 を `public/` に置いて render が成功する (= 1080x1920 / 60fps / h264)
- [x] `npm run test:ci` で schema パースの単体テストが通る
- [x] `npm run build` で既存 vite build が壊れていないことを確認

## Phase 2-A 完了条件

- [x] `ScreenplayBase` Composition (= RenderPlan を props に取る)
- [x] `PartRenderer` で category + id ベースの dispatch
- [x] `parts/subtitles/MinimalSubtitle` で ffmpeg drawtext 相当の見た目
- [x] `parts/subtitles/index.ts` で id → component map
- [x] `PartRegistry.ts` で全 part カテゴリの統合 lookup
- [x] `config/part_registry/subtitle_styles.yaml` を 1 entry (= minimal) で開始
- [x] vitest で schema パース + part dispatch を単体テスト
- [x] 実 scene\_<S>.mp4 を `public/_smoke/` に置いて `--frames=0-N` 指定で render 成功

### 既知の制約 (Phase 2-B で解決)

`<Composition calculateMetadata={...}>` の動的 durationInFrames が
`--props` 経由で十分には伝播しない (= Composition の defaultProps の
`duration_frames` が使われる)。**Phase 2-B では `compositor_remotion.py` が
`--frames=0-{N-1}` を CLI に明示渡しすることで回避する**。

Phase 1 以降は `clip_library.py` (Python 側) と並行して進む。

## smoke test (= 手動検証手順)

```bash
# 1. 既存 TS の scene_000.mp4 を public/ にコピー
mkdir -p frontend/public/_smoke
cp temp/<TS>/scene_000.mp4 frontend/public/_smoke/scene.mp4

# 2. render
cd frontend
npx remotion render HelloWorld /tmp/hello.mp4 \
  --props='{"videoSrc":"_smoke/scene.mp4","subtitleText":"テスト字幕です","subtitleStart":0.5,"subtitleEnd":2.5}'

# 3. ffprobe で 1080x1920 / 60fps / h264 を確認
ffprobe -v quiet -print_format json -show_format -show_streams /tmp/hello.mp4

# 4. 後始末
rm -rf frontend/public/_smoke /tmp/hello.mp4
```

## Phase 完了状況 (= 2026-05-10 セッション末)

| Phase | 内容                                                                        | status |
| ----- | --------------------------------------------------------------------------- | ------ |
| 0     | Remotion セットアップ + HelloWorld                                            | ✅     |
| 1     | clip_library skeleton (= identity/annotation/provenance)                     | ✅     |
| 2-A   | ScreenplayBase + PartRenderer + MinimalSubtitle                              | ✅     |
| 2-B   | compositor_remotion + OVERLAY_BACKEND dispatch                               | ✅     |
| 3-A   | GET /api/projects/<TS>/render-plan endpoint                                  | ✅     |
| 3-B   | StageOverlay UI に Player を side-by-side 表示                                | ✅     |
| 3-C   | video preview を Player に完全移行                                           | ⬜     |
| 4-A   | subtitle_styles 拡充 (fade_in / karaoke_bold)                               | ✅     |
| 4-B   | stickers (= EmojiSticker × 5 preset)                                         | ✅     |
| 4-C   | filter_presets + global_parts wiring                                         | ✅     |
| 4-D   | camera_moves (subtle_zoom_in / ken_burns / dolly_pull_back)                  | ✅     |
| 4-E   | lower_thirds (name_banner / role_caption / quote_box)                        | ✅     |
| 4-F   | title_cards (simple_intro / subscribe_outro / section_break)                 | ✅     |
| 4-G   | transitions (= scene-to-scene cut / dip / slide)                             | ⬜     |
| 4-H   | frame_layouts (= split_horizontal / pip_corner)                              | ⬜     |
| 5     | Screenplay{Youtube,Instagram,TikTok} + bgm + sfx + outro_ctas                | ⬜     |
| 6     | analyze pipeline 統合 (novel intent 自動検出)                                | ⬜     |
| 7     | 旧 free-text 経路 deprecation                                                | ⬜     |

新カテゴリ追加の手順は `2026-05-10_compositional-architecture.md` §4.4 と
`config/part_registry/*.yaml` の既存 entry を参照。drift test (= part_registry_yaml_drift)
で yaml と component の id 集合の一致が常に強制される。
