# 効果音 (SE) タイムライン配置 UI 設計書

## 1. 背景と目的

### 現状の課題

- Stage se の配置 UI (`StageSE.tsx`) は **時刻を数値入力**するリスト形式。
- 動画のどこに音があり (発話・BGM)、SE がどの位置に乗り、長さがどれだけかが
  **可視化されていない**ため、CapCut 等の動画編集ツールに慣れたユーザには
  直感的でない。数値を勘で入れて焼いて確認する試行錯誤になっている。

### 解決策

- 波形 (音声) + 動画プレイヤー (映像) + SE 区間を **1 つのタイムラインに重ねて
  可視化**し、SE を「見ながら」配置・移動できる UI にする。
- 既存依存の **wavesurfer.js (v7、インストール済み・未使用)** を使う。

### スコープ (Phase 1)

やること:

- bgm_mixed.mp4 (= SE を載せる対象。TTS + 字幕 + BGM) の **波形**を表示。
- 同じ動画を **`<video>` プレイヤー**で再生し、波形の **再生ヘッド (playhead)** と同期。
- タイムライン上に **映像サムネイル列** (一定間隔のフレーム) を時間軸で並べる。
- SE を **矩形 region** で波形上に重ねる。**幅 = SE 音源の実 duration**、位置 = time。
- region を **ドラッグで時刻移動**。playhead 位置に **追加**、× で **削除**。
- **scene 境界 / 字幕**を薄いマーカーで重ね、配置の目安にする。
- 既存の「自動配置を生成」「保存」「焼き直し」「試聴」「音量」を踏襲。

やらないこと (Phase 2 以降):

- SE の **トリミング / ループ** (長さ変更。Phase 1 は固有長のまま配置)。
- 波形上での音量エンベロープ編集 (音量は数値 / スライダーのまま)。
- 複数トラック (レイヤー) 表示。

## 2. アーキテクチャ

### 全体構成

```
bgm_mixed.mp4 ──┬─ <video> (映像 + 音声再生)  ──┐
                │                               ├─ wavesurfer (media=video)
                └─ /se/waveform (peaks JSON) ───┘   ↑ playhead を映像と同期
                                                     │
metadata.se.items ── SE regions (start=time, end=time+duration) ── drag / add / del
screenplay scenes/lines ── scene 境界 + 字幕の参考マーカー (非編集)
```

- wavesurfer v7 の `media` に **既存の `<video>` 要素**を渡す。wavesurfer が再生・seek を
  制御し、映像と波形 playhead が一体で動く (= CapCut 風)。
- 波形は **backend が事前計算した peaks JSON** で描画する (mp4 を frontend で decode
  せず高速・確実。`audio_features.py` の RMS 抽出を転用)。
- SE は wavesurfer **Regions plugin** で矩形表示。region.start = time、
  region.end = time + se_duration。Phase 1 は **resize 無効** (固有長)、drag のみ。

### 波形ソースを bgm_mixed にする理由

SE が乗る直前の音 (TTS + 字幕 + BGM) を見て配置するのが自然。reels (SE 込み) だと
自分が今置いた SE も波形に出て編集中に不整合になる。overlaid (BGM 前) でも可だが、
BGM のリズムに合わせて SE を置きたいので bgm_mixed を採用 (無ければ overlaid に fallback)。

## 3. 実装設計

### 3.1 backend

#### (a) bgm_mixed.mp4 の配信ルート

`routes/assets.py` に `GET /asset/<ts>/bgm-mixed` を追加 (overlay と同型)。
bgm_mixed.mp4 が無ければ overlaid.mp4 にフォールバック (後方互換)。

#### (b) 波形 peaks API

`GET /api/projects/<ts>/se/waveform` を `routes/se.py` に追加。

- bgm_mixed.mp4 (無ければ overlaid) の音声を librosa で読み、RMS エンベロープを
  一定フレーム (~30-50ms) でサンプリング → 0-1 正規化した `peaks: number[]` と
  `duration: number` を返す。
- `audio_features.py` の RMS 計算を転用 (区間統計でなく全体エンベロープ版を足す)。
- 結果は `temp/<TS>/se_waveform.json` に cache (動画が変わらない限り再計算しない)。

#### (c) SE duration を list_se に付与

`se_library.list_se()` の各項目に `duration_sec` を追加 (`compositor._get_duration`
を ffprobe で流用)。region 幅計算に使う。catalog には書かず list_se が実ファイルから
動的算出する (catalog 汚染を避け、音源差し替えに自動追従)。

#### (d) 映像サムネイル列 API

