# クリップライブラリ アーキテクチャ 設計案

> **⚠️ SUPERSEDED**: 本 doc は厳密 hash 一致前提の cache 設計で、議論で identity/annotation 分離方式に進化した。
> 統合・最新版は **`2026-05-10_compositional-architecture.md`** を参照。

**date**: 2026-05-10 / **base branch**: `main` / **status**: superseded
**関連**: `2026-05-10_remotion-integration-design.md` (= 独立に進む。組合せで ROI 倍増)

本プロジェクトを **生成系 (= 自由記述プロンプトから AI が毎回新規生成)** から
**ライブラリ系 (= 視覚クリップ の enum 化された pool から決定論的に選択)** へ
段階的に転換する設計案。screenplay の per-line 情報がキャッシュ key に漏れている
現状の構造的欠陥を解消し、`(character, location, visual_intent, start_emotion)`
が一致する clip を **未来永劫 hit** させる。最終 state では per-screenplay の
課金は **TTS + Sync.so のみ** に縮退する。

---

## 0. ゴール

- **コスト**: 同条件のシーンを 2 回目以降は Imagen / Kling 課金 0
- **品質**: 1 intent あたり N 個の variant pool でランダム選択 (= 決定論的 seed) し、
  視聴者から見た映像の単調さを排除
- **汎用性**: enum が網羅的である限り、新規 screenplay は既存 clip の組合せで
  必ず表現できる (= CLAUDE.md「すべての台本に汎用的に対応」を **より強く** 満たす)
- **後方互換**: 現行の自由記述経路は graceful fallback として残し、
  新規 intent が必要になったら初回 generation 後に auto-promote で pool 入りさせる

---

## 1. 現状の構造的欠陥

### 1.1 cache key が per-line 情報を内包している

| キャッシュ                              | 現在の key 派生式                                                                                                                                                                | 漏れ要素                                                                                                  |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `bg_cache.py:115`                       | `sha256({"prompt": _build_background_prompt(scene, screenplay), "ref_shas": [...], "loc_sha": ..., "model": ...})`                                                               | `_build_background_prompt` が `lines[].emotion` を経由して `EMOTION_VISUAL_CUES` を注入                   |
| `kling_cache.py:81` (`build_cache_key`) | `sha256({"augmented_animation_prompt": _augment_animation_prompt(...), "kling_duration": ..., "bg_image_sha": ..., "model_id": ..., "aspect_ratio": ..., "cache_version": ...})` | `augmented_animation_prompt` が **emotion arc + audio_dynamics (= 各 line の wpm/pitch/rms)** を baked-in |

人間の目で同一に見える `(f1__office, home_office, talking_head_calm, 中立)` の
シーンでも、line が違えば key が変わって絶対に hit しない。**理論上の hit 上限から
大きく乖離している**。

### 1.2 1 intent あたり 1 take しか cache できない

現行構造では `cache/bg_images/<key>.png` が 1 ファイルで上書きされる。
「同じ key で 10 take 貯めて variant pool を作る」表現力が無い。

### 1.3 `animation_prompt` が free-text

`scenes[].animation_prompt` が自由記述の英文。同じ「talking head, calm」を意図して
書いても、句点 1 つの差で別 key になる。enum 化が必要。

---

## 2. ターゲット state

### 2.1 概念モデル

```
[screenplay.json]                                       ← 入力 (人間 / analyze pipeline)
   ↓ 各 scene について clip_key を派生
[clip_key = sha256(
    visual_intent_id + character_refs + location_ref +
    start_emotion + duration_bucket + clip_version
  )]
   ↓
[L1: visual clip pool lookup]
   ├─ hit (≥ 1 variant)  → 決定論的 seed で variant 選択 → bg.png + kling_clean.mp4 を copy
   └─ miss               → Imagen + Kling で初回生成 → clip pool に register
   ↓
[L2: audio clip lookup]                                 ← line 単位
   ├─ hit               → tts_<line>.mp3 を copy
   └─ miss              → ElevenLabs で生成 → clip pool に register
   ↓
[L3: per-screenplay 合成]                                ← Sync.so は per-screenplay 課金
   └─ Sync.so で kling_clean + tts → scene_<S>.mp4
   ↓
[Remotion で字幕合成 + platform variant render]
```

### 2.2 課金構造の変化

