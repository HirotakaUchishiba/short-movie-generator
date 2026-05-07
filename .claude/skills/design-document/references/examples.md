# 設計書の具体例

## 良い例 vs 悪い例

### 1. 関数・モジュールの設計

#### ✅ 良い例

```markdown
#### compose_screenplay.py

**パラメータ**:

- `abstract`: analyze pipeline 出力の抽象台本 (dict)
- `speaker_to_ref`: 匿名 speaker → 解決済み character ref の辞書
- `fallback_ref`: speaker 未指定 line に当てる ref

**責務**:

1. abstract.scenes[].lines[].speaker から resolved ref を解決
2. character_refs / featured_characters に注入
3. line.voice_overrides を speaker base voice.json から hydrate
4. 解決失敗 (= 未マップ) は Validation エラーで報告
```

**なぜ良いか**:

- パラメータと責務のみ記載
- 実装の詳細は書いていない
- 何をするかが明確

#### ❌ 悪い例

````markdown
#### compose_screenplay.py

```python
def compose_screenplay(abstract, speaker_to_ref, fallback_ref):
    sp = copy.deepcopy(abstract)
    for scene in sp.get("scenes", []):
        refs = []
        for line in scene.get("lines", []):
            speaker = line.get("speaker")
            if speaker in speaker_to_ref:
                line["speaker"] = speaker_to_ref[speaker]
                refs.append(speaker_to_ref[speaker])
            elif fallback_ref:
                line["speaker"] = fallback_ref
                refs.append(fallback_ref)
            else:
                raise ValidationError(...)
        scene["character_refs"] = list(set(refs))
    return sp
```
````

**なぜ悪いか**:

- 具体的な実装コードを書いている
- 設計段階で実装の詳細まで決めている
- 実装時の柔軟性がない

---

### 2. コンポーネントの設計

#### ✅ 良い例

```markdown
#### Stage 6 字幕プレビュー (StageOverlay.tsx)

**Props**:

- `screenplay`: project snapshot (= 抽象 + tts_meta hydrated)
- `tsPath`: project ディレクトリパス

**構成**:

- 上部: 字幕焼き込み済み overlay 動画プレイヤー
- 各 line を行で表示。subtitles[] 単位でチャンク編集可能
- 「⏱→start」「⏱→end」ボタンでプレイヤー currentTime をその場で snap
- 「auto に戻す」「自動に戻す」で chunk / line の手動 time を破棄

**プレビュー**:

- 開発時は `npm run dev` で `http://localhost:5173` から確認可能
```

**なぜ良いか**:

- Props と構成要素のみ記載
- UI 操作の意図 (= snap / auto に戻す) が簡潔に伝わる
- プレビュー方法も記載

#### ❌ 悪い例

````markdown
#### Stage 6 字幕プレビュー (StageOverlay.tsx)

```tsx
import { useState } from "react";
import { Player } from "./Player";

export const StageOverlay = ({ screenplay, tsPath }: Props) => {
  const [currentTime, setCurrentTime] = useState(0);
  // ... 200 行の実装 ...
};
```
````

**なぜ悪いか**:

- 実装コード全体を書いている
- import 文まで記載している
- 設計ではなく実装になっている

---

### 3. ハンドラ処理の設計

#### ✅ 良い例

```markdown
#### Stage 7 final_import ハンドラ

**処理フロー**:

1. 受け取りパス (= watchdog / HTTP / CLI のいずれか) から動画ファイルを `temp/<TS>/final/` にコピー
2. ffprobe で duration / size を取得して FinalVersion を組み立て
3. 音声指紋 (`compute_match_score`) で TTS 音声との類似度を計測
4. 閾値 (= `config.FINGERPRINT_THRESHOLD`) 未満は warning ログを出力 (= UI 警告 path)
5. metadata.json.final_versions[] に追記し is_canonical を立てる
6. 成功時: FinalVersion を返す
7. 失敗時: 例外を raise + cleanup
```

**なぜ良いか**:

- 処理の流れを箇条書きで説明
- 技術的な選択肢 (= ffprobe / fingerprint) を示唆
- 成功・失敗のパスを明記

#### ❌ 悪い例

````markdown
#### Stage 7 final_import ハンドラ

```python
def import_final(ts: str, src: Path, source: str = "http",
                 skip_fingerprint: bool = False) -> FinalVersion:
    ts_path = Path(config.TEMP_DIR) / ts
    if not ts_path.is_dir():
        raise FileNotFoundError(...)
    # ... 100 行の実装 ...
```
````

**なぜ悪いか**:

- 完全な実装コードを書いている
- エラーメッセージまで決めている
- 実装時の自由度がない

---

### 4. スコープの明確化

#### ✅ 良い例

```markdown
### 今回のスコープ

Stage 8 SNS 公開のうち YouTube Shorts のみを **Phase 1** として実装する。Instagram / TikTok の API upload は **Phase 2** とし、当面は半自動 (= caption をクリップボードへ + アプリ起動) のままにする。

1. **Phase 1: YouTube 完全自動**
   - OAuth refresh token ベースの resumable upload
   - analytics.posts への自動登録
   - quota 403 のハンドリング (= 翌日キューイング)

2. **検証環境**
   - `--privacy unlisted` 強制
   - `AUTO_LOOP_ALLOW_PUBLIC=0` env による二重 gate
```

**なぜ良いか**:

- 今回やることが明確
- やらないこと (= IG / TikTok の Graph API upload) も明記
- スコープが限定されている

#### ❌ 悪い例

```markdown
### 今回のスコープ

YouTube / Instagram / TikTok の SNS 公開を実装し、metrics 自動取得・dashboard・hook ランキングによる自動改善ロジックも含めて全部実装する。
```

**なぜ悪いか**:

- スコープが広すぎる
- すべてを一度に実装しようとしている
- 優先度が不明確

---

### 5. 技術選定の記述

#### ✅ 良い例 (技術が確定している場合)

```markdown
## 1. 背景と目的

### 解決策

**fal.ai Kling V3 Standard** で I2V アニメーションを生成し、9:16 縦長 1080p のシーン動画を全体スタイル統一して作成する。
```

**なぜ良いか**:

- 技術が確定している場合は比較表不要
- 簡潔に記述

#### ❌ 悪い例

```markdown
## 2. 技術選定

### 比較検討した選択肢

| 項目      | Kling V3  | Runway Gen-3 | Sora   |
| --------- | --------- | ------------ | ------ |
| 9:16 対応 | ◎         | ○            | ◎      |
| 単価      | $0.084/秒 | $0.12/秒     | 未公開 |
| ELO 順位  | 上位      | 上位         | TBD    |

### 選定結果

Kling V3 を採用
```

**なぜ悪いか**:

- すでに技術が確定しているのに比較表を作っている
- 不要な情報で設計書が長くなっている
- 実装に関係ない

---

## まとめ

### 設計書で書くべきこと

- **WHY** (なぜ): 背景、課題、解決策
- **WHAT** (何を): スコープ、コンポーネント構成
- **HOW** (どう): アプローチ、責務、処理フロー

### 設計書で書かないこと

- 具体的な実装コード
- 詳細なエラーメッセージ
- import 文
- 完全な型定義
- 実装の細部
