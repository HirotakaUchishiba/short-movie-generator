# 抽象台本生成フェーズ — 設計ドキュメント

| 項目       | 値                                                                       |
| ---------- | ------------------------------------------------------------------------ |
| 最終更新   | 2026-05-07                                                               |
| ステータス | **稼働中** (VideoStyle 廃止 + 二段検証 + Stage 1 統合 UI を含む現行設計) |

---

## 0. 目的

参考動画から台本 JSON を生成する際、Claude Vision の出力を「**元動画クローン**」ではなく「**構成・セリフ・感情だけ抽出した抽象台本**」に変え、ビジュアル要素はユーザーが Stage 1 UI で `location_ref` / `character_selection` / `animation_style` / `camera_distance` をシーン単位に注入する二段階構成にする。これにより:

- 元動画の構図・体勢・場所に縛られず、自分のキャラ・世界観で動画を量産できる
- ロケや登場人物を切り替えるだけで「同じ訴求の動画を別キャラ/別場所で作る」が容易
- 元動画依存の bug (例: 「胸から下のクローズアップ」が全シーン引きずる) が構造的に解消

---

## 1. 全体像

```
[1] 動画アップロード
       ↓
[2] analyze (Claude Vision + Whisper + librosa) → 抽象台本
   ・構成・セリフ・感情・話し方など「中身」だけ抽出
   ・匿名 speaker_1, speaker_2 で発話者を識別
   ・ビジュアル系フィールドは生成しない
       ↓
[3] create-project (= 抽象台本を template から temp/<TS>/screenplay.json へ snapshot)
       ↓
[4] Stage 1「台本」ページの編集セクション
   ・caption / lines 編集
   ・featured_characters + speaker_to_ref で誰が話すか確定
   ・各シーンに location_ref / character_selection / animation_style /
     camera_distance を設定 (bulk apply で一括も可)
   ・completeness バナーで未解決の不整合を可視化
       ↓
[5] Stage 1 OK → 以降 Stage 2〜6 が compose 済み (= 派生フィールド焼き済み) を読む
```

ポイント:

- **VideoStyle テンプレは廃止**。シーン単位で per-scene フィールドを直接持つ
- **再合成エンドポイントは存在しない**。snapshot は常に abstract 形式で保存され、Stage 2 以降は読み出し時に毎回 compose を走らせる (live derivation)

---

## 2. 抽象台本のスキーマ

`screenplays/auto_<sha>.json` (= analyze 出力 / template) と `temp/<TS>/screenplay.json` (= project snapshot) の両方で同じ形式。

```jsonc
{
  "caption": "SNS 投稿用本文 (\\n で改行可、ハッシュタグ含む)",
  "featured_characters": ["f1", "m1__suit"], // 動画全体の登場人物
  "speaker_to_ref": {
    // 匿名 speaker_N → ref
    "speaker_1": "f1",
    "speaker_2": "m1__suit",
  },
  "scenes": [
    {
      "duration": 5.0, // optional (Stage 2 が上書き)
      "location_ref": "home_office", // locations/<id>.json の キー
      "camera_distance": "medium-close", // optional (ロケのデフォを上書き)
      "animation_style": "subtle", // subtle | standard | expressive
      "character_selection": ["f1"], // optional / [] = 0 人 (背景のみ)
      "lines": [
        {
          "text": "やばいやばい",
          "start": 0.0,
          "end": 1.0,
          "speaker": "speaker_1", // raw 匿名 ID か ref
          "emotion": "焦り",
          "delivery": "早口で小声",
          "acoustic": { "pitch_trend": "rising", "rms_peak": 0.4, "wpm": 280 },
          "pronunciation_hints": { "IT": "アイティー" },
        },
      ],
    },
  ],
}
```

ビジュアル系派生フィールド (= `background_prompt`, `animation_prompt`, `character_refs`, `characters[]`, `tags`, `lipsync`, line.`voice_overrides`) は **保存しない**。`load_project_screenplay()` が読み出し時に compose で生成する。

---

## 3. フィールド分類

### A. 抽象台本に **常に書かれる** (Claude / UI 由来)