| Stage          | 現状 cold | 現状 warm       | 提案 cold (= 初回) | 提案 warm (= 2 回目以降) |
| -------------- | --------- | --------------- | ------------------ | ------------------------ |
| 2. TTS         | $         | $ (= L2 miss多) | $                  | $0 (= 同 line なら hit)  |
| 3. BG (Imagen) | $         | $ (= 漏れ)      | $                  | **$0**                   |
| 4. Kling       | $$$       | $$$ (= 漏れ)    | $$$                | **$0**                   |
| 5. Sync.so     | $$        | $$              | $$                 | $$ (= per-screenplay)    |
| 6. Overlay     | -         | -               | -                  | -                        |

**warm 時の per-screenplay 課金 = TTS (新セリフ分) + Sync.so のみ**

---

## 3. スキーマ変更

### 3.1 screenplay schema

`scenes[]` に **enum フィールド 3 つ** を追加し、自由記述の `animation_prompt` /
`background_prompt` は **graceful fallback 用 override** に降格する。

```json
{
  "scenes": [
    {
      "location_ref": "home_office",
      "visual_intent_id": "talking_head_calm",
      "start_emotion": "中立",
      "duration_bucket": 5,
      "character_refs": ["f1__office"],
      "characters": [{ "name": "f1__office" }],
      "lipsync": true,
      "lines": [
        {
          "text": "やばいやばい",
          "emotion": "焦り",
          "delivery": "早口で小声"
        }
      ],

      "_override_background_prompt": null,
      "_override_animation_prompt": null
    }
  ]
}
```

| 新フィールド                  | 型                          | 必須                         | 役割                                                                                  |
| ----------------------------- | --------------------------- | ---------------------------- | ------------------------------------------------------------------------------------- |
| `visual_intent_id`            | enum string                 | 必須 (override 指定時を除く) | clip_key の主軸                                                                       |
| `start_emotion`               | `EMOTION_AUDIO_TAGS` の key | 必須                         | scene 開始時のキャラ表情。bg.png と kling 開始フレームに反映                          |
| `duration_bucket`             | `5 \| 10`                   | 必須                         | Kling の離散尺。1 秒単位だと hit しないため離散化                                     |
| `_override_background_prompt` | string \| null              | 任意                         | clip pool に該当 intent が無い時の cold-cache fallback。指定すると clip_key を bypass |
| `_override_animation_prompt`  | string \| null              | 任意                         | 同上                                                                                  |

`background_prompt` / `animation_prompt` の **自由記述ルートは廃止しない** が、
新規 screenplay では override 経路でのみ使われる扱いになる (= 旧 screenplay の
互換も担保)。

### 3.2 clip 保存レイアウト

```
cache/clips/
  <clip_key>/
    meta.json                ← intent_id / chars / loc / start_emo / duration / variants[]
    v01/
      bg.png
      bg.json                ← Imagen 入力 + 生成日時 + 品質メタ
      kling_clean.mp4         ← lipsync 前の生映像
      kling.json              ← Kling 入力 + 生成日時
      preview.gif             ← UI 表示用 (任意、= 1fps スプライト)
    v02/
      ...
```

### 3.3 clip_key 派生式

```python
def compute_clip_key(scene: dict) -> str:
    parts = {
        "intent": scene["visual_intent_id"],
        "ref_shas": _ref_image_shas(scene["character_refs"]),
        "loc_sha": _location_sha(scene["location_ref"]),
        "start_emotion": scene["start_emotion"],
        "duration_bucket": int(scene["duration_bucket"]),
        "clip_version": config.CLIP_LIBRARY_VERSION,
    }
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
```

**重要不変条件**:

- `lines[*]`、`emotion arc`、`audio_dynamics`、line text に **依存しない**
- character / location の参照画像 sha が変わると key も変わる (= 衣装変更で適切に invalidate)
- `CLIP_LIBRARY_VERSION` を bump すると全 pool を再生成 (= 重大な品質変更時)

---

## 4. visual_intent vocabulary

### 4.1 命名規則

`<category>_<modifier>` の 2 階層 snake_case。category は 1 単語、modifier は 1-2 単語。

