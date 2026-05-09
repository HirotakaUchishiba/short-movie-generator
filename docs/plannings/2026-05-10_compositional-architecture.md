# Compositional Architecture: クリップライブラリ + Remotion 合成エンジン 設計案

**date**: 2026-05-10 / **base branch**: `main` / **status**: proposal (= 未着手、レビュー待ち)
**supersedes**:

- `2026-05-10_remotion-integration-design.md` (= 字幕レンダラ単独の議論)
- `2026-05-10_clip-library-architecture.md` (= 厳密 hash 一致の cache 設計)

両 doc の議論を統合し、**「パーツ化された表現要素を、決定論的に選択し、Remotion で合成する」** という統一原理に再設計する。

---

## 0. Executive Summary

本プロジェクトを以下のアーキテクチャに転換する:

1. **生成系 → ライブラリ系** へ転換。`screenplay.json` は自然言語の自由記述から、
   **enum によるパーツ参照の宣言** に変える
2. **重いパーツ (= AI 生成物)** はクリップライブラリで identity 一致 + variant pool として
   再利用。warm 状態の per-screenplay 課金を **Sync.so のみ** に縮退する
3. **軽いパーツ (= subtitle / sticker / transition / camera_move 等)** は Remotion の
   React コンポーネントとして実装し、enum で screenplay から参照する
4. **Remotion = composition engine** として、両層のパーツを `<Sequence>` / `<AbsoluteFill>`
   で時間 + 空間に配置し、最終 mp4 を吐く責務を持つ
5. プレビュー UI と最終 render は同じ Remotion `<Player>` / `render` を使うことで
   **ピクセル一致** を保証する
6. platform 別 variant (= YouTube / IG / TikTok) は global_parts の差し替えで
   AI 課金ゼロで吐ける

---

## 1. 背景と目的

### 1.1 現状の構造的欠陥

| 領域                              | 欠陥                                                                                                                                                                                             |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **cache key の漏れ**              | `bg_cache.compute_bg_cache_key` / `kling_cache.build_cache_key` が `lines[].emotion` / `audio_dynamics` 等の per-line 情報を内包しており、人間目には同じシーンでも screenplay 違いで miss する   |
| **1 intent あたり 1 take**        | `cache/bg_images/<key>.png` は 1 ファイル上書き構造。同 key で N take 貯める表現力がない (= 視聴者から見た映像の単調さの遠因)                                                                    |
| **`animation_prompt` の自由記述** | scene の動作指示が free-text 英文。1 文字の差で別 key になる。enum 化されていない                                                                                                                |
| **オーバーレイの表現力**          | `compositor.py` の ffmpeg `drawtext` で字幕を焼く構造。CSS 相当の表現 (= karaoke / spring / 感情別カラー) が事実上書けない                                                                       |
| **プレビューと出力の不一致**      | `StageOverlay.tsx` は `<video src="overlaid.mp4">` で焼き込み済みを再生する。手動チャンク編集後に「保存して焼き直し」を押すまで反映されず、UI と最終出力の見た目もフォント描画差で完全一致しない |
| **platform 共通の単一 mp4**       | `output/reels_<TS>.mp4` 1 本を YouTube / IG / TikTok 共通で使い回し、platform ごとの最適化ができない                                                                                             |

### 1.2 ターゲット state

- **screenplay は完全宣言的**: 自然言語指示が排除され、すべてのフィールドが enum 参照
- **同一性で再利用**: `(character, location, start_emotion, camera_distance)` が一致する
  クリップは未来永劫 hit、variant pool で多様性を担保
- **リッチな表現力**: subtitle / sticker / transition / lower_third / camera_move /
  filter_preset / bgm / sfx 等のパーツが React component として組み合わさる
- **ピクセル一致 UI**: `<Player>` と render が同じ Composition を共有
- **AI 課金最小化**: warm 状態で per-screenplay 課金 = Sync.so のみ

### 1.3 設計原則

1. **役割分担: Production Pipeline と Composition Engine は別の責務**
   - **Production Pipeline (= 既存 `main.py` / `staged_pipeline.py` の Stage 1-5)**:
     パーツ製造の責務。Kling / Imagen / TTS / Sync.so で AI 生成し、cache に蓄える。
     手動操作 + フルオート (= auto_loop) を組み合わせた既存資産はすべてここに属する
   - **Composition Engine (= 新設、Remotion + Layer 3)**:
     既製パーツ組立の責務。Production Pipeline が貯めたパーツを再利用して最終 mp4 を吐く。
     **新規パーツの製造はしない**
2. **不変条件: AI 課金は減らす方向にしか動かない** — Remotion 導入で AI 呼び出しが増える設計はしない
3. **不変条件: SSOT は Python 側に置く** — タイミング解決 / cache key 派生 / variant 選択は Python。
   Remotion は「貰った値を信じてレンダリングするだけ」
4. **不変条件: 決定論性** — 同 screenplay の rebuild で同じ動画が出る。variant 選択も
   `seed = sha256(ts + scene_idx)` で固定
5. **CLAUDE.md の「指示の範囲を超えない」/「台本は人間が作成する」を遵守** — パーツの追加 / 廃止は
   人間レビューを通す。screenplay の意図しない演出追加は禁止
6. **後方互換** — 旧 screenplay (= free-text path) は graceful fallback として動き続ける

---

## 2. 全体アーキテクチャ

### 2.1 3 層モデル

```
┌──────────────────────────────────────────────────────────┐
│ Layer 3: Composition Engine (= Remotion)                 │
│   - <PartRenderer> dispatch                              │
│   - <Sequence> 時間軸合成 / <AbsoluteFill> 空間合成        │
│   - <Player> (UI) と render (最終) が同 Composition       │
│   - platform 別 template                                 │
└──────────────────────────────────────────────────────────┘
                          ↑ props (= render_plan.json)
┌──────────────────────────────────────────────────────────┐
│ Layer 2: Part Registry (= 軽い enum パーツ)              │
│   - subtitle_style / sticker / title_card / lower_third  │
│   - transition / camera_move / frame_layout              │
│   - filter_preset / bgm / sfx                            │
│   実装は React component。SSOT は config/part_registry/*.yaml │
└──────────────────────────────────────────────────────────┘
                          ↑ enum lookup
┌──────────────────────────────────────────────────────────┐
│ Layer 1: Clip Library (= 重い AI 生成パーツ)             │
│   - visual_clip (= bg + clean kling)                     │
│   - audio_clip (= TTS、将来拡張)                          │
│   identity/annotation/provenance 構造で degree match      │
│   variant pool で多様性 (= top 10 entries)                │
└──────────────────────────────────────────────────────────┘
                          ↑ identity match lookup
                  [screenplay.json (= 完全宣言的)]
```

### 2.2 パーツ分類

| 分類                 | 例                                                                         | 重さ              | 保存                                       | Layer | enum SSOT                                          |
| -------------------- | -------------------------------------------------------------------------- | ----------------- | ------------------------------------------ | ----- | -------------------------------------------------- |
| **重い (= AI 生成)** | visual_clip, audio_clip                                                    | 永続 + 課金       | `cache/clips/<entry_id>/`                  | 1     | `config/part_registry/visual_intents.yaml` 等      |
| **中重 (= 素材)**    | bgm, sfx, sticker (= 静止画), 既製素材                                     | 永続              | `assets/parts/<category>/<id>.{ext}`       | 2     | `config/part_registry/<category>.yaml`             |
| **軽い (= コード)**  | subtitle_style, title_card, transition, camera_move, layout, filter_preset | 揮発 (= 都度描画) | `frontend/remotion/parts/<category>/*.tsx` | 2-3   | `config/part_registry/<category>.yaml` + 実装は TS |

### 2.3 データフロー

