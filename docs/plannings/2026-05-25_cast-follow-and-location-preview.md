# 登場人物変更への声の追従 + 背景プレビューピッカー 設計書

最終更新: 2026-05-25
ステータス: ドラフト (= レビュー待ち)

## 1. 背景と目的

### 現状の課題

1. **登場人物 (`featured_characters`) を変えても声が追従しない**
   - `featured_characters` (= FeaturedCharactersSection) と `line.speaker` (= SpeakerPicker)
     は `2026-05-17_drop-speaker-mapping-schema.md` で **別 SSOT に分離**された。
     依存は featured ← line.speaker の **片方向**で、featured を編集しても
     line.speaker は書き換わらない。
   - 例: featured を `f1` → `m3` に置換 (f1 削除) しても `line.speaker=f1` が残り、
     compose の `_resolve_line_speaker` で `f1` が featured に無い → `None` →
     TTS が config 既定 (= f1 の声) を使う。背景は featured fallback で m3 になる
     ため、**声 f1・背景 m3 のちぐはぐ + 「人物 0 人」警告**が出る。
   - 話者の一括置換自体は `SpeakerPicker.onBulkApply` (= 同 speaker の全 line を
     一括置換) で可能だが、**featured 編集とは別操作**で連動しない。

2. **背景選択が `<select>` ドロップダウン**で location id 文字列のみ。
   `locations/<id>.preview.png` があるのに見た目で選べない。

### 解決策

1. **featured の base 置換時に `line.speaker` を自動追従**させる (= 声が連動)。
   既存の `onBulkApply` (= 同 ref の全 line を置換) を featured 変更から発火する。
2. 背景選択を `preview.png` の **サムネ付きピッカー**にする。

### 今回のスコープ

やること:

- featured の base **置換** (= 削除 + 追加) を検出し、対象の `line.speaker` を
  新 base へ一括追従
- 背景プレビューピッカー (`LocationThumbPicker`)

やらないこと:

- **背景の featured 連動・一括設定** (= ユーザー要望により対象外。背景は登場
  人物と無関係で、`location_ref` は scene 個別のまま)
- **featured の単純追加 / 単純削除での line.speaker 変更** (= 1:1 置換のみ自動。
  下記「3.1 連動の範囲」参照)
- analyze デフォルト選択ロジックの変更 (= alphabetical casting は維持)
- `SpeakerPicker` per-line 編集の廃止 (= 残す。連動は上乗せ)
- 新規バックエンド API (= 既存の PUT abstract / preview 配信で足りる)

## 2. アーキテクチャ設計

### コンポーネント構成

```
frontend/src/components/stages/
  FeaturedCharactersSection.tsx ← onChange で「置換」を ScriptEditPanel に通知
  ScriptEditPanel.tsx           ← featured diff を検出し line.speaker を連動更新
  SpeakerPicker.tsx             ← 既存の onBulkApply ロジックを共有 (変更最小)
  LocationThumbPicker.tsx       ← 新規: 背景サムネのグリッド選択
  LocationPicker.tsx            ← LocationThumbPicker ベースに (callsite 不変)
```

### 依存関係

- 既存 API のみ (`/asset/location/<id>/preview`, `POST /api/locations/<id>/preview`,
  `GET /api/locations`, `PUT /api/projects/<ts>/abstract`)。新規なし。

## 3. 実装設計

### 3.1 featured → line.speaker 連動 (声の追従)

- **責務**: featured の変更前後を比較し、base が **1:1 で置換**された場合に、
  旧 base を使う全 `line.speaker` を新 base へ書き換える。
- **判定**: 旧 featured と新 featured の base 集合の差分を取る。
  - `removed = 旧 - 新`、`added = 新 - 旧`
  - `len(removed) == 1 and len(added) == 1` → **1:1 置換**とみなし、
    `removed[0]` を speaker に持つ全 line を `added[0]` に置換 (= 既存
    `onBulkApply(removed, added)` 相当)。
  - それ以外 (= 複数置換 / 追加のみ / 削除のみ) → **line.speaker は変更しない**
    (= 既存の per-line 編集 + 「人物 0 人」warning で人間が気付く)。