| category         | 説明                         | modifier 例                                          |
| ---------------- | ---------------------------- | ---------------------------------------------------- |
| `talking_head_*` | 立ち / 座位の喋り (= 顔中心) | `_calm` `_animated` `_listening` `_explaining`       |
| `reaction_*`     | リアクション (= 言葉なし)    | `_surprise` `_relief` `_concern` `_realization`      |
| `gesture_*`      | 身振り (= 喋りながら)        | `_pointing` `_nodding` `_thinking` `_count_fingers`  |
| `transition_*`   | 入退場 / 移動                | `_walk_in` `_sit_down` `_stand_up` `_lean_in`        |
| `action_*`       | 具体的動作                   | `_typing` `_drinking` `_phone_check` `_open_box`     |
| `cinematic_*`    | カメラ / 構図表現            | `_zoom_in_face` `_dolly_pull_back` `_wide_establish` |

最初は **30-50 intent** で開始し、運用しながら拡張する。網羅性より **粒度の一貫性**
を優先 (= 「talking_head_calm と sit_in_office は同じ粒度ではない」を排除)。

### 4.2 粒度ルール

1 intent = **Kling 1 クリップで完結する 1 動作** (= 5s か 10s)
複合動作 (= "rush to desk → open laptop → sigh relieved") は **scene を 3 つに分割** して
3 intent で表現する。これにより:

- enum 爆発を抑制 (= 組合せ爆発を回避)
- scene の transition が分かれているので Remotion 側で transition effect も柔軟になる
- 1 つの intent 失敗が全体に波及しない

### 4.3 catalog ファイル

`config/visual_intents.yaml` に enum を一元管理する SSOT を新設:

```yaml
version: 1
intents:
  - id: talking_head_calm
    category: talking_head
    description: "Subject stands or sits, faces camera, talks calmly. Minimal body motion."
    suggested_kling_prompt_template: |
      A {character} {pose_modifier} in {location_decor},
      {start_emotion_addon}, talking calmly to camera,
      subtle ambient motion, lipsync friendly,
      KLING_NEGATIVE_CONSTRAINT.
    duration_buckets: [5, 10]
    valid_start_emotions: [中立, 喜び, 満足, 困惑]
    pool_target_size: 10
    deprecated: false

  - id: reaction_surprise
    category: reaction
    description: "Subject reacts with surprise, eyes wide, slight gasp. No speech."
    suggested_kling_prompt_template: |
      A {character} in {location_decor},
      eyes widening in surprise, slight intake of breath,
      reaction shot, lipsync NOT used,
      KLING_NEGATIVE_CONSTRAINT.
    duration_buckets: [5]
    valid_start_emotions: [中立, 困惑]
    pool_target_size: 8
    deprecated: false
```

`description` は analyze pipeline (Claude) に渡されて intent 推定の判断材料になる。
`suggested_kling_prompt_template` は variant 生成スクリプトのテンプレ。

---

## 5. キャッシュカスケード

### 5.1 L1: visual clip (= bg + clean kling)

| 項目       | 内容                                                                                                                                                                  |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| key        | `compute_clip_key(scene)` (= §3.3)                                                                                                                                    |
| 保存先     | `cache/clips/<clip_key>/v<NN>/`                                                                                                                                       |
| variant 数 | `pool_target_size` (intent ごとに定義)                                                                                                                                |
| lookup     | `lookup_clip(scene) -> ClipPool` (= variants が空でない pool を返す。空なら None)                                                                                     |
| selection  | `select_variant(pool, ts, scene_idx) -> ClipVariant` (= 決定論的 seed)                                                                                                |
| miss 動作  | Imagen + Kling で 1 take 生成 → `register_variant(pool, take)` で v01 として登録 → 次回以降 hit。pool_target_size 未満の状態 = "warming up" として progress UI に表示 |

### 5.2 L2: audio clip (= TTS audio per line)

| 項目      | 内容                                                                                          |
| --------- | --------------------------------------------------------------------------------------------- |
| key       | `sha256(line.text + voice_id + voice_overrides + audio_tags + emotion + delivery + model_id)` |
| 保存先    | `cache/audio_clips/<key>.mp3` + `<key>.json` (= alignment 情報)                               |
| variant   | 1 (= TTS は決定論的 hash で十分。同じ入力なら同じ音声で問題ない)                              |
| lookup    | `lookup_audio_clip(line) -> Path \| None`                                                     |
| miss 動作 | ElevenLabs 呼出 → register。`alignment` (= char-level timestamps) も保存し L3 で使う          |