```
[1. screenplay.json (= enum 参照のみ)]
    ↓
[2. resolve_scene(scene)]                    ← Python
    ├─ Layer 1: clip_library.lookup(scene.identity)
    │   ├─ hit  → variant pool top 10 → seed で 1 本選択 → bg/kling パスを取得
    │   └─ miss → cold path: Imagen + Kling で 1 take 生成 → entry 登録 → 上記
    ├─ Layer 2 (heavy): asset/parts/* から file path 解決
    └─ Layer 2 (light): part_registry から component_id を解決
    ↓
[3. TTS]                                      ← 既存 (per-screenplay)
    ├─ ElevenLabs one-shot で screenplay 全体の音声 + alignment を取得
    └─ silence-detect で line 境界を snap (= 既存ロジック維持)
    ↓
[4. Sync.so lipsync]                          ← 既存 (per-screenplay)
    └─ kling_clean + tts → tmp/scene_<S>.mp4
    ↓
[5. render_plan.json を Python が組み立て]    ← Layer 3 への渡し
    ├─ 解決済み scene_<S>.mp4 path
    ├─ 解決済み subtitle 時刻 (= _resolve_subtitle_timings 流用)
    ├─ Layer 2 パーツの enum 参照と props
    └─ template 指定 (= "base" | "youtube" | "instagram" | "tiktok")
    ↓
[6. Remotion render]                          ← Layer 3
    └─ npx remotion render Root.tsx Composition-<template> output.mp4 --props=...
    ↓
[7. output/reels_<TS>.mp4 (+ platform variants)]
    ↓
[8. Stage 7+8: final import / publish]        ← 既存
```

---

## 3. Layer 1: クリップライブラリ

### 3.1 identity / annotation / provenance 分離

各 cache entry は 3 つの観点を持つ:

| 階層           | 役割                                                       | 例                                                                             |
| -------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------ |
| **identity**   | 「視覚的に互換か?」を決める。**hard match 必須**           | character_refs / location_ref / start_emotion / camera_distance                |
| **annotation** | 「このクリップは何が得意か」を記述。**ranking スコア材料** | visual_intent_id / duration_bucket / motion_intensity / generation_seed        |
| **provenance** | デバッグ + 再生成の根拠。lookup には使わない               | imagen_prompt / kling_prompt / model_versions / source_screenplay / timestamps |

```
cache/clips/<entry_id>/
  meta.json
  bg.png
  kling_clean.mp4         ← lipsync 前の生映像
  preview.gif             ← UI 一覧用、1fps スプライト
```

```json
// meta.json
{
  "id": "01H8KZX...",
  "identity": {
    "character_refs": ["f1__office"],
    "location_ref": "home_office",
    "start_emotion": "中立",
    "camera_distance": "medium-close"
  },
  "annotation": {
    "visual_intent_id": "talking_head_calm",
    "duration_bucket": 5,
    "motion_intensity": "low",
    "generation_seed": 12345
  },
  "provenance": {
    "imagen_prompt": "...",
    "kling_prompt": "...",
    "ref_image_shas": { "f1__office": "<sha>" },
    "location_sha": "<sha>",
    "model_versions": { "imagen": "imagen-3.0", "kling": "v3" },
    "generated_at": "2026-05-10T12:34:56Z",
    "source_screenplay": "auto_xyz.json",
    "source_scene_idx": 2
  },
  "lifecycle": {
    "approved_at": "2026-05-10T12:35:01Z",
    "hit_count": 0,
    "last_used_at": null,
    "blacklisted": false,
    "status": "active"
  }
}
```

### 3.2 lookup アルゴリズム (= degree match)

```python
HARD_DIMENSIONS = ("character_refs", "location_ref", "start_emotion", "camera_distance")

def lookup_clip_pool(scene: dict, top_k: int = 10) -> list[ClipEntry]:
    candidates = [
        e for e in iter_active_entries()
        if _identity_matches(e, scene)
    ]
    if not candidates:
        return []

    requested_ann = {
        "visual_intent_id": scene.get("visual_intent_id"),
        "duration_bucket": scene.get("duration_bucket"),
        "motion_intensity": scene.get("motion_intensity", "low"),
    }
    candidates.sort(key=lambda e: -_annotation_score(e, requested_ann))
    return candidates[:top_k]


def _identity_matches(entry: ClipEntry, scene: dict) -> bool:
    if frozenset(entry.identity["character_refs"]) != frozenset(scene["character_refs"]):
        return False
    if entry.identity["location_ref"] != scene["location_ref"]:
        return False
    if entry.identity["start_emotion"] != scene["start_emotion"]:
        return False
    if entry.identity["camera_distance"] != scene.get("camera_distance", "medium-close"):
        return False
    return True


def _annotation_score(entry: ClipEntry, requested: dict) -> float:
    score = 0.0
    a = entry.annotation
    # visual_intent_id: 完全一致 +3.0、互換セット内 +1.5
    if a.get("visual_intent_id") == requested.get("visual_intent_id"):
        score += 3.0
    elif _intent_compatible(a.get("visual_intent_id"), requested.get("visual_intent_id")):
        score += 1.5
    # duration_bucket
    if a.get("duration_bucket") == requested.get("duration_bucket"):
        score += 1.0
    # motion_intensity
    if a.get("motion_intensity") == requested.get("motion_intensity"):
        score += 0.5
    # 新しいエントリを軽く優遇 (= 飽和を避けるため hit_count が低いものを微優先)
    score += max(0.0, 0.3 - 0.01 * entry.lifecycle["hit_count"])
    return score


def _intent_compatible(a: str | None, b: str | None) -> bool:
    """visual_intents.yaml の compatible_with を辿る。"""
    if not a or not b:
        return False
    catalog = load_intent_catalog()
    return b in catalog[a].compatible_with
```

### 3.3 variant 選択 (= 決定論的)

```python
def select_variant(pool: list[ClipEntry], ts: str, scene_idx: int) -> ClipEntry:
    if not pool:
        raise ValueError("empty pool")
    seed = int(hashlib.sha256(f"{ts}|{scene_idx}".encode()).hexdigest(), 16)
    return pool[seed % len(pool)]
```

**ts** は project ごとの timestamp (= `temp/<TS>/`)。同 screenplay の rebuild では
TS が変わらないため同 variant が出る。別 project では別 variant が選ばれる
ため、視聴者から見た多様性も担保される。

### 3.4 cold path (= miss 時の挙動)

```python
def resolve_scene_visual(scene: dict, ts: str, scene_idx: int) -> ResolvedVisual:
    if scene.get("_override_animation_prompt"):
        return _legacy_freetext_path(scene)  # 後方互換

    pool = lookup_clip_pool(scene, top_k=10)

    if not pool:
        # cold: 1 take 生成して entry 登録、以後 hit
        entry = generate_new_clip_entry(scene, status="pending_review")
        register_clip_entry(entry)
        # pending_review 中も即座に使う (= UI で承認待ちのまま使用)
        # blacklist された場合は次回 lookup で除外される
        return ResolvedVisual.from_entry(entry, source="cold")

    if len(pool) < config.CLIP_POOL_TARGET_SIZE:
        logger.info(
            "[clip-pool] %s warming up (%d/%d entries)",
            _identity_repr(scene), len(pool), config.CLIP_POOL_TARGET_SIZE,
        )

    selected = select_variant(pool, ts, scene_idx)
    return ResolvedVisual.from_entry(selected, source="hit")
```

### 3.5 variant pool 成長

```bash
python3 scripts/grow_clip_pool.py \
  --identity '{"character_refs":["f1__office"],"location_ref":"home_office","start_emotion":"中立","camera_distance":"medium-close"}' \
  --annotation '{"visual_intent_id":"talking_head_calm","duration_bucket":5,"motion_intensity":"low"}' \
  --variants 10 \
  --auto-approve   # 既定は UI 承認待ち
```

挙動:

1. identity / annotation を seed の差で N 回 Imagen + Kling を呼ぶ
2. 各 entry を `cache/clips/<id>/` に置き、`status: pending_review` で登録
3. `--auto-approve` なら quality gate 簡易判定後に `status: active` 昇格
4. 手動承認は UI (= IntentCatalog) または `python3 scripts/approve_clip.py <id>`

### 3.6 lifecycle 管理