`GET /api/projects/<ts>/se/thumbnails` を `routes/se.py` に追加。bgm_mixed (無ければ
overlaid) から ffmpeg で一定間隔 (既定 1s) の縮小フレーム (例 90x160) を
`temp/<TS>/se_thumbs/` に抽出し、`{interval_sec, count}` を返す (各フレームは
`/asset/<ts>/se-thumb/<idx>` で配信)。抽出済みなら再利用 (cache)。AI 課金は無い
(ローカル ffmpeg)。

### 3.2 frontend

#### (a) WaveformTimeline コンポーネント (新規)

`frontend/src/components/stages/se/WaveformTimeline.tsx`。

- props: 動画 asset URL、peaks、duration、items、tracks、scene 境界秒・字幕秒、
  onChange(items)、selectedIdx。
- wavesurfer v7 + Regions plugin + Timeline plugin を初期化。`media` に内部の
  `<video>` 要素を渡す。
- items → regions (start=time, end=time+duration, color=category 別)。
- region の `update-end` (drag 終了) → 対応 item の time を更新 → onChange。
- 「ここに SE 追加」ボタン → playhead 位置に新 region + 既定 se_id を items に追加。
- region クリック → selectedIdx 更新 (詳細パネルと連動)。
- scene 境界・字幕は **非編集の参考 region / marker** として薄色で重ねる。
- 波形の上に **映像サムネイル列**を同じ時間軸で並べる (thumbnails API のフレームを
  `<img>` 列で配置し、wavesurfer の幅・ズームと揃える)。

#### (b) StageSE 改修

`StageSE.tsx` をタイムライン中心に再構成。

- 上: WaveformTimeline (波形 + video + SE regions)。
- 下: 選択中 SE の詳細 (se_id 選択 / 音量 / reason 表示 / 削除) +「自動配置を生成」
  「配置を保存」「効果音をミックスして reels を焼く」。
- items の single source of truth は従来どおり `SeItem[]` state。タイムラインと
  詳細パネルは同じ state を編集する。bgm 未承認なら従来どおりゲート表示。

### 3.3 データモデル

`SeItem` (= {time, se_id, volume, source, reason}) は **変更なし**。duration は
表示専用で list_se から引く (item には保存しない = 音源差し替えで自動追従)。

## 4. テスト方針

- backend: waveform API (peaks 長さ・0-1 範囲・cache 再利用)、list_se の
  `duration_sec`、bgm-mixed 配信 (overlaid フォールバック)。
- frontend: items ⇄ regions 変換 (time/duration ↔ start/end)、drag で time 更新、
  追加・削除で items 更新を **純粋関数**に切り出してテスト (wavesurfer DOM 部分は除外)。

## 5. 実装タスク

### Phase 1

- [ ] backend: `/asset/<ts>/bgm-mixed` 配信 (overlaid フォールバック)
- [ ] backend: `/api/projects/<ts>/se/waveform` (RMS peaks + duration、cache)
- [ ] backend: `list_se` に `duration_sec` 付与 (ffprobe)
- [ ] backend: `/api/projects/<ts>/se/thumbnails` + `/asset/<ts>/se-thumb/<idx>` (ffmpeg フレーム抽出、cache)
- [ ] frontend: api (getSeWaveform / getSeThumbnails / bgmMixedAssetUrl) + 型 (SeTrack に duration_sec)
- [ ] frontend: items ⇄ regions 変換 + add/del/move を純粋関数に切り出し + テスト
- [ ] frontend: WaveformTimeline (wavesurfer v7 + regions + timeline + サムネ列, video 同期)
- [ ] frontend: StageSE 改修 (タイムライン + 詳細パネル)
- [ ] pytest / tsc

### Phase 2 以降

- [ ] SE トリミング / ループ (region resize → start/end を se item に拡張)
- [ ] 波形上の音量ハンドル

## 6. リスクと対策

- **mp4 音声の波形 decode**: frontend decode は重い/互換性問題 → backend peaks JSON
  で回避 (librosa)。
- **wavesurfer v7 の API**: v6 と異なる。v7 の `media` / `peaks` / Regions plugin を前提に実装。
- **大きい動画の波形**: peaks を ~30-50ms 粗さに間引き + cache で初回のみ計算。
- **scene 境界マーカーの基準ズレ**: 字幕と同じ `_scene_offsets_from_videos` (実尺累積)
  を使い、SE 配置 (絶対秒) と一致させる。
- **スコープ肥大**: trim・音量エンベロープは Phase 2 に分離し、Phase 1 は
  「波形 + 映像 (プレイヤー + サムネ列) + SE 区間の可視化と配置」に絞る。

```

```
