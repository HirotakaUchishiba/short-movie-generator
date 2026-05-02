# 抽象台本生成フェーズ — 設計ドキュメント

| 項目       | 値                          |
| ---------- | --------------------------- |
| 最終更新   | 2026-05-02                  |
| ステータス | **設計確定 / 実装未着手**   |
| 関連 PR    | なし (本ドキュメントが起点) |

---

## 0. 目的

参考動画から台本 JSON を生成する際、Claude Vision の出力を「**元動画クローン**」ではなく「**構成・セリフ・感情だけ抽出した抽象台本**」に変え、ビジュアル要素はユーザーが定義する **VideoStyle テンプレ** で後から差し込む二段階構成にする。これにより:

- 元動画の構図・体勢・場所に縛られず、自分のキャラ・世界観で動画を量産できる
- VideoStyle を切り替えるだけで「同じ訴求の動画を別のキャラ/場所で作る」が容易
- 元動画依存の bug (例: 「胸から下のクローズアップ」が全シーン引きずる) が構造的に解消

---

## 1. 背景: 何が問題だったか

現状の `analyze/pipeline.py` は Claude Vision に元動画フレームを渡して screenplay JSON を逆生成する。Claude は SYSTEM_PROMPT に従い、**元動画の見えたとおりの構図・服装・体勢・場所**を `background_prompt` / `animation_prompt` / `wardrobe` / `location` に書き込む。

実例 (2026-05-02 生成の `auto_72fb061...json`):

```json
"background_prompt": "白い壁を背景にダークブラウンの木製テーブルに向かって座る男性の胸から下のクローズアップ、両手をテーブル上で軽く構えている"
"animation_prompt": "The speaker leans slightly forward with both hands gesturing softly..."
```

→ 結果として **全 11 シーンが「同じ男性の胸から下のクローズアップ」固定**になる。Imagen / Kling はこの記述に忠実に画像/動画を生成するため、**元動画の構図しか作れない**。

---

## 2. 解決方針

**常に抽象化** + **抽象化要素を確定するフェーズ** の二段階に再構成する。モード切替ではなく**常に抽象化**するのがポイント (モード切替だと使い分けがブレる)。

```
[1] 動画アップロード
       ↓
[2] 動画分析 (Claude Vision) → 抽象台本
   ・構成・セリフ・感情・話し方など「中身」だけ抽出
   ・ビジュアル系フィールドは生成しない (空 or プレースホルダー)
       ↓
[3] ★抽象化要素決定フェーズ (新)
   ・VideoStyle 選択 (キャラ + ロケ + 衣装テンプレ)
   ・シーン別オーバーライド
   ・各 line の speaker / emotion / delivery を編集可
       ↓
[4] 合成 → 完全 screenplay (validator strict 通過)
       ↓
[5] Stage 1 (台本タブ) で確認 → Stage 2〜7
```

---

## 3. フィールド分類 (ユーザー判断 + 設計者注釈)

### A. 必要 / 抽象化が必要 (= UI で確定する)

抽象化 = 元動画から自動抽出するが、UI で編集可能にする。確定タイミング = **抽象化要素決定フェーズ**。