| 操作                    | トリガ                                                                                                    |
| ----------------------- | --------------------------------------------------------------------------------------------------------- |
| `pending_review`        | `register_clip_entry` 直後                                                                                |
| `active`                | UI / CLI 承認 + `_evaluate_quality` pass。`auto_promote=True` なら Stage 4 承認時に自動昇格               |
| `blacklisted`           | UI で reject、または `scripts/blacklist_clip.py <id> --reason "..."`                                      |
| LRU pruning             | `lifecycle.last_used_at` で older から削除。`config.CLIP_POOL_MAX_TOTAL_GB` 超過時に 80% まで縮退         |
| character/location 変更 | 参照画像 sha が変わると `_identity_matches` 経路で旧 entry が miss 化 (= 物理削除は別 cron で archive へ) |

### 3.7 invariants (= 守るべき不変条件)

| invariant                                                                  | 理由                                                                                      |
| -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `identity` は **hard match のみ**。決して soft 化しない                    | キャラ/場所/開始表情/画角が違うクリップを当てると視聴者に「別の動画になった」と気付かれる |
| `annotation` の比較は **降格可能** (= 一致が無くても fallback)             | warm-up 中の hit 率を上げるため                                                           |
| `compositional` パーツ (= subtitle/sticker/...) は **identity に含めない** | 同じ visual atom に対して composition 違いで variant を吐ける、というのが本設計の主目的   |
| variant 選択は **deterministic seed**                                      | 同 screenplay の rebuild で動画が変わると、字幕修正等の微調整時に再検証コストが発生する   |
| `_override_*` 経路は **常に動く** (= 廃止しない)                           | novel intent / 緊急対応の cold path が無いと運用詰む                                      |

---

## 4. Layer 2: Part Registry

### 4.1 part 種別 taxonomy

初期実装するカテゴリ (= 12 種):

| カテゴリ          | 役割                                   | サンプル id                                                         | 重さ      |
| ----------------- | -------------------------------------- | ------------------------------------------------------------------- | --------- |
| `visual_intents`  | クリップ識別子 (= Layer 1 のラベル)    | talking_head_calm, reaction_surprise, action_typing                 | (Layer 1) |
| `subtitle_styles` | 字幕の見た目 + アニメーション          | minimal, karaoke_bold, fade_in, bouncing_word                       | 軽        |
| `stickers`        | 絵文字 / リアクション png + 出現アニメ | exclaim_red, question_mark, heart_pulse, thumbs_up                  | 中重      |
| `title_cards`     | イントロ / 仕切り / アウトロ           | logo_reveal_v1, section_break_simple, subscribe_cta_v1              | 軽        |
| `lower_thirds`    | 名前バナー / 役職テロップ / 引用       | name_banner, role_caption, quote_box                                | 軽        |
| `transitions`     | scene 間 / 内 transition               | cut, dip_to_black, dip_to_white, slide_left, smash_cut, zoom_in_out | 軽        |
| `camera_moves`    | 動画への post-effect 動き              | none, subtle_zoom_in, ken_burns, dolly_pull_back                    | 軽        |
| `frame_layouts`   | 画面分割                               | full, split_horizontal, pip_corner_tr, pip_corner_bl                | 軽        |
| `filter_presets`  | 色調 / フィルタ                        | none, warm_cinematic, cool_blue, monochrome, vintage                | 軽        |
| `bgm_tracks`      | 楽曲 + ducking                         | upbeat_synth_01, lofi_calm_03, dramatic_strings_02                  | 中重      |
| `sfx`             | 効果音                                 | whoosh, ding, drum_hit, transition_swoosh, pop                      | 中重      |
| `outro_ctas`      | platform 別 outro                      | youtube_subscribe, ig_follow, tiktok_like                           | 軽        |

初期は各カテゴリ 5-10 entries で開始。運用しながら追加 (= `_override_*` 経由で
試行 → 価値があれば registry 化)。

### 4.2 SSOT yaml 構造

```yaml
# config/part_registry/subtitle_styles.yaml
version: 1
parts:
  - id: minimal
    description: |
      白文字 + 黒縁取り。現状の ffmpeg drawtext と同じ見た目。default。
    params_schema:
      font_size: { type: number, default: 76 }
      font_color: { type: string, default: "#FFFFFF" }
      border_color: { type: string, default: "#000000" }
      border_width: { type: number, default: 6 }
    valid_contexts: [scene, global]
    component: MinimalSubtitle
    deprecated: false

  - id: karaoke_bold
    description: |
      単語ごとにハイライトが進む TikTok 風太字スタイル。word-level timestamps が必要。
    params_schema:
      base_color: { type: string, default: "#FFFFFF" }
      highlight_color: { type: string, default: "#FACC15" }
      font_size: { type: number, default: 84 }
    valid_contexts: [scene]
    requires:
      - tts_alignment # alignment が無いと使えない
    component: KaraokeBoldSubtitle
    deprecated: false

  - id: bouncing_word
    description: |
      単語が下からポップアップ (spring animation)。
    params_schema:
      bounce_strength: { type: number, default: 0.8 }
    valid_contexts: [scene]
    requires:
      - tts_alignment
    component: BouncingWordSubtitle
    deprecated: false
```

```yaml
# config/part_registry/visual_intents.yaml
version: 1
parts:
  - id: talking_head_calm
    description: "Subject stands or sits, faces camera, talks calmly. Minimal body motion."
    suggested_kling_template: |
      A {character} {pose_modifier} in {location_decor},
      {start_emotion_addon}, talking calmly to camera,
      subtle ambient motion, lipsync friendly.
    duration_buckets: [5, 10]
    valid_start_emotions: [中立, 喜び, 満足, 困惑]
    motion_intensity_bucket: low
    pool_target_size: 10
    compatible_with: [talking_head_listening, talking_head_explaining]
    deprecated: false
```

`compatible_with` は §3.2 の `_intent_compatible` で参照される。

### 4.3 React コンポーネントの住所

```
frontend/remotion/
  parts/
    subtitles/
      MinimalSubtitle.tsx
      KaraokeBoldSubtitle.tsx
      FadeInSubtitle.tsx
      BouncingWordSubtitle.tsx
      index.ts                ← id → component の map
    stickers/
      ExclaimRed.tsx
      QuestionMark.tsx
      HeartPulse.tsx
      index.ts
    title_cards/
      LogoRevealV1.tsx
      SectionBreakSimple.tsx
      SubscribeCtaV1.tsx
      index.ts
    transitions/
      Cut.tsx
      DipToBlack.tsx
      SlideLeft.tsx
      SmashCut.tsx
      index.ts
    camera_moves/
      SubtleZoomIn.tsx
      KenBurns.tsx
      DollyPullBack.tsx
      index.ts
    ...
  PartRegistry.ts             ← 全カテゴリの id → component 統合 lookup
```

```tsx
// frontend/remotion/PartRegistry.ts
import * as Subtitles from "./parts/subtitles";
import * as Stickers from "./parts/stickers";
// ...

export const PART_REGISTRY = {
  subtitle_styles: Subtitles,
  stickers: Stickers,
  title_cards: TitleCards,
  // ...
} as const;

export function resolvePartComponent(
  category: keyof typeof PART_REGISTRY,
  id: string,
): React.ComponentType<any> {
  const cat = PART_REGISTRY[category];
  const cmp = (cat as any)[id];
  if (!cmp) throw new Error(`unknown part: ${category}/${id}`);
  return cmp;
}
```

### 4.4 part 追加フロー

新規 part を増やす標準手順:

1. `config/part_registry/<category>.yaml` に entry を追加 (= description / params_schema / component name)
2. `frontend/remotion/parts/<category>/<ComponentName>.tsx` で実装
3. `frontend/remotion/parts/<category>/index.ts` の id map に追加
4. Storybook (= `<ComponentName>.stories.tsx`) で見た目確認
5. Vitest (= `<ComponentName>.test.tsx`) で props 経由動作確認
6. `screenplay_validator.py` の enum チェックを yaml から自動再ロード (= validator 側の hardcode 不要)

人間レビュー後、screenplay から参照可能になる。

---

## 5. Layer 3: Remotion composition engine

### 5.1 Composition 構造