**注意**: 現状の Stage 2 は **screenplay-wide one-shot TTS** (= `generate_screenplay_tts_one_shot`)
なので、line 単位 cache に降ろすには **per-line TTS 経路** を新設する必要がある。
これは大きい変更で、副作用として line 間の音響的繋がり (= prosody 連続性) が
失われる懸念がある。**§9 開く議論** で扱う。

### 5.3 L3: per-screenplay 合成 (= scene\_<S>.mp4)

| 項目       | 内容                                                                    |
| ---------- | ----------------------------------------------------------------------- |
| キャッシュ | **しない** (= screenplay 固有の組合せ。scene\_<S>.mp4 は ts ごとに作る) |
| 入力       | L1 で選ばれた `kling_clean.mp4` + L2 で取得した `tts_<line>.mp3` 群     |
| 処理       | Sync.so でリップシンク合成 → `temp/<TS>/tmp/scene_<S>.mp4`              |
| 課金       | Sync.so のみ (常に発生)                                                 |

### 5.4 lookup アルゴリズム (擬似コード)

```python
def resolve_scene_visual(scene: dict, ts: str, scene_idx: int) -> ResolvedVisual:
    if scene.get("_override_animation_prompt"):
        return _generate_freetext_path(scene)  # 旧経路 fallback

    clip_key = compute_clip_key(scene)
    pool = lookup_clip_pool(clip_key)

    if pool is None or len(pool.variants) == 0:
        # cold path: 1 take 生成して pool 化
        variant = generate_clip_variant(scene, clip_key)
        register_variant(clip_key, variant)
        return ResolvedVisual(bg=variant.bg, kling=variant.kling, source="cold")

    if len(pool.variants) < pool.target_size:
        logger.info(
            "[clip-pool] %s warming up (%d/%d variants)",
            clip_key, len(pool.variants), pool.target_size,
        )

    variant = select_variant_deterministic(pool, ts, scene_idx)
    return ResolvedVisual(bg=variant.bg, kling=variant.kling, source="hit")


def select_variant_deterministic(pool: ClipPool, ts: str, scene_idx: int) -> ClipVariant:
    # 同じ screenplay の rebuild で同じ variant が選ばれることを保証。
    # ts は project ごとに変わるので異なる project では別 variant が選ばれる。
    seed = int(hashlib.sha256(f"{ts}|{scene_idx}".encode()).hexdigest(), 16)
    idx = seed % len(pool.variants)
    return pool.variants[idx]
```

---

## 6. Variant pool 管理

### 6.1 pool 成長スクリプト

```bash
python3 scripts/grow_clip_pool.py \
  --intent talking_head_calm \
  --char f1__office \
  --loc home_office \
  --start-emotion 中立 \
  --duration 5 \
  --variants 10 \
  --auto-approve   # quality gate を skip。デフォルトは UI 承認待ち
```

挙動:

1. clip_key を派生
2. 既存 variant 数を確認 (= `meta.json.variants`)
3. 不足分だけ Imagen + Kling を **連続 N 回** 呼ぶ (= seed を変えて多様性確保)
4. 各 variant を `cache/clips/<clip_key>/vNN/` に置き、`status: pending_review` で登録
5. UI / CLI で `approve` されたら `status: active` に昇格して lookup 対象に入る

### 6.2 決定論的 variant selection

`select_variant_deterministic(pool, ts, scene_idx)` は §5.4 の通り。
**同じ screenplay の再ビルドで同じ動画が出る** ことを担保するための設計。
これは Stage 6 の字幕修正等で何度も rebuild する運用と相性が良い。

A/B variant が欲しい場合は `_clip_variant_seed_offset` を screenplay に追加する経路で
対応 (= optional フィールド、別 doc で議論)。

### 6.3 quality gate

variant pool 入りには **承認** が必要。承認経路:

| 経路         | 用途                                                                                                      |
| ------------ | --------------------------------------------------------------------------------------------------------- |
| UI 承認      | Stage 4 の Kling 承認 UI を流用。「pool に register」ボタンを追加                                         |
| CLI 自動承認 | `--auto-approve` (= `grow_clip_pool.py` 専用、品質ガード簡略版で運用者の手作業節約)                       |
| auto promote | `progress_store.mark_approved("kling")` 時に「同 clip_key で他 variant が無いとき」だけ自動で pool に昇格 |

承認時の品質チェック (= 既存 `kling_cache._evaluate_quality` を流用):