| #   | フィールド                              | 階層   | 確定方法                                             | 注釈                                                                              |
| --- | --------------------------------------- | ------ | ---------------------------------------------------- | --------------------------------------------------------------------------------- |
| 1   | `caption`                               | root   | UI 編集 (元動画案を初期値)                           | SNS 投稿用本文                                                                    |
| 2   | `lines[].speaker`                       | line   | `scene.characters[].name` から自動派生 + UI で訂正可 | 単一キャラなら省略                                                                |
| 3   | `lines[].emotion` / `emotion_intensity` | line   | Claude 推論 → UI 編集可                              | EMOTION_VOICE_PRESETS のキー                                                      |
| 4   | `lines[].delivery`                      | line   | Claude 推論 → UI 編集可                              | TTS チューニング用自然言語                                                        |
| 5   | `lines[].acoustic`                      | line   | librosa 抽出 → UI 編集可 (高度)                      | pitch_trend / rms_peak / wpm                                                      |
| 6   | `lines[].pronunciation_hints`           | line   | Claude 推論 → UI 編集可                              | 固有名詞・略語                                                                    |
| 7   | `scenes[].characters[]`                 | scene  | **VideoStyle から注入** + シーン別 override 可       | name + role                                                                       |
| 8   | キャラのバリエーション                  | (派生) | `characters/<name>.png` から選択                     | character_refs に反映                                                             |
| 9   | `scenes[].location_ref`                 | scene  | **VideoStyle から注入** + シーン別 override 可       | location_continuity のキー                                                        |
| 10  | `root.location_continuity[<id>]`        | root   | **VideoStyle から注入**                              | ★「胸から下のクローズアップ」を抽象化する正体。`camera_distance` フィールドが該当 |
| 11  | `scenes[].wardrobe.identifier`          | scene  | **VideoStyle から注入** + シーン別 override 可       | wardrobe_continuity のキー                                                        |
| 12  | `scenes[].tags`                         | scene  | **VideoStyle から注入** + シーン別 override 可       | preset 適用ルールと連動                                                           |

> ❌ `root.subtitle_y_from_bottom` は字幕焼き込み (Stage 7) で決定するため、**台本作成段階の決定対象から除外**(ユーザー指摘どおり)。

### B. 必要 / 抽象化不要 (= 自動派生 or 固定値)

| #   | フィールド                  | 階層  | 自動派生方法                                        | 注釈                                 |
| --- | --------------------------- | ----- | --------------------------------------------------- | ------------------------------------ |
| 1   | `scenes[].duration`         | scene | Claude が動画のシーン分割で算出                     | 構成情報                             |
| 2   | `lines[]` の数と並び        | scene | Claude が抽出                                       | 構成情報                             |
| 3   | `lines[].text`              | line  | Whisper transcript                                  | セリフ本文                           |
| 4   | `lines[].start` / `end`     | line  | Whisper word timestamp                              | タイミング                           |
| 5   | `scenes[].character_refs`   | scene | `scenes[].characters[].ref` から自動派生            | UI 編集不要                          |
| 6   | `scenes[].lipsync`          | scene | **常に true (固定)**                                |                                      |
| 7   | `root.scoped_augmentations` | root  | VideoStyle から注入                                 | preset 適用ルール                    |
| 8   | `lines[].rate`              | line  | `acoustic.wpm` から自動算出 (`config.WPM_BASELINE`) | デフォルトで OK、明示時のみ override |

### C. 削除対象 (= プロジェクトのどこにも要らない)

| #   | フィールド                              | 削除理由                                                                                           |
| --- | --------------------------------------- | -------------------------------------------------------------------------------------------------- |
| 1   | `scenes[].label`                        | "導入フック" 等の Claude 命名。動画内描画なし。auto_animation_prompt 廃止後は LLM 入力としても不要 |
| 2   | `root.audio_mode`                       | 常に voiced (silent モードは使わない)                                                              |
| 3   | `root.bgm_path`                         | BGM 機能不要                                                                                       |
| 4   | `root.bgm_volume_db`                    | BGM 機能不要                                                                                       |
| 5   | `lines[].silence_after_ms`              | TTS チューニング機能不要                                                                           |
| 6   | `scenes[].emotion_cue_overrides`        | (D2 への回答に基づき削除)                                                                          |
| 7   | `lines[].audio_tags` の **手動指定 UI** | (D3 への回答に基づき UI から削除。バックエンドの emotion → audio_tags 自動補完は残す)              |

---

## 4. 不明点・追加質問への回答

### D1. 主人公の数は複数定義する必要があるか?

**回答**:

- 「主人公」は単に **固定ナレーター 1 人** を指す呼称
- 複数定義が必要になるのは **対話形式の動画** (主人公 + 相手) を作る場合のみ
- ナレーター 1 人の動画なら `scene.characters[]` は常に 1 要素で十分:
  ```json
  [{ "name": "主人公", "role": "narrator", "ref": "female_engineer" }]
  ```
- 対話形式なら 2 要素以上:
  ```json
  [
    { "name": "主人公", "role": "narrator", "ref": "female_engineer" },
    { "name": "上司", "role": "boss", "ref": "male_boss" }
  ]
  ```

**設計上の落としどころ**: VideoStyle に `format: "narrator" | "dialogue"` を持たせ、

- `narrator` モード: 全シーン共通の 1 キャラのみ展開 (シンプル)
- `dialogue` モード: 複数キャラ展開可能、シーンによって登場キャラを subset 指定可

### D2. `scenes[].emotion_cue_overrides` は不要では?

**回答: 削除して OK**

- emotion_cue_overrides は emotion 由来の **視覚 cue (facial 表情 / lighting / camera 距離 / tone)** を preset ID で **シーン単位で上書き**する高度機能
- 通常運用: `emotion="焦り"` → `EMOTION_VISUAL_CUES` から自動的に `facial=alert_focused`, `lighting=warm_morning`, `camera=close_up` 等が派生
- emotion_cue_overrides を使うシーン: 「emotion は焦りだが、lighting だけは cool_blue にしたい」のような細かい演出調整
- → ショート動画の運用では細かいシーン別演出は不要。**削除候補に追加**
- 必要になったら再導入可 (`config.py` の `EMOTION_VISUAL_CUES` 仕組み自体は残す)

### D3. `lines[].audio_tags` はなぜ emotion と切り分けるのか?

**回答**:

- `emotion` = セリフ全体の **声色制御** (TTS の `stability` / `style` / `similarity_boost` に変換)
- `audio_tags` = ElevenLabs eleven_v3 の **インラインタグ** (例 `[laughs] そうだよね` → 笑い声を入れてからセリフ)
- 両者は独立した制御点なので別フィールドだが、**emotion から自動補完する仕組みが既に config.py に実装されている**:
  ```python
  EMOTION_AUDIO_TAGS_ENABLED = True
  EMOTION_AUDIO_TAGS: dict[str, list[str]] = {
      "驚き": ["[gasp]"],
      "喜び": ["[laughs]"],
      ...
  }
  ```

**設計上の落としどころ**: **「UI からは消す、バックエンドの自動補完は残す」**

- ユーザーは emotion を選ぶだけで OK (audio_tags は内部で自動補完)
- 細かく制御したい上級者向けに schema には残しておく (削除しない)
- → 削除対象 C 表の「手動指定 UI」のみ削除

---

## 5. VideoStyle データモデル

`video_styles/<name>.json` に保存する「動画スタイルテンプレ」。

```jsonc
// video_styles/my_engineer_office.json
{
  "name": "私のエンジニア女性 (オフィス)",
  "format": "narrator", // "narrator" | "dialogue"

  // キャラクター定義
  "characters": [
    {
      "name": "主人公",
      "role": "narrator",
      "ref": "female_engineer", // characters/female_engineer.png
      "voice_overrides": {
        "voice_id": "<ElevenLabs voice id>",
        "stability": 0.4,
        "style": 0.3,
        "similarity_boost": 0.7,
      },
    },
  ],

  // 衣装辞書
  "wardrobe_continuity": {
    "office_outfit": "グレーニット + 黒パンツ + 眼鏡 + ロングヘア",
  },
  "default_wardrobe": "office_outfit",

  // ロケーション辞書 (★ camera_distance がここで決まる = 「胸から下のクローズアップ」を抽象化)
  "location_continuity": {
    "home_office": {
      "decor": "ミニマル北欧風、ナチュラルウッドのデスク、観葉植物、白壁、奥にアートと窓",
      "lighting": "柔らかい自然光、暖色系",
      "color_palette": "白基調 + ベージュ + グリーン",
      "props": "シルバーの MacBook、白いマグカップ",
      "camera_distance": "medium", // close-up | medium-close | medium | wide
    },
  },
  "default_location": "home_office",

  // シーン分類タグの初期値 (scoped_augmentations と連動)
  "default_tags": ["home_office"],

  // 横断的な scope ベース演出ルール
  "scoped_augmentations": [
    {
      "scope": { "tag": "home_office" },
      "elements": ["plants_background", "natural_window_light"],
    },
  ],

  // animation_prompt 合成のスタイル
  "animation_style": "subtle", // subtle | standard | expressive
}
```