```
frontend/remotion/
  Root.tsx                                    ← registerRoot
  compositions/
    ScreenplayBase.tsx                        ← 基本 composition (= 全 scene を Sequence で並べる)
    ScreenplayYoutube.tsx                     ← Base + youtube outro_cta + 字幕控えめ
    ScreenplayInstagram.tsx                   ← Base + ホールド冒頭 + IG 風太字字幕
    ScreenplayTikTok.tsx                      ← Base + 単語 karaoke + 字幕下 1/3
  components/
    PartRenderer.tsx                          ← type + id を受けて registry から component dispatch
    SceneSequence.tsx                         ← 1 scene = OffthreadVideo + scene_parts overlay
    GlobalPartsLayer.tsx                      ← bgm / outro_card 等の screenplay-wide パーツ
  hooks/
    useSceneOffsets.ts
    useTtsAlignment.ts                        ← word-level timestamps を読む
  schemas/
    renderPlan.ts                             ← Zod スキーマ
```

```tsx
// compositions/ScreenplayBase.tsx
export const ScreenplayBase: React.FC<{ plan: RenderPlan }> = ({ plan }) => {
  return (
    <AbsoluteFill>
      {/* filter_preset (= 全画面) */}
      {plan.global_parts.filter_preset && (
        <PartRenderer
          category="filter_presets"
          id={plan.global_parts.filter_preset.id}
          params={plan.global_parts.filter_preset.params}
        />
      )}

      {/* scene の連結 */}
      {plan.scenes.map((scene, idx) => (
        <Sequence
          key={idx}
          from={frameOf(scene.offset_sec)}
          durationInFrames={frameOf(scene.duration_sec)}
        >
          <SceneSequence scene={scene} />
        </Sequence>
      ))}

      {/* bgm (= 全長、ducking 適用) */}
      {plan.global_parts.bgm && (
        <Audio
          src={plan.global_parts.bgm.path}
          volume={plan.global_parts.bgm.ducking_curve}
        />
      )}

      {/* outro_card / cta (= 末尾の Sequence) */}
      {plan.global_parts.outro_card && (
        <Sequence
          from={
            plan.video.duration_frames -
            frameOf(plan.global_parts.outro_card.duration_sec)
          }
          durationInFrames={frameOf(plan.global_parts.outro_card.duration_sec)}
        >
          <PartRenderer
            category="title_cards"
            id={plan.global_parts.outro_card.id}
            params={plan.global_parts.outro_card.params}
          />
        </Sequence>
      )}
    </AbsoluteFill>
  );
};
```

```tsx
// components/SceneSequence.tsx
export const SceneSequence: React.FC<{ scene: ResolvedScene }> = ({
  scene,
}) => {
  return (
    <AbsoluteFill>
      {/* clip 動画 (= Layer 1) */}
      <OffthreadVideo src={scene.scene_video_path} />

      {/* camera_move (= 動画への transform 適用) */}
      {scene.parts.camera_move && (
        <PartRenderer
          category="camera_moves"
          id={scene.parts.camera_move.id}
          params={scene.parts.camera_move.params}
          wraps="parent"
        />
      )}

      {/* 字幕 (= line ごとの Sequence) */}
      {scene.subtitle_lines.map((line, lIdx) =>
        line.chunks.map((chunk, cIdx) => (
          <Sequence
            key={`${lIdx}-${cIdx}`}
            from={frameOf(chunk.start_abs_sec - scene.offset_sec)}
            durationInFrames={frameOf(chunk.end_abs_sec - chunk.start_abs_sec)}
          >
            <PartRenderer
              category="subtitle_styles"
              id={scene.parts.subtitle_style.id}
              params={{
                ...scene.parts.subtitle_style.params,
                text: chunk.text,
                emotion: line.emotion,
              }}
            />
          </Sequence>
        )),
      )}

      {/* sticker (= タイミング指定で重ねる) */}
      {scene.parts.stickers?.map((s, i) => (
        <Sequence
          key={i}
          from={frameOf(s.at)}
          durationInFrames={frameOf(s.duration ?? 1.5)}
        >
          <PartRenderer category="stickers" id={s.id} params={s.params} />
        </Sequence>
      ))}

      {/* lower_third (= タイミング指定) */}
      {scene.parts.lower_third && (
        <Sequence
          from={frameOf(scene.parts.lower_third.at)}
          durationInFrames={frameOf(scene.parts.lower_third.duration)}
        >
          <PartRenderer
            category="lower_thirds"
            id={scene.parts.lower_third.id}
            params={scene.parts.lower_third.params}
          />
        </Sequence>
      )}

      {/* sfx (= 短い、Audio で重ねる) */}
      {scene.parts.sfx?.map((s, i) => (
        <Sequence key={i} from={frameOf(s.at)}>
          <Audio src={s.path} volume={s.volume ?? 0.6} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
```

### 5.2 PartRenderer dispatch

```tsx
// components/PartRenderer.tsx
export const PartRenderer: React.FC<{
  category: PartCategory;
  id: string;
  params: Record<string, unknown>;
  wraps?: "parent";
}> = ({ category, id, params, wraps }) => {
  const Component = resolvePartComponent(category, id);
  if (wraps === "parent") {
    // camera_move 等、親 element をラップして transform を適用するパターン
    return <Component {...params} />;
  }
  return <Component {...params} />;
};
```

### 5.3 render_plan.json の schema (= Layer 3 への入力)

```ts
// schemas/renderPlan.ts
import { z } from "zod";

export const RenderPlan = z.object({
  video: z.object({
    width: z.number(), // 1080
    height: z.number(), // 1920
    fps: z.number(), // 60
    duration_frames: z.number(),
  }),
  scenes: z.array(
    z.object({
      index: z.number(),
      scene_video_path: z.string(), // tmp/scene_<S>.mp4 の絶対パス
      offset_sec: z.number(),
      duration_sec: z.number(),
      subtitle_lines: z.array(
        z.object({
          line_idx: z.number(),
          emotion: z.string().optional(),
          chunks: z.array(
            z.object({
              text: z.string(),
              start_abs_sec: z.number(),
              end_abs_sec: z.number(),
              anchor_kind: z.enum(["auto", "manual"]),
            }),
          ),
        }),
      ),
      parts: z.object({
        subtitle_style: z.object({
          id: z.string(),
          params: z.record(z.unknown()),
        }),
        stickers: z
          .array(
            z.object({
              id: z.string(),
              at: z.number(),
              duration: z.number().optional(),
              params: z.record(z.unknown()),
            }),
          )
          .optional(),
        lower_third: z
          .object({
            id: z.string(),
            at: z.number(),
            duration: z.number(),
            params: z.record(z.unknown()),
          })
          .optional(),
        camera_move: z
          .object({
            id: z.string(),
            params: z.record(z.unknown()),
          })
          .optional(),
        sfx: z
          .array(
            z.object({
              path: z.string(),
              at: z.number(),
              volume: z.number().optional(),
            }),
          )
          .optional(),
      }),
    }),
  ),
  global_parts: z.object({
    filter_preset: z
      .object({ id: z.string(), params: z.record(z.unknown()) })
      .optional(),
    bgm: z
      .object({
        path: z.string(),
        ducking_curve: z.union([
          z.number(),
          z.array(z.tuple([z.number(), z.number()])),
        ]),
      })
      .optional(),
    intro_card: z
      .object({
        id: z.string(),
        duration_sec: z.number(),
        params: z.record(z.unknown()),
      })
      .optional(),
    outro_card: z
      .object({
        id: z.string(),
        duration_sec: z.number(),
        params: z.record(z.unknown()),
      })
      .optional(),
  }),
  template: z.enum(["base", "youtube", "instagram", "tiktok"]),
});
```

### 5.4 platform 別 template

各 template は `ScreenplayBase` を import して global_parts を上書きする:

```tsx
// compositions/ScreenplayYoutube.tsx
export const ScreenplayYoutube: React.FC<{ plan: RenderPlan }> = ({ plan }) => {
  const planForYoutube: RenderPlan = {
    ...plan,
    global_parts: {
      ...plan.global_parts,
      outro_card: plan.global_parts.outro_card ?? {
        id: "youtube_subscribe",
        duration_sec: 2.0,
        params: {},
      },
    },
  };
  return <ScreenplayBase plan={planForYoutube} />;
};
```

### 5.5 Player と render の統一

