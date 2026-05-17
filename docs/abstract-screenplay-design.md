# 抽象台本生成フェーズ — 設計ドキュメント

| 項目       | 値                                                                                                                                            |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| 最終更新   | 2026-05-17                                                                                                                                    |
| ステータス | **稼働中** (= line.speaker は resolved id 直書き方式。analyze が character catalog から alphabetical 順に割当て、Stage 1 UI で人間が訂正可能) |

---

## 0. 目的

参考動画から台本 JSON を生成する際、Claude Vision の出力を「**元動画クローン**」ではなく「**構成・セリフ・感情・ロケ選定だけ抽出した抽象台本**」に変える。analyze pipeline は構成・セリフ・感情に加えて `location_ref` / `camera_distance` を `locations/` カタログから自動選定し、各 `line.speaker` には `characters/` の resolved id (= `f1__office` 等) を直接書き込む (= 自由記述ビジュアルプロンプトは産出しない。casting はユーザが Stage 1 UI で訂正可能)。

さらに **Claude inference の直後に Gemini 2.5 Pro による rewrite phase** が走り、`line.text` + `caption` だけを **同じ意味・同じ感情で独自の言い回し** に書き換える (= 翻案権配慮、`docs/plannings/2026-05-17_gemini-dialogue-rewrite.md`)。これにより:

- 元動画の構図・体勢・casting に縛られず、自分のキャラ・世界観で動画を量産できる
- 登場人物を切り替えるだけで「同じ訴求の動画を別キャラで作る」が容易
- 元動画依存の bug (例: 「胸から下のクローズアップ」が全シーン引きずる) が構造的に解消
- `identity` (= clip_library の cache 鍵) が手動入力に依存せず、analyze 出力だけで常に揃う
- **元動画の発話をそのまま字起こしする問題** が構造的に解消される (= Gemini rewrite が言い回しを置換、構造とメタは保持)

---

## 1. 全体像

```
[1] 動画アップロード
       ↓
[2] analyze (Claude Vision + Whisper + librosa) → 抽象台本
   ・構成・セリフ・感情・話し方など「中身」を抽出
   ・各 line.speaker には character catalog の resolved id (= f1, m1__suit 等)
     を alphabetical 順に直書き
   ・location_ref / camera_distance を locations/ カタログから自動選定
   ・annotation (visual_intent_id 等) を Claude 推論で付与
   ・自由記述ビジュアルプロンプトは生成しない
       ↓
[2b] Gemini 2.5 Pro rewrite (= line.text + caption を翻案権配慮で書き換え)
       ↓
[3] create-project (= 抽象台本を template から temp/<TS>/screenplay.json へ snapshot)
       ↓
[4] Stage 1「台本」ページの編集セクション
   ・caption / lines 編集 (= 各 line.speaker は SpeakerPicker で訂正可能)
   ・featured_characters は analyze の casting 提案が初期値
   ・completeness バナーで未解決の不整合を可視化
   ・identity / annotation / location_ref / camera_distance は analyze が
     SSOT として産出するため Stage 1 UI に編集導線は無い
       ↓
[5] Stage 1 OK → 以降 Stage 2〜6 が compose 済み (= 派生フィールド焼き済み) を読む
```

ポイント:

- **VideoStyle テンプレは廃止**。シーン単位で per-scene フィールドを直接持つ
- **再合成エンドポイントは存在しない**。snapshot は常に abstract 形式で保存され、Stage 2 以降は読み出し時に毎回 compose を走らせる (live derivation)
- **identity / annotation は analyze が SSOT として常に産出する**。手動入力 UI / PATCH 経路は撤去済み (= `docs/plannings/2026-05-12_legacy-schema-removal.md`)
- **line.speaker は resolved id 直書き**。`speaker_to_ref` mapping は撤廃済み (= `docs/plannings/2026-05-17_drop-speaker-mapping-schema.md` #209)

---

## 2. 抽象台本のスキーマ

`screenplays/auto_<sha>.json` (= analyze 出力 / template) と `temp/<TS>/screenplay.json` (= project snapshot) の両方で同じ形式。

```jsonc
{
  "caption": "SNS 投稿用本文 (\\n で改行可、ハッシュタグ含む)",
  "featured_characters": ["f1", "m1__suit"], // 動画全体の登場人物
  "scenes": [
    {
      "duration": 5.0, // optional (Stage 2 が上書き)
      "location_ref": "home_office", // analyze が locations/ カタログから選定
      "camera_distance": "medium-close", // analyze が選定 (close-up|medium-close|medium|wide)
      "animation_style": "subtle", // subtle | standard | expressive
      "character_selection": ["f1"], // optional / [] = 0 人 (背景のみ)
      "annotation": {
        // optional / Layer 1 (Clip Library) cache lookup 用。analyze が常時
        // best-effort で付与する (= 低 confidence でも残す。catalog 外の id /
        // enum 外の値は当該 field のみ null に降格)。
        "visual_intent_id": "talking_head_calm", // visual_intents.yaml の id か null
        "duration_bucket": 5, // 5 / 10 (= visual_intents の duration_buckets と整合)
        "motion_intensity": "low", // low | medium | high
      },
      "lines": [
        {
          "text": "やばいやばい",
          "start": 0.0,
          "end": 1.0,
          "speaker": "f1", // resolved id 直書き (analyze が割当、UI で訂正可能)
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

`scenes[].annotation` は Clip Library の cache lookup key 用。`identity`
(= `character_refs` / `location_ref` / `start_emotion` / `camera_distance` の
nested dict) は compose が **常に派生する**。`location_ref` / `start_emotion`
が欠ければ `_derive_identity` が `ValueError` で fail-fast する (= analyze が
SSOT として必ず産出する責務を負う)。`character_refs` は空でも許容 (= 背景のみ
シーン)。identity + annotation を組合せて、同 identity + 同 intent の scene が
2 回目以降 AI 課金 0 で hit する設計。`visual_intent_id` が null の scene は
cold path (= 通常の Imagen + Kling 生成) に流れ、catalog 拡張のヒントとして
SSE event の `novel_intent_candidates` に出力される。

---

## 3. フィールド分類

### A. 抽象台本に **常に書かれる** (Claude / UI 由来)

| #   | フィールド                    | 階層  | 由来                                                                          |
| --- | ----------------------------- | ----- | ----------------------------------------------------------------------------- |
| 1   | `caption`                     | root  | Claude → Gemini rewrite → UI 編集                                             |
| 2   | `lines[].text`                | line  | Whisper transcript → Gemini rewrite                                           |
| 3   | `lines[].start` / `end`       | line  | Whisper word timestamp (analyze 時) → Stage 2 (TTS) が実音声長で上書き        |
| 4   | `lines[].emotion`             | line  | Claude 推論 → UI 編集                                                         |
| 5   | `lines[].delivery`            | line  | Claude 推論 → UI 編集                                                         |
| 6   | `lines[].acoustic`            | line  | librosa 抽出                                                                  |
| 7   | `lines[].pronunciation_hints` | line  | Claude 推論                                                                   |
| 8   | `lines[].speaker`             | line  | character catalog の resolved id を直書き (= alphabetical 順) → UI で訂正可能 |
| 9   | `scenes[].duration`           | scene | Stage 2 (TTS) が実音声長で上書き                                              |

### B. ユーザが Stage 1 で **確定する**

| #   | フィールド                     | 階層  | 既定                             |
| --- | ------------------------------ | ----- | -------------------------------- |
| 1   | `scenes[].animation_style`     | scene | "standard"                       |
| 2   | `scenes[].character_selection` | scene | 未指定 (= speakers から自動推論) |

### B'. analyze pipeline が **Claude 推論で書く** (= Layer 1 cache lookup / casting 提案)

`location_ref` / `camera_distance` は compose の `_derive_identity` が必須とするため
analyze が必ず産出する (= 欠落は fail-fast)。`annotation` および casting 系
(`featured_characters` / `lines[].speaker`) は best-effort で、validator は不在を
許容する。casting は **提案** であり、ユーザが Stage 1 UI で訂正する (= per-line
SpeakerPicker / 👥 登場人物セレクタ)。

| #   | フィールド                             | 階層  | 由来 / 既定                                                                                                                                        |
| --- | -------------------------------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `scenes[].location_ref`                | scene | Claude が `locations/` カタログから最近傍を選定。catalog 外 id は後処理で先頭に矯正                                                                |
| 2   | `scenes[].camera_distance`             | scene | Claude が close-up/medium-close/medium/wide から選定。enum 外は後処理で drop (= location 既定 fallback に委ねる)                                   |
| 3   | `scenes[].annotation.visual_intent_id` | scene | Claude 推論で `config/part_registry/visual_intents.yaml` の id を 1 つ選ぶ。catalog 外なら当該 field のみ null に降格                              |
| 4   | `scenes[].annotation.duration_bucket`  | scene | 5 / 10 のいずれか (= visual_intents の `duration_buckets` と整合)                                                                                  |
| 5   | `scenes[].annotation.motion_intensity` | scene | low / medium / high                                                                                                                                |
| 6   | `featured_characters`                  | root  | character catalog が提供されれば Claude が catalog の base から順番に割り当てて提案 (= 元動画の登場人物に寄せない)。catalog 外 ref は後処理で drop |
| 7   | `lines[].speaker`                      | line  | character catalog の base を alphabetical 順に各 line に直書き (= 2026-05-17 #209 から)。catalog 外 ref は後処理で drop。UI で人間が訂正可能       |

#### casting 後処理ルール (= post-processing で決定論的に適用)

Claude の提案には 2 つの判定ロジックが後処理で被さる。すべて graceful (= 適用不能なら何もしない)。**いずれも参考動画の登場人物に寄せるロジックは含まない** (= 2026-05-17 方針変更、`docs/plannings/2026-05-17_decouple-casting-from-reference.md` 参照)。

- **Rule B (distinct character)**: 同じ base character を複数 line.speaker に割り当てない (= 同じ base が複数 speaker で出ないように alphabetical 順で次の未使用 base に swap)
- **Rule A (wardrobe-by-location)**: 各 speaker の **dominant location** (= 最も多くの line を持つ scene の `location_ref`) の `recommended_wardrobes` に合うように wardrobe を swap する。同 base に該当 wardrobe バリアントが存在しないなら swap しない。`featured_characters` は swap 後の ref に同期される

`visual_intent_id` が null の scene は SSE event `novel_intent_candidates` に集計され、UI で「catalog 拡張のヒント」として表示される。`confidence` / `rationale` は Claude が出力しても compose 前の正規化で drop され snapshot には残らない。

### C. compose で **派生される** (= 保存しない)

| フィールド                   | 由来ロジック                                                                          |
| ---------------------------- | ------------------------------------------------------------------------------------- |
| `scenes[].background_prompt` | location 詳細 + camera_distance + characters から決定論的に生成                       |
| `scenes[].animation_prompt`  | emotion arc + animation_style から決定論的に生成 (英語)                               |
| `scenes[].characters[]`      | character_selection / line.speaker から推論された ref を `[{name: ref}]` に展開       |
| `scenes[].character_refs`    | 上と同じ ref のフラット配列                                                           |
| `scenes[].tags`              | abstract.scenes[].tags がコピーされる (デフォルト空)                                  |
| `scenes[].lipsync`           | 常に true (固定)                                                                      |
| `lines[].voice_overrides`    | line.speaker (= 直書き resolved ref) から `characters/<base>/voice.json` を引いて注入 |

---

## 4. ファイル配置 (template / snapshot 二層)

| 種別                 | パス                        | git 管理 | 役割                                                                                             |
| -------------------- | --------------------------- | -------- | ------------------------------------------------------------------------------------------------ |
| **template**         | `screenplays/<name>.json`   | 追跡     | 新規 project 作成の素材。現状は **analyze pipeline 出力** (= `auto_<sha>.json`) のみが生成される |
| **project snapshot** | `temp/<TS>/screenplay.json` | ignore   | project 作成時に template からコピー。以後すべての stage / UI 編集の **唯一の対象**              |

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

`additionalProperties: False` は両方で効く。`featured_characters` / `character_selection` を含む abstract 専用フィールドが正式に schema に表現されているので、両形式とも未知フィールド拒否を維持できる。

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

不正な `camera_distance` (= `_CAMERA_LABELS` に無い値) は warning log + `medium` にフォールバック。`line.speaker` が catalog 外 ref なら line から削除し warning log + `diagnose_abstract.unmapped_speakers` に集計する。

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
frames → audio → whisper → acoustic → claude → rewrite (Gemini) → save
```

- frames / audio / whisper / acoustic は content-addressed cache が効く (= 同じ動画の再分析は無料に近い)
- claude フェーズは **必ず** 呼ぶ (cache 無し)
- rewrite フェーズ (= Gemini 2.5 Pro) は line.text + caption を翻案権配慮で書き換える。失敗は graceful に Claude original を維持 (= analyze 全体は止めない)
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

analyze_job_id を持つプロジェクトでのみ表示される (= analyze 経由でない legacy template を選ぶと表示されず、Stage 1 は完全 screenplay の確認のみとなる)。構成:

```
[completeness バナー]
  ⚠️ N 件の未解決項目 (caption 空 / 登場人物未指定 / 未マッピング話者 /
                       人物 0 人シーン / 背景未設定 / 不正カメラ距離 /
                       未定義キャラ ref)
  または ✅ 抽象台本に未解決の不整合はありません

[📝 台本作成]
  ├ 🪄 全シーン一括適用 (動き)
  ├ caption (textarea)
  ├ 👥 登場人物 (= featured_characters のチェック。analyze 提案時は ✨ バッジ)
  └ シーンごとに:
       [シーン #N] [+ 下に追加] [× 削除]
       ├ シーン個別設定 (analyze pre-fill された値を表示、訂正可能。
       │   analyze 経由なら ✨ バッジを 1 つ):
       │   ├ 🏠 背景 (LocationPicker、locations/<id>.json から選択)
       │   ├ 🎥 距離 (close-up / medium-close / medium / wide)
       │   └ 🎬 動き (subtle / standard / expressive)
       ├ 登場人物セレクタ
       └ lines: ▲▼ 移動 / × 削除 / セリフ + 感情 + 🎤 SpeakerPicker (= line.speaker 訂正)
  └ + シーンを末尾に追加

[💾 台本作成を保存]   ← PUT /api/projects/<ts>/abstract

[📹 参考動画 + analyze ジョブ情報] (折りたたみ)
```

`location_ref` / `camera_distance` / `identity` / `annotation` は analyze が SSOT
として産出するため Stage 1 UI に編集導線は無い (= `LocationPicker` /
`CameraDistancePicker` / `IdentityEditor` / `AnnotationEditor` は撤去済み)。
**話者マッピング UI (= speaker_N → ref の dict 編集) は廃止済み** (= 2026-05-17 #209)。
代わりに per-line SpeakerPicker で line.speaker を直接訂正する。

保存後は `progress_store.revoke_all_approvals(ts_path)` で Stage 1〜6 の承認だけ解除し、生成済み assets は保持する。再 GET で diagnostics が更新される。

### bulk apply

`animation_style` を全シーンに一括適用する。17 シーンクリック地獄を回避するための UX 機能。シーン個別の値は上書きされる。

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
| `PATCH /api/projects/<ts>/lines/<s>/<l>`   | line 単位の field patch (= speaker / emotion / delivery 等)            |
| `PUT /api/projects/<ts>/screenplay`        | JSON 直接編集 (上級者向け折りたたみ)                                   |
| `GET /asset/reference-video/<sha>`         | 参考動画ストリーミング                                                 |

`PATCH /api/projects/<ts>/scenes/<s>` は **撤去済み**。scene 単位の identity 系
フィールド (location_ref / camera_distance 等) は analyze が SSOT として産出し、
手動 patch する経路は持たない (= `docs/plannings/2026-05-12_legacy-schema-removal.md`)。

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
| **rewrite phase**    | Claude inference 直後に走る Gemini 2.5 Pro による line.text / caption の言い換え (翻案権配慮)   |

---

## 12. 過去の設計案 (廃止済み)

参考までに、過去採用していた設計と廃止理由を残す:

| 案                                                                      | 廃止理由                                                                                                              |
| ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **VideoStyle テンプレ**                                                 | 「ロケ + キャラ + 衣装オプション」を 1 ファイルに束ねるとスイッチ単位が粗い。シーン単位で持たせるほうが柔軟           |
| **drafts/canonical 二層モデル**                                         | template ファイル共有による project 間の干渉が発生。snapshot 設計で解消                                               |
| **`POST /api/projects/<ts>/recompose`**                                 | live derivation で不要に。snapshot 上書き = 再合成と等価                                                              |
| **`scenes[].wardrobe_tag`**                                             | キャラ ID に焼き込み (`<base>__<wardrobe>`) する設計に統一                                                            |
| **`root.location_continuity`**                                          | グローバル `locations/<id>.json` から引く設計に変更                                                                   |
| **`root.subtitle_y_from_bottom`**                                       | Stage 6 (字幕焼き込み) で決定するため、台本作成段階の責務外                                                           |
| **`scenes[].emotion_cue_overrides`**                                    | ショート動画運用では細かい演出調整は不要。emotion から自動派生で十分                                                  |
| **`lines[].audio_tags` の手動 UI**                                      | バックエンドの emotion → audio_tags 自動補完を残してUI からは消した                                                   |
| **旧 flat schema (`scenes[].character_refs` 等を scene root に直書き)** | identity / annotation は nested dict のみ。clip_library / validator / downstream は nested only に統一 (2026-05-12)   |
| **identity / annotation の手動編集 UI**                                 | analyze が SSOT として常に産出するため `IdentityEditor` / `AnnotationEditor` / `SceneFieldEditor` を撤去 (2026-05-12) |
| **`location_ref` / `camera_distance` の Stage 1 手動注入**              | analyze が `locations/` カタログから自動選定する設計に変更 (2026-05-12)                                               |
| **`speaker_to_ref` / `speaker_profiles` mapping schema**                | line.speaker に resolved id を直書きする方式に統一。dead 抽象化を撤廃 (2026-05-17 #209)                               |
| **話者マッピング UI (= speaker_N → ref の dict 編集)**                  | line.speaker 直書き方式により不要 (= per-line SpeakerPicker に統一、2026-05-17 #209)                                  |