### scenes[] への自動展開ルール

| screenplay フィールド          | 派生ロジック                                                              |
| ------------------------------ | ------------------------------------------------------------------------- |
| `root.wardrobe_continuity`     | `style.wardrobe_continuity` をそのままコピー                              |
| `root.location_continuity`     | `style.location_continuity` をそのままコピー                              |
| `root.scoped_augmentations`    | `style.scoped_augmentations` をそのままコピー                             |
| `scenes[].characters[]`        | `style.characters` (narrator モード) or シーン別 subset (dialogue モード) |
| `scenes[].character_refs`      | `[c.ref for c in characters[]]` から自動派生                              |
| `scenes[].wardrobe.identifier` | `style.default_wardrobe` (シーン別 override 可)                           |
| `scenes[].location_ref`        | `style.default_location` (シーン別 override 可)                           |
| `scenes[].tags`                | `style.default_tags` (シーン別 override 可)                               |
| `scenes[].lipsync`             | 常に `true`                                                               |
| `lines[].voice_overrides`      | `speaker` を key に `style.characters[].voice_overrides` から自動引き当て |

---

## 6. 抽象化要素決定フェーズ UI

新規ステップとして AnalyzePage の後に挿入。

```
[アップロード] → [分析] → ★[VideoStyle 選択 + シーン別調整] → [合成] → [Stage 1〜7]
```

### UI 構成 (3 段)

#### 6.1 VideoStyle 選択 (上部)

```
┌─ Style ──────────────────────────────────────┐
│  ○ 私のエンジニア女性 (オフィス)               │
│  ○ 私のエンジニア男性 (カフェ)                 │
│  ○ + 新規 VideoStyle 作成                      │
└──────────────────────────────────────────────┘
```

#### 6.2 VideoStyle 編集 (中部、折りたたみ)

```
キャラ:  [主人公 (narrator)] [ref: female_engineer ▼]
         + キャラ追加 (dialogue モード時)

衣装:    [office_outfit] グレーニット + 黒パンツ + 眼鏡
         + 衣装追加

ロケ:    [home_office]
           decor:           ミニマル北欧風...
           lighting:        柔らかい自然光
           color_palette:   白基調 + ベージュ
           props:           MacBook
           camera_distance: [medium ▼]
         + ロケ追加

スタイル: animation_style [subtle ▼]
```

#### 6.3 シーン別オーバーライド (下部)

抽象台本の各シーンを並べて、シーンごとに wardrobe / location / tags を上書き可:

```
シーン 1 (5.0s · 2 セリフ)
  wardrobe : [default ▼]   location: [default ▼]
  ▶ セリフ詳細 (展開)

シーン 2 (4.3s · 1 セリフ)
  wardrobe : [office_outfit ▼]   location: [home_office ▼]
  ▶ セリフ詳細

[ 合成して台本を生成 ]
```

---

## 7. 合成ロジック (compose_screenplay)