```tsx
// frontend/src/components/stages/StageOverlay.tsx (Phase 4 で書き直し)
import { Player } from "@remotion/player";
import { ScreenplayBase } from "../../../remotion/compositions/ScreenplayBase";

export default function StageOverlay() {
  const { plan } = useRenderPlan(ctx.detail.timestamp); // GET /api/projects/<TS>/render-plan
  return (
    <Player
      component={ScreenplayBase}
      inputProps={{ plan }}
      durationInFrames={plan.video.duration_frames}
      fps={plan.video.fps}
      compositionWidth={plan.video.width}
      compositionHeight={plan.video.height}
      controls
      autoPlay={false}
    />
  );
}
```

Player と最終 render が **同じ Composition + 同じ props** を使うため、見た目が
ピクセル一致する (= フォント描画の Chromium 差は player と render で同じ Chromium が動くため
発生しない)。

---

## 6. screenplay schema 拡張

### 6.1 旧 → 新

```json
// 旧 (= 自由記述、現行)
{
  "scenes": [
    {
      "location_ref": "home_office",
      "background_prompt": "デスクに駆け寄るエンジニア cinematic lighting",
      "animation_prompt": "subject rushes to desk, opens laptop, leans back relieved",
      "character_refs": ["f1__office"],
      "lipsync": true,
      "lines": [
        { "text": "やばいやばい", "start": 0.0, "end": 1.0, "emotion": "焦り" }
      ]
    }
  ]
}
```

```json
// 新 (= enum 参照、提案)
{
  "global_parts": {
    "filter_preset": { "id": "warm_cinematic", "params": {} },
    "bgm": { "id": "upbeat_synth_01", "ducking": true },
    "intro_card": { "id": "logo_reveal_v1", "duration_sec": 1.5 },
    "outro_card": { "id": "subscribe_cta_v1", "duration_sec": 2.0 }
  },
  "scenes": [
    {
      "identity": {
        "character_refs": ["f1__office"],
        "location_ref": "home_office",
        "start_emotion": "中立",
        "camera_distance": "medium-close"
      },
      "annotation": {
        "visual_intent_id": "talking_head_calm",
        "duration_bucket": 5,
        "motion_intensity": "low"
      },
      "lipsync": true,
      "lines": [
        { "text": "やばいやばい", "emotion": "焦り", "delivery": "早口で小声" }
      ],
      "scene_parts": {
        "subtitle_style": { "id": "karaoke_bold", "params": {} },
        "stickers": [{ "id": "exclaim_red", "at": 0.5, "params": {} }],
        "camera_move": { "id": "subtle_zoom_in", "params": {} },
        "transition_in": { "id": "cut", "params": {} },
        "transition_out": { "id": "dip_to_black", "params": {} }
      },

      "_override_background_prompt": null,
      "_override_animation_prompt": null
    }
  ]
}
```

### 6.2 後方互換

- 旧 screenplay (= `background_prompt` / `animation_prompt` あり、`identity` 無し) は
  validator pass。`_legacy_freetext_path` で従来の bg_cache / kling_cache 経由
- 新 screenplay (= `identity` あり) は clip_library 経由
- `_override_*` を持つ scene は新 screenplay でも free-text path 強制 (= novel intent 用 escape hatch)
- `lines[].start` / `lines[].end` は **旧では必須、新では省略可** (= Stage 2 が one-shot TTS から
  alignment を取って自動算出する。既存の自動算出ロジックを維持)

### 6.3 validator 変更

`screenplay_validator.py` に以下の追加:

| 検証                                                                                                                                    |
| --------------------------------------------------------------------------------------------------------------------------------------- |
| `identity.character_refs` の値が `characters/<base>/...` と一致すること                                                                 |
| `identity.location_ref` が `locations/<id>.json` に存在                                                                                 |
| `identity.start_emotion` が `EMOTION_AUDIO_TAGS` の key                                                                                 |
| `identity.camera_distance` が `["close-up", "medium-close", "medium", "wide"]`                                                          |
| `annotation.visual_intent_id` が `config/part_registry/visual_intents.yaml` に存在 + `valid_start_emotions` に start_emotion が含まれる |
| `annotation.duration_bucket` が `visual_intents[id].duration_buckets` に含まれる                                                        |
| `scene_parts.subtitle_style.id` が `subtitle_styles.yaml` に存在 + `valid_contexts` に "scene"                                          |
| その他全 part の id が対応 yaml に存在                                                                                                  |
| `requires` (= 例: `tts_alignment`) が満たされること (= alignment が無いのに karaoke_bold は reject)                                     |

---

## 7. データフロー (= warm path 詳細)

```
[1. screenplay.json (新スキーマ)]
   ↓
[2. screenplay_validator]
   ├─ identity / annotation / parts の存在 + 整合性チェック
   └─ 不正 → reject (= UI でエラー表示)
   ↓
[3. resolve_scene_visual(scene, ts, scene_idx)]
   ├─ pool = lookup_clip_pool(scene)        ← Layer 1
   ├─ if pool empty: cold path
   ├─ entry = select_variant(pool, ts, scene_idx)
   └─ return ResolvedVisual (bg.png, kling_clean.mp4 path, identity, annotation)
   ↓
[4. Stage 2: TTS (one-shot)]
   ├─ ElevenLabs API で screenplay 全体 + alignment 取得
   └─ lines に start/end を自動算出
   ↓
[5. Stage 5: Sync.so lipsync (per-screenplay)]
   └─ kling_clean + tts → tmp/scene_<S>.mp4
   ↓
[6. build_render_plan(screenplay, ts)]
   ├─ scene_videos の実尺を ffprobe で取得
   ├─ subtitle 時刻を _resolve_subtitle_timings で解決 (= 既存ロジック流用)
   ├─ part の id / params / 時刻を埋める
   └─ render_plan.json を生成
   ↓
[7. Remotion render]
   └─ npx remotion render Root.tsx Composition-<template> output.mp4 --props=plan.json
   ↓
[8. output/reels_<TS>.mp4 (+ platform variants)]
```

### 7.1 platform variants の build (= Stage 8)

```python
def publish_to_platform(ts: str, platform: str, privacy: str = "unlisted") -> None:
    plan = build_render_plan(ts, template=platform)
    out_path = f"output/reels_{ts}__{platform}.mp4"
    run_remotion_render(plan, out_path, composition=f"Screenplay-{platform}")
    register_final_version(ts, out_path, template=platform)
    # 既存 platform_clients/<platform>.py で publish
    upload_video(out_path, platform=platform, privacy=privacy)
```

### 7.2 cache invalidation

| イベント                          | 影響                                                                                                                                                      |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| character/location 参照画像差替え | `ref_image_shas` / `location_sha` が変わるため、`provenance` で過去 entry をマーク (= identity 一致でも別世代と判定)。新世代 entry が貯まるまで cold path |
| `visual_intents.yaml` の id 廃止  | 廃止 id を `deprecated: true` にする → 新規 screenplay で reject、過去 entry の lookup は引き続き hit (= 旧 screenplay の rebuild は機能維持)             |
| `CLIP_LIBRARY_VERSION` bump       | 重大な品質変更時に手動 bump。全 entry が miss 化 (= 物理削除は別 cron)                                                                                    |
| react component の修正            | rebuild が必要な過去動画は Stage 6 (overlay) から再 render するだけで良い。AI 課金不要                                                                    |
| part_registry yaml の params 変更 | 過去 screenplay の params は yaml の default に従って再評価。互換性に注意するため major 変更時は yaml version を bump                                     |

---

## 8. analyze pipeline 統合

`scripts/analyze_video.py` の Claude prompt を拡張:

### 8.1 抽象台本出力の拡張

Claude が以下を出力するよう prompt を更新:

```json
{
  "scenes": [
    {
      "identity": {
        "speaker": "speaker_1",
        "location_hint": "office_with_window",
        "start_emotion": "中立",
        "camera_distance": "medium-close"
      },
      "annotation": {
        "visual_intent_id": "talking_head_calm",
        "duration_bucket": 5,
        "motion_intensity": "low",
        "confidence": 0.85
      },
      "lines": [...]
    }
  ]
}
```