- duration が `duration_bucket` の ±5% 以内
- KLING_NEGATIVE_CONSTRAINT 違反 (= 文字 / ロゴ / 解像度低下) が無い
- character_refs 一致度 (= 顔識別の sha 比較は将来。当面は目視承認)

### 6.4 pruning (storage 管理)

| 戦略               | 内容                                                                                                                  |
| ------------------ | --------------------------------------------------------------------------------------------------------------------- |
| LRU (variant 単位) | `meta.variants[].last_used_at` を更新。最大 storage 超過時に hit_count が低い variant から削除                        |
| TTL (= 任意)       | 12 ヶ月 access が無い clip pool は archive (= cold storage 移動)                                                      |
| 上限               | `config.CLIP_POOL_MAX_TOTAL_GB = 200` (= 既定)。超過時に LRU で 80% まで縮退                                          |
| invalidation       | character / location の参照画像 sha 変更で clip_key が変わるため、自動的に旧 pool が miss 化 (= 物理削除は別 cron で) |

---

## 7. Analyze pipeline 統合

### 7.1 intent 推定の責務追加

`scripts/analyze_video.py` の Claude prompt を拡張:

1. `config/visual_intents.yaml` の `id` + `description` 一覧を context として渡す
2. 各 scene について以下を推定して JSON で出力:
   - `visual_intent_id` (= 一覧から best match)
   - `start_emotion`
   - `duration_bucket` (= 5 / 10、Kling clip 長から推定)
   - `confidence: 0.0 - 1.0`
3. `confidence < 0.7` の場合は intent_id を `null` で返し、free-text fallback 経路を発動

### 7.2 catalog UI

`frontend/src/pages/IntentCatalog.tsx` を新設:

- 全 intent の一覧 + description + variant pool 状態 (= active / pending / count)
- 各 intent の preview gif サムネ (= variants の 1 つ)
- 「pool を成長させる」ボタン (= `grow_clip_pool.py` を裏で起動)
- 新規 intent 提案 UI (= `visual_intents.yaml` への PR を生成)

### 7.3 novel intent (= 未収録) フロー

screenplay に既存 enum に無い intent が必要になった場合:

```
Option A: free-text fallback (即座)
  scene._override_animation_prompt = "..." を書く
  → 旧 free-text 経路で生成 (cache 無し、毎回課金)

Option B: 新規 intent として登録 (中期)
  config/visual_intents.yaml に新 entry を提案 (= PR or UI)
  → 承認後 grow_clip_pool で初期 N variant を生成
  → 以後 hit 化
```

`scripts/analyze_video.py` で confidence < 0.7 の scene が複数出たら、
auto suggest として `analyze_<TS>.suggested_intents.json` に
「こういう intent を新設すると hit しそう」を提案させる (= 中期改善)。

---

## 8. 移行プラン

### Phase 5a: schema 拡張 (= 1 週間)

| 変更                                                                                                                           |
| ------------------------------------------------------------------------------------------------------------------------------ |
| `screenplay_validator.py`: `visual_intent_id` / `start_emotion` / `duration_bucket` のオプショナル受入                         |
| 旧 screenplay (= override 無し) は validator pass、新 screenplay (= intent 指定) も pass                                       |
| `config/visual_intents.yaml` を初期 5 intent (= talking_head_calm/animated, reaction_surprise/relief, gesture_pointing) で開始 |
| `config.CLIP_LIBRARY_VERSION = "v1"` を新設                                                                                    |

### Phase 5b: clip_key + lookup 実装 (= 2 週間)

| 変更                                                                                                                                  |
| ------------------------------------------------------------------------------------------------------------------------------------- |
| `clip_library.py` (新規): `compute_clip_key` / `lookup_clip_pool` / `register_variant` / `select_variant_deterministic`               |
| `scene_gen.py`: `_resolve_scene_visual` を新設し、scene が `visual_intent_id` を持つ場合は clip_library 経路、無ければ free-text 経路 |
| `bg_cache.py` / `kling_cache.py`: 旧 cache はそのまま残す (= override 経路で利用)                                                     |
| migration: 既存 5 intent について `grow_clip_pool.py --variants 10` を実行して初期 pool 構築                                          |

### Phase 5c: analyze pipeline 統合 (= 1 週間)

| 変更                                                                                          |
| --------------------------------------------------------------------------------------------- |
| `scripts/analyze_video.py` の Claude prompt に intent 一覧を注入                              |
| 出力 JSON に `visual_intent_id` / `start_emotion` / `duration_bucket` / `confidence` を含める |
| confidence 低時の override fallback を実装                                                    |