| #   | フィールド                    | 階層  | 由来                                                                   |
| --- | ----------------------------- | ----- | ---------------------------------------------------------------------- |
| 1   | `caption`                     | root  | Claude → UI 編集                                                       |
| 2   | `lines[].text`                | line  | Whisper transcript                                                     |
| 3   | `lines[].start` / `end`       | line  | Whisper word timestamp (analyze 時) → Stage 2 (TTS) が実音声長で上書き |
| 4   | `lines[].emotion`             | line  | Claude 推論 → UI 編集                                                  |
| 5   | `lines[].delivery`            | line  | Claude 推論 → UI 編集                                                  |
| 6   | `lines[].acoustic`            | line  | librosa 抽出                                                           |
| 7   | `lines[].pronunciation_hints` | line  | Claude 推論                                                            |
| 8   | `lines[].speaker`             | line  | Claude 推論 (`speaker_N`) → UI で ref に紐付け                         |
| 9   | `scenes[].duration`           | scene | Stage 2 (TTS) が実音声長で上書き                                       |

### B. ユーザが Stage 1 で **シーン別に確定する**

| #   | フィールド                     | 階層  | 既定                                    |
| --- | ------------------------------ | ----- | --------------------------------------- |
| 1   | `featured_characters`          | root  | 未指定 (= UI 必須入力)                  |
| 2   | `speaker_to_ref`               | root  | 未指定 (= multi-speaker のみ必須)       |
| 3   | `scenes[].location_ref`        | scene | 未指定 (= UI で 1 ロケを bulk apply 可) |
| 4   | `scenes[].camera_distance`     | scene | locations/<id>.json のデフォを継承      |
| 5   | `scenes[].animation_style`     | scene | "standard"                              |
| 6   | `scenes[].character_selection` | scene | 未指定 (= speakers から自動推論)        |

### C. compose で **派生される** (= 保存しない)

| フィールド                   | 由来ロジック                                                               |
| ---------------------------- | -------------------------------------------------------------------------- |
| `scenes[].background_prompt` | location 詳細 + camera_distance + characters から決定論的に生成            |
| `scenes[].animation_prompt`  | emotion arc + animation_style から決定論的に生成 (英語)                    |
| `scenes[].characters[]`      | character_selection / speaker から推論された ref を `[{name: ref}]` に展開 |
| `scenes[].character_refs`    | 上と同じ ref のフラット配列                                                |
| `scenes[].tags`              | abstract.scenes[].tags がコピーされる (デフォルト空)                       |
| `scenes[].lipsync`           | 常に true (固定)                                                           |
| `lines[].speaker`            | raw `speaker_N` を speaker_to_ref で resolve した ref に置換               |
| `lines[].voice_overrides`    | resolve 後の ref から `characters/<base>/voice.json` を引いて注入          |

---

## 4. ファイル配置 (template / snapshot 二層)

| 種別                 | パス                        | git 管理 | 役割                                                                                |
| -------------------- | --------------------------- | -------- | ----------------------------------------------------------------------------------- |
| **template**         | `screenplays/<name>.json`   | 追跡     | 新規 project 作成の素材。手書き / analyze 出力 / 任意のシード                       |
| **project snapshot** | `temp/<TS>/screenplay.json` | ignore   | project 作成時に template からコピー。以後すべての stage / UI 編集の **唯一の対象** |

`POST /api/projects` で template から snapshot にコピーされ、以後 template は触られない。template が外部で書き換わっても進行中 project は影響を受けない (= 別 project の analyze を回しても安全)。

### staged_pipeline の API

| 関数                                   | 対象             | 用途                                                  |
| -------------------------------------- | ---------------- | ----------------------------------------------------- |
| `load_template(name)`                  | template         | 新規 project 作成時のみ                               |
| `load_project_abstract(ts_path)`       | project snapshot | UI 編集対象 (= 抽象台本のまま読む)                    |
| `load_project_screenplay(ts_path)`     | project snapshot | Stage 2〜6 / UI から読む (= compose を毎回走らせる)   |
| `save_project_screenplay(ts_path, sp)` | project snapshot | 書き込みは全部これ。metadata.screenplay_sha256 も更新 |

---

## 5. 二段検証 (`screenplay_validator.py`)

abstract と composed の両方を **同じスキーマ** で表現するが、`background_prompt` の必須化だけは別チェックに分離する:

```python
validate_screenplay(sp)                              # = require_composed=True
validate_screenplay(sp, require_composed=False)      # abstract 形式 (PUT abstract / pipeline 出力)
validate_abstract(sp)                                # 上のショートカット
```

| 形式     | 通る場面                                                   | 必須項目                     |
| -------- | ---------------------------------------------------------- | ---------------------------- |
| abstract | snapshot 直書き / PUT abstract / analyze pipeline の保存前 | caption, scenes (>= 1)       |
| composed | Stage 2 直前 / scene_gen / compositor                      | + scenes[].background_prompt |