```python
# analyze/compose.py (新規モジュール)

def compose_screenplay(abstract: dict, style: VideoStyle,
                        overrides: dict | None = None) -> dict:
    """抽象台本に VideoStyle を当てはめて完全 screenplay JSON を返す。

    overrides は {"scene_idx": {"wardrobe": "...", "location_ref": "..."}} の dict。
    """
    overrides = overrides or {}
    sp = {
        "caption": abstract["caption"],
        "wardrobe_continuity": style.wardrobe_continuity,
        "location_continuity": style.location_continuity,
        "scoped_augmentations": style.scoped_augmentations,
        "scenes": [],
    }
    voice_by_speaker = {c.name: c.voice_overrides for c in style.characters}

    for i, src in enumerate(abstract["scenes"]):
        sov = overrides.get(i, {})
        scene = {
            "duration": src["duration"],
            "characters": _resolve_characters(src, style),
            "character_refs": _resolve_refs(src, style),
            "wardrobe": {"identifier": sov.get("wardrobe", style.default_wardrobe)},
            "location_ref": sov.get("location_ref", style.default_location),
            "tags": sov.get("tags", style.default_tags),
            "lipsync": True,
            "lines": [
                _resolve_line(line, voice_by_speaker)
                for line in src["lines"]
            ],
        }
        scene["background_prompt"] = _compose_background(scene, src, style)
        scene["animation_prompt"] = _compose_animation(scene, src, style)
        sp["scenes"].append(scene)
    return sp


def _compose_background(scene, src_scene, style) -> str:
    """ロケ + 衣装 + シーン動作キーワードから 1 文を生成。"""
    loc = style.location_continuity[scene["location_ref"]]
    wardrobe_text = style.wardrobe_continuity[scene["wardrobe"]["identifier"]]
    chars = "、".join(c["name"] for c in scene["characters"])
    distance = loc["camera_distance"]
    return (
        f"{loc['decor']} で {distance} 距離で映る {chars}、"
        f"{wardrobe_text} を着用、{loc['lighting']}, single moment in time"
    )


def _compose_animation(scene, src_scene, style) -> str:
    """emotion arc + animation_style から英語の動きを生成。"""
    emotions = [l.get("emotion") for l in scene["lines"] if l.get("emotion")]
    arc = " → ".join(emotions) if emotions else "natural"
    style_modifier = {
        "subtle":     "with minimal hand movement, mostly facial expression",
        "standard":   "with natural hand gestures and body language",
        "expressive": "with energetic gestures and pronounced movement",
    }[style.animation_style]
    return f"subject speaks naturally following the emotion arc: {arc}, {style_modifier}"
```

`_compose_background` / `_compose_animation` は **ルールベースの決定論的合成**。再現性が高くキャッシュ可能。

> 別案: Claude Sonnet で自然言語生成も可能だが、コスト + ばらつきが出るため初期は決定論的が無難。

---

## 8. 実装フェーズ

| Phase                                    | 内容                                                                                                                                                                                          | 工数          |
| ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| **1. analyze 抽象化**                    | `analyze/pipeline.py` の SYSTEM_PROMPT を変更し、background_prompt / animation_prompt / wardrobe / location / characters を空にして抽象台本を出す                                             | 半日          |
| **2. VideoStyle データモデル**           | `video_styles/<name>.json` ディレクトリ + JSON schema + CRUD ヘルパー                                                                                                                         | 1 日          |
| **3. 合成ロジック**                      | `analyze/compose.py` (synthesize_screenplay + \_compose_background + \_compose_animation) + 単体テスト                                                                                        | 1 日          |
| **4. 抽象化要素決定フェーズ UI**         | 新ページ `/analyze/<job>/style` で VideoStyle 選択 + シーン別 override + 合成プレビュー → 「完全台本を生成」                                                                                  | 2 日          |
| **5. 削除対象フィールドの除去**          | label / audio_mode / bgm_path / bgm_volume_db / silence_after_ms / emotion_cue_overrides / 手動 audio_tags UI を削除 (validator schema + 既存台本 migration + バックエンド・フロント参照削除) | 1 日          |
| **6. 既存テスト更新 + ドキュメント整理** | テスト追加 + CLAUDE.md / README 整理                                                                                                                                                          | 1 日          |
| **合計**                                 |                                                                                                                                                                                               | **約 6.5 日** |