### Phase 5d: catalog UI + pool growth (= 1-2 週間)

| 変更                                                                                             |
| ------------------------------------------------------------------------------------------------ |
| `frontend/src/pages/IntentCatalog.tsx` (新規)                                                    |
| `routes/clip_pool.py` (新規): GET /api/clips / GET /api/clips/<key> / POST /api/clips/<key>/grow |
| Stage 4 (Kling) UI に「pool に register」ボタン追加                                              |
| `scripts/grow_clip_pool.py` 完成                                                                 |

### Phase 5e: L2 audio clip (= 任意 / 後回し可)

| 変更                                                                                                            |
| --------------------------------------------------------------------------------------------------------------- |
| `audio_clip_cache.py` (新規): line 単位 TTS cache                                                               |
| Stage 2 を per-line 経路 / one-shot 経路の切替に再設計                                                          |
| (= 大規模変更。one-shot の prosody 連続性とのトレードオフがあるため、Phase 5d 完了後の運用データを見て判断する) |

### Phase 5f: 旧 cache の deprecation (= 半年運用後)

| 変更                                                                   |
| ---------------------------------------------------------------------- |
| 旧 `bg_cache.py` / `kling_cache.py` の per-line key 経路を deprecate   |
| `_override_*` 経路は残す (= novel intent の cold path 用)              |
| `cache/bg_images/` / `cache/kling_videos/` の旧データを LRU で archive |

---

## 9. 開く議論 (= 設計レビュー時の論点)

1. **L2 (audio clip) を本当にやるか**
   - 現状 one-shot TTS は line 間の自然な抑揚を作る重要な仕組み
   - per-line cache 化すると prosody が分断される
   - **暫定推奨**: Phase 5b-d で L1 だけ実装し、L2 は運用データを見て判断。同じ line を多用する運用 (= ハッシュタグ等の決まり文句) では効くが、台本固有のセリフが多ければ hit 率は限定的

2. **variant 選択の決定論性**
   - 案 A: `seed = sha256(ts + scene_idx)` (= 提案中、project ごと固定)
   - 案 B: `seed = sha256(screenplay_content)` (= 同じ screenplay は project が違っても同じ動画)
   - 案 C: random (= rebuild で別動画が出る、A/B testing 向き)
   - **暫定推奨**: 案 A。レビュー / 修正サイクルが安定する

3. **intent 粒度: 5s 固定 vs 5s/10s 混在**
   - 10s intent (= 長尺アクション) を許すと variant pool の重複が起きる ("talking_head_calm 5s と 10s で別 pool")
   - 一方、長セリフは 10s が必要
   - **暫定推奨**: 同 intent_id × duration_bucket で別 pool。intent vocabulary は同じ

4. **starting_emotion を「scene 開始時」と定義する是非**
   - kling 動画は 5s かけて表情変化することがある (= 中立 → 焦り)
   - cache key には開始のみ入れる? 開始 + 終了の 2 点 (= "emotion arc bucket") で入れる?
   - **暫定推奨**: 開始のみ。emotion arc は kling prompt の自由度に委ねる (= variant pool で多様性確保)

5. **`_override_*` を残し続けるか**
   - 残すと「楽な道」として常用されて enum が育たないリスク
   - 廃止すると novel intent の機動力が落ちる
   - **暫定推奨**: 残す。ただし `_override_*` を使った scene は cache 0 のため運用 cost が見える化され、自然と enum 化が進む

6. **CLAUDE.md「指示の範囲を超えない」との関係**
   - intent 推定は LLM が行うため、人間の意図と乖離する可能性
   - **担保**: `confidence < 0.7` で fallback、UI で intent を必ず確認できる、analyze 出力の人間レビューを Stage 1 に明示する

7. **pool warm-up の運用**
   - 初期 5 intent × `(char × loc)` 全組合せ × 10 variants = 大量 generation
   - **暫定推奨**: 初期は **実際に screenplay で使われた組合せのみ** lazy 生成 (= 1 take で pool 入り、`pool_target_size` までは複数 screenplay 跨いで成長)

