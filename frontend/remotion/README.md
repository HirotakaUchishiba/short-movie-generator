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
  compositions/
    HelloWorld.tsx           ← Phase 0 minimum viable (= 1 シーン + 1 字幕)
    (将来) ScreenplayBase.tsx, ScreenplayYoutube.tsx, ...
  components/                ← (Phase 2+ で追加) PartRenderer / SceneSequence / GlobalPartsLayer
  parts/                     ← (Phase 4+ で追加) subtitles / stickers / transitions / ...
  schemas/
    renderPlan.ts            ← Layer 3 への入力 Zod スキーマ (= compositor_remotion.py が組立)
  __tests__/
    HelloWorld.test.ts       ← schema パース系の単体テスト
```

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