`config/part_registry/visual_intents.yaml` の id + description 全件を context に注入し、
Claude が best match を返す。`confidence < 0.7` の場合 `_override_animation_prompt` を
返して free-text fallback。

### 8.2 vocabulary 提案 (= novel intent 検出)

`confidence < 0.7` が連続するシーンが見つかると、analyze 出力に `suggested_intents.json` を
併記:

```json
{
  "suggested_intents": [
    {
      "category": "visual_intents",
      "proposed_id": "frantic_typing_at_desk",
      "description": "...",
      "scene_examples": [3, 7],
      "rationale": "..."
    }
  ]
}
```

運用者がレビューして yaml に追加 → `grow_clip_pool.py` で初期 N variants を生成 → 以後 hit。

---

## 9. 実装 Phase

### Phase 0: 学習 + minimum viable (= 1 週間)

| Goal     | 既存 1 TS の screenplay + 既存 scene_videos を Remotion で再生し、現行 ffmpeg overlay と同等の見た目を出す |
| -------- | ---------------------------------------------------------------------------------------------------------- |
| 成果物   | `frontend/remotion/` 一式 + `compositor_remotion.py` の試作 + Hello World render                           |
| 検証     | 既存 TS で Remotion render を回し、字幕位置 / フォント / 色が ffmpeg overlay と PSNR 30dB 以上で一致       |
| 不変条件 | 本番経路は不変 (= `OVERLAY_BACKEND=ffmpeg` 既定)                                                           |

### Phase 1: クリップライブラリ identity/annotation 実装 (= 2-3 週間)

| 変更                                                                                                                                                               |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `clip_library.py` (新規): `lookup_clip_pool` / `select_variant` / `register_clip_entry` / `compute_identity_match`                                                 |
| `cache/clips/<id>/meta.json` 構造実装。旧 `cache/bg_images` / `cache/kling_videos` は当面残す                                                                      |
| `scene_gen.py`: `resolve_scene_visual` 経路を追加 (= identity ありのとき clip_library、無いとき従来 bg_cache + kling_cache)                                        |
| `screenplay_validator.py`: `identity` / `annotation` のオプショナル受入 + part_registry の id 整合性チェック                                                       |
| `config/part_registry/visual_intents.yaml` を 5 intent (talking_head_calm / talking_head_animated / reaction_surprise / reaction_relief / gesture_pointing) で開始 |
| `scripts/grow_clip_pool.py` (新規)                                                                                                                                 |
| `scripts/migrate_clip_pool.py` (新規、character_refs 入れ替え時用)                                                                                                 |
| 旧 5 intent について `grow_clip_pool.py --variants 5` で初期 pool 構築                                                                                             |
| ユニットテスト (= identity match / annotation score / variant 選択の決定論性)                                                                                      |

**完了基準**: `OVERLAY_BACKEND=ffmpeg` のままでも、新 screenplay (= identity あり) で
clip_library hit が起き、AI 課金が下がる。Remotion はまだ統合しない。

### Phase 2: Remotion 基盤 + subtitle parts (= 2 週間)

| 変更                                                                                                    |
| ------------------------------------------------------------------------------------------------------- |
| `frontend/remotion/Root.tsx` / `compositions/ScreenplayBase.tsx` / `components/PartRenderer.tsx` (新規) |
| `subtitle_styles.yaml` を 3 entry (minimal / karaoke_bold / fade_in) で開始                             |
| `frontend/remotion/parts/subtitles/{Minimal,KaraokeBold,FadeIn}Subtitle.tsx`                            |
| `compositor_remotion.py` (新規): `build_render_plan` + `npx remotion render` 起動                       |
| `staged_pipeline.run_overlay` を backend dispatch (= `OVERLAY_BACKEND` 切替) に変更                     |
| `routes/render_plan.py` (新規): GET /api/projects/<TS>/render-plan                                      |
| 既存 ffmpeg backend は残す                                                                              |
| Vitest + Storybook で subtitle component 単体テスト                                                     |
| e2e テスト: ffmpeg backend と Remotion backend で PSNR 比較                                             |

**完了基準**: `OVERLAY_BACKEND=remotion` で本番フルランが通る。subtitle スタイルを
yaml で切替えられる。

### Phase 3: Player UI 統合 (= 1-2 週間)

| 変更                                                                                                |
| --------------------------------------------------------------------------------------------------- |
| `frontend/src/components/stages/StageOverlay.tsx` の `<video>` を `<Player>` に置換                 |
| 手動チャンク編集が **リアルタイム反映** (= 焼き直し待ち消滅)                                        |
| `useRenderPlan` hook 新設 (= /api/projects/<TS>/render-plan を SWR で polling)                      |
| 字幕 Y 位置エディタを `<Player>` 内 overlay に統合                                                  |
| 既存 ffmpeg overlay の preview (= overlaid.mp4 直接再生) を deprecate、Remotion `<Player>` に一本化 |

**完了基準**: UI で字幕編集 → 即時 preview 反映 → 「保存して焼き直し」で出力が UI と
ピクセル一致。

### Phase 4: パーツレジストリ拡充 (= 3-4 週間)

| カテゴリ追加                                                                                                                |
| --------------------------------------------------------------------------------------------------------------------------- |
| `transitions.yaml` + 5 components (= cut / dip_to_black / dip_to_white / slide_left / smash_cut)                            |
| `stickers.yaml` + 8 stickers (= exclaim_red / question_mark / heart_pulse / thumbs_up / fire / star / arrow_down / sparkle) |
| `lower_thirds.yaml` + 3 (= name_banner / role_caption / quote_box)                                                          |
| `title_cards.yaml` + 3 (= logo_reveal_v1 / section_break_simple / subscribe_cta_v1)                                         |
| `camera_moves.yaml` + 4 (= none / subtle_zoom_in / ken_burns / dolly_pull_back)                                             |
| `filter_presets.yaml` + 5 (= none / warm_cinematic / cool_blue / monochrome / vintage)                                      |
| 各カテゴリの React component 実装 + Storybook + Vitest                                                                      |
| `IntentCatalog.tsx` (新規) で全カテゴリの一覧 + preview UI                                                                  |
| screenplay editor (= Stage 1 UI) でパーツを enum 選択する UI                                                                |

**完了基準**: screenplay JSON にパーツを書けば Remotion が描画する。各パーツが
Storybook で 1 entry あたり数秒で確認できる。

### Phase 5: platform variant + audio parts (= 2-3 週間)

| 変更                                                                                                |
| --------------------------------------------------------------------------------------------------- |
| `compositions/Screenplay{Youtube,Instagram,TikTok}.tsx` 実装                                        |
| `outro_ctas.yaml` + 各 platform 用 entry                                                            |
| `bgm_tracks.yaml` + 5 tracks (= ducking 仕様込み)                                                   |
| `sfx.yaml` + 8 (= whoosh / ding / pop / drum_hit / transition_swoosh / chime / impact / click)      |
| `routes/final_publish.py`: `--platform` で template 切替 + `output/reels_<TS>__<platform>.mp4` 生成 |
| `final_versions[]` に `template` フィールド追加                                                     |
| Stage 8 publish 経路で platform 別 mp4 を自動 register                                              |

**完了基準**: 1 screenplay から `--publish youtube` / `--publish instagram` / `--publish tiktok` で
3 種類の mp4 を出せ、それぞれ platform 最適化されている。

### Phase 6 (任意): novel intent 自動検出 / catalog ガバナンス (= 2 週間)

| 変更                                                                                |
| ----------------------------------------------------------------------------------- |
| analyze pipeline で `confidence < 0.7` のシーン群から `suggested_intents.json` 出力 |
| 運用者レビュー UI (= IntentCatalog 内に「提案」タブ)                                |
| 採用された提案を yaml に書き戻す + `grow_clip_pool.py` を裏で起動                   |

### Phase 7 (任意): 旧 free-text 経路の deprecation (= 半年運用後判断)

| 変更                                                                                                |
| --------------------------------------------------------------------------------------------------- |
| 旧 `bg_cache.py` / `kling_cache.py` の per-line key 経路を deprecate (= 警告のみ、廃止は更に半年後) |
| `_override_*` 経路は残す (= novel intent / 緊急対応用 escape hatch)                                 |
| `cache/bg_images/` / `cache/kling_videos/` を archive 移動                                          |