`additionalProperties: False` は両方で効くが、`featured_characters` / `speaker_to_ref` / `character_selection` を含む abstract 専用フィールドが正式に schema に表現されているので、両形式とも未知フィールド拒否を維持できる。

---

## 6. compose ロジック (`analyze/compose.py`)

```python
def compose_screenplay(abstract: dict) -> dict:
    """abstract 台本を composed screenplay に変換する (決定論的)。
    voice_overrides は characters/<id>/voice.json から、ロケ詳細は
    locations/<id>.json から、それぞれグローバルに引いて埋める。"""

def diagnose_abstract(abstract: dict) -> dict:
    """compose 直前の不整合を抽出 (UI 警告バナー用)。
    返り値: { unmapped_speakers, scenes_without_location,
              scenes_without_characters, invalid_camera_distance }"""
```

`_compose_background` は ロケ詳細 + camera_distance + characters から **1 文** を文字列連結で生成。Claude を呼ばないのでコストゼロ・キャッシュ可能・再現性が高い。`_compose_animation` は emotion arc + animation_style から英語で 1 文。

不正な `camera_distance` (= `_CAMERA_LABELS` に無い値) は warning log + `medium` にフォールバック。`speaker` が未解決なら line から削除し warning log + `diagnose_abstract.unmapped_speakers` に集計する。

---

## 7. キャラ entity / ロケ集 (グローバル SSOT)

```
characters/
  <base>/                   ← 被写体 ID (= 顔・体型・髪型が同じ人物)
    voice.json              ← voice メタ (base 単位、衣装で変わらない)
    base.png                ← 衣装サフィックス無しの参照画像
    <wardrobe>.png          ← `<base>__<wardrobe>` で参照される衣装バリアント
locations/
  <id>.json                 ← decor / lighting / color_palette / props /
                              camera_distance
  <id>.preview.png          ← LocationPicker のサムネ
```

screenplay の `featured_characters` / `character_selection` / `line.speaker` / `character_refs` には **解決済み ID** (= `<base>__<wardrobe>`、衣装無しなら `<base>` 単独) を入れる。

---

## 8. analyze pipeline (`analyze/pipeline.py`)

各フェーズ:

```
frames → audio → whisper → acoustic → claude → save
```

- frames / audio / whisper / acoustic は content-addressed cache が効く (= 同じ動画の再分析は無料に近い)
- claude フェーズは **必ず** 呼ぶ (cache 無し)
- save 時に `_normalize_scene_pronunciation_hints` で SYSTEM_PROMPT 違反 (= scene 直下の pronunciation_hints) を line に展開し、件数を `claude_drift` として `phase_complete` SSE と warning ログに出す

```python
{
  "phase": "save",
  "claude_drift": {
    "scene_pronunciation_hints_demoted": 0
  },
  "validation_warnings": 0
}
```

drift カウントが恒常的に 0 でない場合、SYSTEM_PROMPT / モデル選定 / 入力形式の見直しが必要。

---

## 9. Stage 1 UI (`frontend/src/components/stages/ScriptEditPanel.tsx`)

analyze_job_id を持つプロジェクトでのみ表示される (手書き台本は JSON 直接編集だけ)。構成:

```
[completeness バナー]
  ⚠️ N 件の未解決項目 (caption 空 / 登場人物未指定 / 未マッピング話者 /
                       背景未設定シーン / 人物 0 人シーン / 不正カメラ距離)
  または ✅ 抽象台本に未解決の不整合はありません

[📝 台本作成]
  ├ 🪄 全シーン一括適用 (背景 / カメラ距離 / 動き)
  ├ caption (textarea)
  ├ 👥 登場人物 (= featured_characters のチェック)
  ├ 🎙 話者マッピング (multi-speaker のときのみ)
  └ シーンごとに:
       [シーン #N] [+ 下に追加] [× 削除]
       ├ 背景 (LocationPicker)
       ├ カメラ距離 (close-up / medium-close / medium / wide)
       ├ 動き (subtle / standard / expressive)
       ├ 登場人物セレクタ
       └ lines: ▲▼ 移動 / × 削除 / セリフ + 感情 + 話者
  └ + シーンを末尾に追加

[💾 台本作成を保存]   ← PUT /api/projects/<ts>/abstract

[📹 参考動画 + analyze ジョブ情報] (折りたたみ)
```