---

## 9. オープン課題への決定 (2026-05-02 確定)

| #   | 項目                               | 決定                                 | 備考                                                                                                                                    |
| --- | ---------------------------------- | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | VideoStyle 保存先                  | **`screenplays/styles/<name>.json`** | screenplays 配下にネスト (canonical / drafts と同階層感)                                                                                |
| 2   | デフォルト VideoStyle 数           | **3〜5 個**                          | office_engineer / cafe_barista / living_room_lifestyle / simple_background / outdoor_park                                               |
| 3   | 既存 screenplay の migration       | **ワンショット script**              | `scripts/migrate_screenplay_v3.py` で削除対象フィールド (label / audio*mode / bgm*\* / silence_after_ms / emotion_cue_overrides) を除去 |
| 4   | `_compose_background` 合成方式     | **決定論ルールベース**               | テンプレ + 動作キーワードを文字列連結で組み立て。Claude Sonnet 呼び出しは不採用 (コスト・ばらつき・遅延)                                |
| 5   | dialogue モードの speaker 推定精度 | **テスト動画で実測**                 | 主人公 + 上司の対話シーンを含む短尺動画で実分析 → speaker 取得精度を検証                                                                |

---

## 10. 用語定義

| 用語                       | 定義                                                                                         |
| -------------------------- | -------------------------------------------------------------------------------------------- |
| **抽象台本**               | 元動画から構成・セリフ・感情・話し方のみ抽出した台本。ビジュアル要素は空                     |
| **VideoStyle**             | キャラ + ロケ + 衣装 + voice + animation_style をひとまとめにしたユーザー定義テンプレ        |
| **完全 screenplay**        | 抽象台本 + VideoStyle を合成した、validator strict 通過レベルの screenplay JSON              |
| **抽象化要素決定フェーズ** | 抽象台本生成後、VideoStyle 選択 + シーン別 override で完全 screenplay を確定する UI ステップ |
| **合成ロジック**           | 抽象台本 + VideoStyle → 完全 screenplay を組み立てる関数群 (`analyze/compose.py`)            |

---

## 11. 関連ファイル (実装着手時の touchpoint)

| ファイル                                 | 変更内容                                                                                  |
| ---------------------------------------- | ----------------------------------------------------------------------------------------- |
| `analyze/pipeline.py`                    | SYSTEM_PROMPT 抽象化、ビジュアルフィールド空出し                                          |
| `analyze/compose.py`                     | (新規) 合成ロジック                                                                       |
| `analyze/job.py`                         | abstract_screenplay と final_screenplay の両方を保存できるよう拡張                        |
| `analyze/style.py`                       | (新規) VideoStyle CRUD                                                                    |
| `screenplay_validator.py`                | label / audio*mode / bgm*\* / silence_after_ms / emotion_cue_overrides を schema から削除 |
| `video_analyzer.py`                      | SYSTEM_PROMPT 全面書き換え (ビジュアル指示削除、抽象化指示追加)                           |
| `preview_server.py`                      | `POST /api/screenplay/analyze/<job>/style` (VideoStyle 適用) endpoint 追加                |
| `frontend/src/types.ts`                  | VideoStyle / AbstractScreenplay 型追加、削除フィールド除去                                |
| `frontend/src/pages/AnalyzePage.tsx`     | 抽象化要素決定フェーズへの遷移追加                                                        |
| `frontend/src/pages/StyleEditorPage.tsx` | (新規) VideoStyle 選択 + 編集 + シーン別 override                                         |
| `screenplays/auto_*.json` (既存)         | migration script で削除対象フィールド除去                                                 |