---

## 10. 影響範囲

### 10.1 新規ファイル

| ファイル                                                                         | 内容                                                        |
| -------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `clip_library.py`                                                                | Layer 1 (= identity/annotation/provenance, lookup, variant) |
| `compositor_remotion.py`                                                         | Layer 3 backend (= render_plan 組み立て + Remotion 起動)    |
| `routes/render_plan.py`                                                          | GET /api/projects/<TS>/render-plan                          |
| `routes/clip_library.py`                                                         | GET/POST /api/clips/\* (= 一覧 / 承認 / blacklist / grow)   |
| `routes/part_registry.py`                                                        | GET /api/parts/\* (= catalog 表示用)                        |
| `scripts/grow_clip_pool.py`                                                      | variant pool 成長                                           |
| `scripts/migrate_clip_pool.py`                                                   | character_refs 等の入替で旧 pool を新 pool に移行           |
| `scripts/approve_clip.py` / `scripts/blacklist_clip.py`                          | CLI lifecycle 操作                                          |
| `config/part_registry/*.yaml` (= 12 カテゴリ)                                    | enum SSOT                                                   |
| `frontend/remotion/Root.tsx`                                                     | registerRoot                                                |
| `frontend/remotion/compositions/Screenplay{Base,Youtube,Instagram,TikTok}.tsx`   | platform 別 composition                                     |
| `frontend/remotion/components/{PartRenderer,SceneSequence,GlobalPartsLayer}.tsx` | 共通 dispatch + scene 描画                                  |
| `frontend/remotion/parts/<category>/*.tsx` + `index.ts`                          | 各 part の React 実装                                       |
| `frontend/remotion/PartRegistry.ts`                                              | id → component 統合 lookup                                  |
| `frontend/remotion/schemas/renderPlan.ts`                                        | Zod スキーマ                                                |
| `frontend/src/pages/IntentCatalog.tsx`                                           | 全カテゴリの一覧 + preview + 承認 UI                        |
| `frontend/src/hooks/useRenderPlan.ts`                                            | /api/projects/<TS>/render-plan の SWR fetch                 |
| `tests/test_clip_library.py`                                                     | identity/annotation/variant 選択                            |
| `tests/test_compositor_remotion.py`                                              | render_plan 組み立て                                        |
| `tests/test_pipeline_e2e_compositional.py`                                       | フルラン                                                    |
| `frontend/remotion/__tests__/parts/**/*.test.tsx`                                | 各 part の単体テスト                                        |

### 10.2 修正ファイル

| ファイル                                          | 修正内容                                                                                                                      |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `screenplay_validator.py`                         | identity / annotation / scene_parts / global_parts のオプショナル受入 + part_registry 整合性チェック                          |
| `scene_gen.py`                                    | `resolve_scene_visual` を新設、identity あり scene は clip_library 経由                                                       |
| `staged_pipeline.py:run_overlay`                  | backend dispatch (= `OVERLAY_BACKEND` 切替)                                                                                   |
| `staged_pipeline.py:run_bg` / `run_kling`         | identity あり scene は clip_library cold path、無い scene は従来経路                                                          |
| `config.py`                                       | `OVERLAY_BACKEND` / `REMOTION_CONCURRENCY` / `CLIP_LIBRARY_VERSION` / `CLIP_POOL_TARGET_SIZE` / `CLIP_POOL_MAX_TOTAL_GB` 追加 |
| `frontend/src/components/stages/StageOverlay.tsx` | `<video>` を `<Player>` に置換                                                                                                |
| `frontend/src/components/stages/StageScript.tsx`  | identity / annotation / scene_parts の編集 UI 追加                                                                            |
| `frontend/package.json`                           | `remotion` / `@remotion/player` / `@remotion/cli` / `zod` 追加                                                                |
| `frontend/src/types.ts`                           | RenderPlan / ScenePart / GlobalPart 型を export                                                                               |
| `routes/final_publish.py`                         | `--platform` で template 切替                                                                                                 |
| `final_import/core.py`                            | `final_versions[]` に `template` フィールド追加                                                                               |
| `CLAUDE.md`                                       | Stage 6/8 のセクションに本設計の概要を追記                                                                                    |
| `docs/developments/architecture.md`               | 3 layer モデルの図と説明を追加                                                                                                |
| `docs/abstract-screenplay-design.md`              | identity/annotation/parts の関係を追記                                                                                        |

### 10.3 削除予定 (= 当面残す)

- `compositor.py` (= ffmpeg backend) — フォールバック / CI として維持
- `bg_cache.py` / `kling_cache.py` の旧 key 経路 — `_override_*` 経路で利用継続
- ffmpeg drawtext 経由の `_build_overlay_filter` — Phase 7 で deprecate

---

## 11. テスト戦略

### 11.1 ユニット (Python)

| 対象                   | 観点                                                                                                               |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `_identity_matches`    | character / location / start_emotion / camera_distance のいずれかが違うと false                                    |
| `_annotation_score`    | visual_intent_id 完全一致 +3.0、互換セット +1.5、不一致 +0、duration_bucket / motion_intensity の +1.0 / +0.5 加点 |
| `select_variant`       | 同じ (ts, scene_idx) で同じ entry、別 ts で分散する                                                                |
| `register_clip_entry`  | pending_review で登録、active への昇格条件                                                                         |
| `lookup_clip_pool`     | identity 不一致は除外、active のみ、blacklisted は除外                                                             |
| `screenplay_validator` | identity 必須化 (override 無し時) / part_registry 整合性 / requires チェック                                       |
| `build_render_plan`    | scene 実尺の解決 / subtitle anchor 解決 / part 時刻の絶対秒変換                                                    |

### 11.2 ユニット (Remotion / TS)

| 対象                                  | 観点                                                  |
| ------------------------------------- | ----------------------------------------------------- |
| `parts/subtitles/MinimalSubtitle`     | text / fontSize / color の props で見た目が変わる     |
| `parts/subtitles/KaraokeBoldSubtitle` | wordTimings の各 word が指定 frame でハイライトされる |
| `parts/transitions/DipToBlack`        | from / duration で fade-out → black → fade-in する    |
| `parts/stickers/ExclaimRed`           | spring animation で scale が遷移                      |
| `PartRenderer`                        | 不正な (category, id) は Error throw                  |
| `compositions/ScreenplayBase`         | scenes の順序 / global_parts の重ね順                 |

### 11.3 統合 / e2e

| テスト                                                                                                                    |
| ------------------------------------------------------------------------------------------------------------------------- |
| `test_pipeline_e2e_compositional`: 新 screenplay でフルラン → output mp4 が生成され ffprobe で 1080x1920 / 60fps          |
| `test_clip_pool_screenplay_invariance`: 別 screenplay 2 本で同 identity の scene があるとき、同 entry が hit              |
| `test_clip_pool_warm_up`: 同じ identity を 10 回 generation → 11 回目以降 hit                                             |
| `test_remotion_vs_ffmpeg_psnr`: ffmpeg backend と Remotion backend で同 screenplay を render → PSNR 30dB 以上             |
| `test_platform_variants`: 同 screenplay から `--publish` 3 platform で別々の mp4 が生成、各 outro_card が正しく入っている |

### 11.4 シミュレーション

`tests/sim/test_clip_pool_hit_rate.py`: 過去 N 本の screenplay を順次流して hit 率を
プロット。20 本で 50%、50 本で 80% を目標。

---

## 12. リスクと対策

### 12.1 技術リスク