- **wardrobe の扱い**: featured は base 単位 (= 同 base の衣装入れ替え) なので、
  base が同一で wardrobe だけ変わった置換 (例: `f1__office` → `f1__casual`) は
  speaker の base が一致するため、resolved id の wardrobe も追従させる。
- 連動後は通常の保存 (`PUT abstract`) → 再 compose → TTS 生成時に新 speaker の
  `voice.json` が引かれる (= `2026-05-24` の TTS タイミング設計のまま、声が追従)。

### 3.2 LocationThumbPicker (背景プレビューピッカー)

- **責務**: location 一覧を `/asset/location/<id>/preview` のサムネカード
  グリッドで表示し、クリックで 1 つ選ばせる。
- **Props**: `locations: string[]` / `value: string | undefined` /
  `onChange(id: string | undefined)`。
- 各カード = サムネ + id ラベル + 選択ハイライト。preview 未生成は灰色
  プレースホルダ + 「🪄 生成」ボタン (= 既存 preview 生成 API)。`<img loading="lazy">`。
- 「(未設定)」選択肢も持つ。`LocationPicker` (per-scene) の中身をこれに差し替え
  (= 外部 callsite は不変)。

## 4. テスト方針

- **単体 (frontend)**: featured を 1:1 置換 (`f1`→`m3`) したとき、全 scene の
  `line.speaker=f1` が `m3` に書き換わること。複数置換 / 追加のみ / 削除のみでは
  line.speaker が変わらないこと。
- **レンダリング**: `LocationThumbPicker` が preview ありはサムネ、無しは生成
  ボタンを出すこと。
- **手動**: Stage 1 で featured を別キャラに置換 → 話者表示が追従し、「人物 0 人」
  警告が出ないこと (= 動画 / 背景 / TTS は再生成せず abstract 上で確認)。

## 5. 実装タスク

### Phase 1 (今回実装)

- [ ] 1. ScriptEditPanel に featured diff → line.speaker 連動ロジック (1:1 置換検出)
  - [ ] 1-1. `onBulkApply` を featured 変更からも呼べるよう配線
  - [ ] 1-2. 複数置換 / 追加のみ / 削除のみは no-op (= 既存 warning に委ねる)
- [ ] 2. `LocationThumbPicker.tsx` 新規 (サムネグリッド + 未生成プレースホルダ + 生成ボタン)
- [ ] 3. `LocationPicker.tsx` を `LocationThumbPicker` ベースに置換 (callsite 不変)
- [ ] 4. テスト (連動の単体 + LocationThumbPicker レンダリング)

### Phase 2 (将来)

- [ ] 複数 base 置換時の対応付け UI (= 確認ダイアログでマッピング)
- [ ] featured 単純削除時に残った line.speaker の扱い (= None 降格 or 明示警告)

## 6. リスクと対策

- **1:1 置換の誤検出**: 複数同時編集を 1:1 と誤認しないよう、diff が厳密に
  `removed 1 / added 1` のときだけ連動。それ以外は触らない (= 安全側)。
- **連動が個別調整を上書き**: 1:1 置換は「旧 base の全 line」を対象にするため、
  per-line で別話者に分けていたケースを潰し得る。複数話者シーンでは置換でなく
  per-line (`SpeakerPicker`) を使う運用とし、Phase 2 で確認ダイアログを検討。
- **preview 未生成 location**: プレースホルダ + 生成ボタンで段階対応。

## 7. 参考資料

- `docs/plannings/2026-05-17_drop-speaker-mapping-schema.md` — featured と
  line.speaker を別 SSOT に分離した経緯 (= 連動が無い根本理由)
- `docs/plannings/2026-05-17_decouple-casting-from-reference.md` — casting を
  参考動画に寄せない方針 (= デフォルトを変えない根拠)
- `CLAUDE.md` — featured_characters / line.speaker / location_ref のスキーマと
  TTS の voice 解決 (= 連動後に声が引かれる経路)