保存後は `progress_store.revoke_all_approvals(ts_path)` で Stage 1〜6 の承認だけ解除し、生成済み assets は保持する。再 GET で diagnostics が更新される。

### bulk apply

`location_ref` / `camera_distance` / `animation_style` の 3 種を全シーンに一括適用する。17 シーンクリック地獄を回避するための UX 機能。シーン個別の値は上書きされる。

### scene 構造編集

各シーンに `+ 下に追加` / `× 削除` ボタン。削除は確認 dialog 経由。最後の 1 シーンは削除できない。`scenes[].duration` / `lines[].start` / `lines[].end` は Stage 2 (TTS) 実音声長から派生する SSOT なので Stage 1 UI では編集しない (= patch_line allowlist からも `start` / `end` を除外)。

線移動 (`▲▼`) は既存の `applySceneBoundaries` API 経由で line 単位 (= scene 境界の移動)。テキスト・順序は不変なので ElevenLabs 再課金なし。

---

## 10. バックエンド API

| Endpoint                                   | 用途                                                                   |
| ------------------------------------------ | ---------------------------------------------------------------------- |
| `POST /api/projects`                       | template から snapshot を作成                                          |
| `GET /api/projects/<ts>/abstract`          | snapshot を生のまま + diagnostics                                      |
| `PUT /api/projects/<ts>/abstract`          | snapshot を上書き保存 (validate_abstract で軽量検証) + Stage 1〜6 解除 |
| `POST /api/projects/<ts>/scene-boundaries` | line 単位の scene 境界変更 (TTS 再課金なし)                            |
| `PATCH /api/projects/<ts>/lines/<s>/<l>`   | line 単位の field patch                                                |
| `PATCH /api/projects/<ts>/scenes/<s>`      | scene 単位の field patch                                               |
| `PUT /api/projects/<ts>/screenplay`        | JSON 直接編集 (上級者向け折りたたみ)                                   |
| `GET /asset/reference-video/<sha>`         | 参考動画ストリーミング                                                 |

`POST /api/projects/<ts>/recompose` は **存在しない**。snapshot は常に abstract 形式で保存され、`load_project_screenplay()` が読み出し時に compose を走らせる live derivation 設計のため、明示的な再合成は不要。

---

## 11. 用語

| 用語                 | 定義                                                                                            |
| -------------------- | ----------------------------------------------------------------------------------------------- |
| **抽象台本**         | 元動画から構成・セリフ・感情・話し方のみ抽出した台本。ビジュアル要素は per-scene フィールド経由 |
| **完全 screenplay**  | 抽象台本に compose をかけて派生フィールド (background_prompt 等) が焼かれた状態                 |
| **template**         | `screenplays/<name>.json`。新規 project 作成の素材                                              |
| **project snapshot** | `temp/<TS>/screenplay.json`。project 専用の immutable abstract 台本                             |
| **live derivation**  | snapshot は abstract のまま、読み出し時に都度 compose を走らせる方式                            |
| **diagnostics**      | compose 直前の不整合を抽出した dict (UI completeness バナー用)                                  |
| **claude_drift**     | analyze pipeline で SYSTEM_PROMPT 違反を吸収した patch 件数のメトリクス                         |

---

## 12. 過去の設計案 (廃止済み)

参考までに、過去採用していた設計と廃止理由を残す:

| 案                                      | 廃止理由                                                                                                    |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| **VideoStyle テンプレ**                 | 「ロケ + キャラ + 衣装オプション」を 1 ファイルに束ねるとスイッチ単位が粗い。シーン単位で持たせるほうが柔軟 |
| **drafts/canonical 二層モデル**         | template ファイル共有による project 間の干渉が発生。snapshot 設計で解消                                     |
| **`POST /api/projects/<ts>/recompose`** | live derivation で不要に。snapshot 上書き = 再合成と等価                                                    |
| **`scenes[].wardrobe_tag`**             | キャラ ID に焼き込み (`<base>__<wardrobe>`) する設計に統一                                                  |
| **`root.location_continuity`**          | グローバル `locations/<id>.json` から引く設計に変更                                                         |
| **`root.subtitle_y_from_bottom`**       | Stage 6 (字幕焼き込み) で決定するため、台本作成段階の責務外                                                 |
| **`scenes[].emotion_cue_overrides`**    | ショート動画運用では細かい演出調整は不要。emotion から自動派生で十分                                        |
| **`lines[].audio_tags` の手動 UI**      | バックエンドの emotion → audio_tags 自動補完を残してUI からは消した                                         |