| リスク                                                                 | 影響  | 対策                                                                                                                        |
| ---------------------------------------------------------------------- | ----- | --------------------------------------------------------------------------------------------------------------------------- |
| Node + Chromium 依存追加                                               | 中    | ffmpeg backend を残す。CI で `playwright install chromium` を pre-step に置く                                               |
| Remotion render が ffmpeg overlay より遅い                             | 中    | 計測して 2x 以内なら許容。`--concurrency` を上げる。それでも遅い場合 Phase 2 を保留                                         |
| Player の `<Video>` ブラウザ再生がフレーム精度ない                     | 低    | Player と最終 render で微妙な差は許容差として明文化 (= ±2px / ±1 frame)                                                     |
| Composition の見た目が ffmpeg overlay と完全一致しない                 | 低-中 | Phase 0 で目視 + PSNR 比較。許容できる差にとどまるか確認。違いが大きい場合は Remotion 側のフォント描画を調整                |
| identity 一致が false-positive 起こす (= 視覚不一致クリップが選ばれる) | 中    | Phase 1 では identity 4 次元 + camera_distance を hard 必須。運用で誤マッチが見つかったら invariant を強化                  |
| visual_intent vocabulary の発展性                                      | 低    | yaml に `compatible_with` を持つこと、`deprecated` で旧 id を温存できることが対策                                           |
| TikTok karaoke 用 word-level timestamps の取得失敗                     | 中    | `metadata.json.tts_alignment` が無い TS では karaoke を無効化、`subtitle_style.requires` チェックで validator が事前 reject |
| L2 (audio_clip) の per-line cache 化が prosody を壊す                  | 中    | Phase 1-5 では L2 を実装しない。one-shot TTS の prosody 連続性を維持                                                        |

### 12.2 運用リスク

| リスク                                          | 対策                                                                                                                                                       |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 「字幕の SSOT が 2 箇所?」                      | タイミング解決 (= `_resolve_subtitle_timings` / `_split_into_chunks`) は backend 側に固定。Remotion は **解決済みの値を表示するだけ** という不変条件を厳守 |
| CLAUDE.md「指示の範囲を超えない」からの逸脱誘惑 | パーツ追加は人間レビュー必須。screenplay の意図しない演出追加 (= sticker を勝手に挿入する等) は禁止                                                        |
| vocabulary 設計が大変                           | カテゴリごとに段階導入。subtitle / transition / sticker から開始して運用しながら他カテゴリ追加                                                             |
| screenplay schema が肥大化                      | scene_parts / global_parts はすべて optional。書かなければ default が当たる                                                                                |
| storage 肥大 (= 100GB 規模)                     | LRU + TTL + 上限。`config.CLIP_POOL_MAX_TOTAL_GB` で gating                                                                                                |
| 過去 screenplay の互換性                        | 旧 screenplay は free-text path で動く。Phase 7 まで強制移行しない                                                                                         |
| Remotion render 失敗時のリカバリ                | `OVERLAY_BACKEND=ffmpeg` への即時 fallback path を残す                                                                                                     |

### 12.3 採算性

| 項目                               | 影響                                                                                                                       |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| AI 課金 (Kling/Imagen/TTS/Sync.so) | warm 状態で **TTS + Sync.so のみ**。BG / Kling 課金 = 0 (= cold は通常通り)                                                |
| CPU 時間 (Remotion render)         | ffmpeg の 1-2 倍。platform 3 種で 3 倍                                                                                     |
| storage                            | clip pool 100GB 規模 (= 10 variant × 100 intent × 20 (char × loc) × 5MB)                                                   |
| 開発時間                           | Phase 0-5 で計 10-14 週間 (= Phase 4 のパーツレジストリが最重)                                                             |
| 学習コスト                         | Remotion 経験者がいないため、Phase 0 を学習に充てる                                                                        |
| ROI                                | 1) AI 課金大幅減 2) UI と最終出力一致 3) platform 別自動最適化 4) パーツ単位で iteration が高速化 — **2-4 が複合的に効く** |

---

## 13. 開く議論 (= レビュー時の論点)

1. **identity に `camera_distance` を含めるか?**
   - 含める → hit 率は下がるが視覚一貫性は高い
   - 含めない → hit 率上がるが画角ズレ
   - **暫定推奨**: 含める。寄り/引きが混ざる違和感 > hit 率の差

2. **variant 選択の決定論性: ts vs screenplay_content**
   - 案 A: `seed = sha256(ts + scene_idx)` (= project ごと固定、同 screenplay 別 project で変動)
   - 案 B: `seed = sha256(screenplay_content + scene_idx)` (= 同内容なら project 跨いで同一)
   - **暫定推奨**: 案 A。レビュー / 修正サイクルが安定する

3. **L2 (audio_clip cache) を実装するか**
   - 現状 one-shot TTS の prosody 連続性は重要
   - per-line cache 化すると分断
   - **暫定推奨**: Phase 1-5 では実装しない。運用データを見て判断

4. **`OVERLAY_BACKEND` の切替単位は project ごと? グローバル?**
   - 案 A: グローバル (= `config.OVERLAY_BACKEND`) — シンプル
   - 案 B: project ごと (= `metadata.json.overlay_backend`) — A/B 比較しやすい
   - **暫定推奨**: 案 A で開始、Phase 5 完了時に必要なら案 B 拡張

5. **Phase 5 の platform variant: 同時生成 vs 都度生成**
   - 案 A: Stage 6 完了時に 3 platform 同時生成 (= 公開時に選ぶだけ)
   - 案 B: Stage 8 公開時に指定 platform のみ生成 (= 必要分だけ)
   - **暫定推奨**: 案 B。CPU 時間節約 + 使わない platform を avoid

6. **vocabulary の owner**
   - 誰が `visual_intents.yaml` 等の追加・廃止を判断するか
   - 提案 → 運用者レビュー → 承認 のフロー必要
   - **暫定推奨**: PR + IntentCatalog UI の「提案」タブで管理

7. **CLAUDE.md「指示の範囲を超えない」と outro_card 等の自動追加**
   - YouTube template が outro_card を自動付与するのは越権では?
   - **暫定推奨**: outro_card のテキストは **screenplay JSON で明示** (= `global_parts.outro_card.id`)。
     template はその id があれば描画、無ければスキップ。template が **勝手に追加することはしない**

8. **Phase 7 の旧 free-text 経路 deprecation のタイミング**
   - 半年運用後に判断
   - novel intent の cold path として `_override_*` は残す
   - **暫定推奨**: deprecation = 警告のみ。物理削除は更に半年後

---

## 14. 完了条件

全 Phase 完了時:

- ✅ screenplay は完全宣言的 (= identity + annotation + scene_parts + global_parts)
- ✅ 旧 free-text screenplay も後方互換で動く
- ✅ `cache/clips/<entry_id>/` に variant pool が蓄積
- ✅ 同 identity の異なる screenplay が同 clip を hit する
- ✅ `OVERLAY_BACKEND=remotion` で本番フルランが通る
- ✅ `<Player>` と最終 render が見た目ピクセル一致
- ✅ `--publish youtube/instagram/tiktok` で platform 別 mp4 が自動生成
- ✅ AI 課金は warm 状態で **TTS + Sync.so のみ** に縮退
- ✅ 12 カテゴリのパーツが yaml + React component で実装済み
- ✅ IntentCatalog UI で全カテゴリ + clip pool が可視化
- ✅ `data/cost_records.jsonl` に Remotion render 時間が記録され、ffmpeg backend の 2x 以内
- ✅ ドキュメント (CLAUDE.md / architecture.md / abstract-screenplay-design.md) が更新済み
- ✅ 旧 ffmpeg backend は当面フォールバックとして残存

---

## 15. 次アクション

1. **本ドキュメントをレビュー** して §13 の論点を解決
2. Phase 0 (= 1 週間、学習 + minimum viable) を着手するかの判断
3. Go なら以下を並行着手:
   - `frontend/remotion/` のセットアップ (= `npm install remotion @remotion/player @remotion/cli zod`)
   - 既存 1 TS で Hello World render
   - `clip_library.py` の identity / annotation データ構造実装 (= まだ lookup は繋がない)
4. Phase 0 完了時に Phase 1 / Phase 2 の並行性を再判断 (= Phase 1 は Python 中心、
   Phase 2 は TS 中心なので人/時間に応じて並行可能)

**ステータス**: 本ドキュメントは proposal。実装着手は未承認。
本書は前 2 doc (= remotion-integration-design / clip-library-architecture) を **supersedes**
するため、実装着手承認時に旧 2 doc に「→ 2026-05-10_compositional-architecture.md に統合済み」の
ヘッダーを追記する。