8. **cache invalidation の波及**
   - キャラの参照画像を 1 枚差し替えると `_ref_image_shas` が変わって全 clip pool が miss 化
   - 衣装変更ごとに数百 GB を再生成するか?
   - **暫定推奨**: 参照画像変更時に「旧 clip pool は archive、新 pool は lazy 構築」で運用。`scripts/migrate_clip_pool.py --char-from f1__office_v1 --char-to f1__office_v2` で意図的に migrate する経路も用意

---

## 10. Remotion 設計との関係

`2026-05-10_remotion-integration-design.md` とは **独立** に進められる。

| シナリオ                   | 効果                                                                                                                      |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| クリップライブラリのみ実装 | per-screenplay 課金が大幅減 (= 主に Sync.so のみ)。最終 mp4 は ffmpeg overlay のまま                                      |
| Remotion のみ実装          | platform 別 variant が出せる。AI 課金は不変                                                                               |
| **両方**                   | 1 clip pool に対して `(youtube/ig/tiktok) × (字幕 variant) × (アスペクト比) = N variant` がほぼゼロ課金で吐ける。ROI 倍増 |

実装順序の推奨:

1. Remotion Phase 0-1 (= Stage 6 backend 切替) を先行 (= AI 課金に影響しないので安全)
2. クリップライブラリ Phase 5a-5d (= 大本命)
3. Remotion Phase 2-3 (= UI 統合 + platform variant) で価値を倍化

---

## 11. テスト戦略

### 11.1 ユニット

| テスト対象                     | 観点                                                                                                    |
| ------------------------------ | ------------------------------------------------------------------------------------------------------- |
| `compute_clip_key`             | line / emotion / audio_dynamics の差で key が変わらない不変性                                           |
| `select_variant_deterministic` | (ts, scene_idx) が同じなら同じ variant が選ばれる、別 ts では分散する                                   |
| `register_variant`             | 同 clip_key で N 回呼ぶと N variant が並ぶ、quality gate failure で `pending_review` 留置される         |
| `lookup_clip_pool`             | pending variant は無視、active のみ返す                                                                 |
| screenplay_validator           | `visual_intent_id` 必須化 (= override 無い場合) / vocabulary 内チェック / `start_emotion` enum チェック |

### 11.2 統合

| テスト                                                                                                                                   |
| ---------------------------------------------------------------------------------------------------------------------------------------- |
| `test_clip_pool_growth_e2e`: 同じ scene を 10 回 generation → pool に 10 variants が並び、11 回目以降は hit                              |
| `test_clip_pool_screenplay_invariance`: line text が違うが intent / char / loc / start_emotion 一致の 2 つの screenplay で同 clip が hit |
| `test_clip_pool_migration_on_char_swap`: character_refs の参照画像差替えで clip_key が変わり、旧 pool が miss 化                         |

### 11.3 シミュレーション (= ROI 確認)

`tests/sim/test_clip_pool_hit_rate.py`: 過去 N 本の screenplay を順次流して hit 率の
推移をプロット。20 本目で 50% hit、50 本目で 80% hit を達成目標とする。

---

## 12. 完了条件

このプランの全 Phase が完了した時点で:

- ✅ `screenplay.json` の各 scene が `visual_intent_id` / `start_emotion` / `duration_bucket` を持つ
- ✅ `cache/clips/<clip_key>/vNN/` に variant pool が蓄積されている
- ✅ 同 (intent, char, loc, start_emotion, duration) の 2 つの screenplay が同 clip を共有 hit する
- ✅ `scripts/grow_clip_pool.py` で pool を意図的に成長させられる
- ✅ `IntentCatalog.tsx` で intent 一覧と pool 状態が見える
- ✅ analyze pipeline が intent_id を高い confidence で推定する
- ✅ pool warm 後の per-screenplay 課金が **TTS + Sync.so のみ** に縮退している
- ✅ `_override_*` 経路は novel intent 用 cold path として残っている
- ✅ Remotion 統合 (= 別 doc) と組み合わせると platform variant が無料で吐ける

---

## 13. 次アクション

1. このプランをレビューして §9 の論点を解決
2. Phase 5a (= 1 週間) を着手するかの判断
3. Go なら `config/visual_intents.yaml` を 5 intent で起こし、`screenplay_validator.py` の
   オプショナル受入から実装開始
4. Phase 5a 完了時に Phase 5b の go/no-go を再判断 (= analyze pipeline / clip_library の
   実装順を実データで確かめる)

**ステータス**: 本ドキュメントは proposal。実装着手は未承認。
