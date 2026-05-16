# wardrobe 自動選定: 判定ロジックによる一貫した casting

> **作成日**: 2026-05-16
> **発端**: 「登場人物と服装も自動で決めるようにしてください。ただし完全ランダムではなく、一貫性と一定のルールに基づいた判定ロジックで選ばれるように」というユーザ要望。
> **前提**: PR #196 で analyze は `featured_characters` / `speaker_to_ref` を提案するが、wardrobe の選択基準が曖昧で、ロケ的に違和感のある衣装が選ばれる可能性がある。

## WHY (= なぜやるか)

PR #196 で casting の自動提案は導入したが、**判定ロジックが Claude の judgement に委ねられており、ロケと衣装の不整合が起きうる**。例: 動画のシーンが全部 `warm_cafe` でくつろいだ会話なのに、Claude が `f1__office` (オフィスカジュアル) を選んでしまう、など。

ユーザは「完全ランダムではなく判定ロジック」を求めているため、**ロケ → 衣装** の決定論的なルールを追加して、選択を予測可能にする。同時に **「別 speaker は別 character」** という暗黙ルールも post-processing で明示的に enforce する。

## WHAT (= 修正の最終形)

### 1. ロケに optional な `recommended_wardrobes` を追加

`locations/<id>.json` (= `Location` dataclass) に optional な `recommended_wardrobes: list[str]` を追加:

```jsonc
{
  "id": "home_office",
  "decor": "...",
  "lighting": "...",
  "camera_distance": "medium-close",
  "recommended_wardrobes": ["office", "casual"],
}
```

各キャラの衣装バリアント名 (`f1__office` → `office`、`f1__casual` → `casual` 等) と突合される。空 / 未設定なら rule は適用されない (= Claude の選択をそのまま使う、graceful)。

### 2. analyze SYSTEM_PROMPT に wardrobe rule を追記

casting 出力ルールに以下を追加:

- 各 speaker の wardrobe を選ぶときは、その speaker が登場する**主要シーンの location** の `recommended_wardrobes` から選ぶこと
- **異なる speaker には異なる base character を割り当てる** (= 同じ顔の人が別人として登場するのは禁止)

### 3. post-processing で判定ロジックを enforce

`video_analyzer.build_screenplay` の casting 正規化に 2 つの rule を追加:

#### Rule A: wardrobe-by-location

各 speaker について:

1. 対応する resolved id (= `<base>__<wardrobe>`) を分解
2. その speaker が登場するシーン (= `lines[].speaker == speaker_N` のシーン) を集計
3. **dominant location** = 最も多くの line を持つシーンの `location_ref` (同数なら最初に出現したもの)
4. dominant location の `recommended_wardrobes` を取得 (= location_catalog から)
5. 以下を全て満たすときのみ wardrobe を swap:
   - dominant location に `recommended_wardrobes` が定義されている
   - 現在の wardrobe がその list に含まれていない
   - 同じ base で、`recommended_wardrobes` に含まれる wardrobe バリアントが character_catalog の refs に存在する
6. swap した場合は `featured_characters` も同期 (= 同 base の旧 ref を新 ref に置換)

#### Rule B: 別 speaker は別 base

- `speaker_to_ref` の値を順に走査
- 既出の base が出てきたら、その speaker のマッピングを **drop** (= 人間が後で対応付ける)
- `featured_characters` から該当 ref を除く

両 rule とも graceful: 失敗条件 (location 未設定、recommended_wardrobes 不在、適合 wardrobe 無し) では何もしない。analyze は rule の適用失敗で fail しない。

### 4. compose / clip_library 側は変更不要

`featured_characters` / `speaker_to_ref` は video-wide のフィールドで、compose はそのまま使う。clip_library の identity (= per-scene の `character_refs`) は compose が `speaker_to_ref` から派生するため、wardrobe の決定はこの post-processing で完結する。

## scope 外 (= 本機能で踏み込まないこと)

- **per-scene wardrobe variation**: 同じキャラが「office シーンでは office、cafe シーンでは casual」と切り替わる挙動。ユーザの要望は「一貫性」なので、video-wide で 1 種類に統一する設計を維持
- **顔/声紋による厳密マッチング**: 既存通り Claude の自然言語マッチに任せる
- **wardrobe 命名規則の強制**: `recommended_wardrobes` の値は character の wardrobe バリアント名と完全一致する前提。揺れがあると swap が効かないが、warning log のみで fail しない
- **既存ロケへの metadata 補完 UI**: hand-edit で設定する想定

## HOW (= phase 分解)

全 3 phase、本セッション内で順次実装する (= worktree `feat/wardrobe-by-location` 上)。

### Phase 1: `Location.recommended_wardrobes` 追加

| 対象                             | 内容                                                                                                                                                                                               |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `analyze/location.py`            | `Location` に optional `recommended_wardrobes: list[str]` 追加 (default empty)。`to_dict` は空なら省略 (= 既存 json を汚さない)。`from_dict` は安全に読み込み。`build_location_catalog()` に含める |
| `tests/test_analyze_location.py` | round-trip / 空省略 / catalog 含有のテスト                                                                                                                                                         |

### Phase 2: SYSTEM_PROMPT + post-processing rule

| 対象                           | 内容                                                                                                                                                                                                                        |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `video_analyzer.py`            | SYSTEM_PROMPT casting 節に wardrobe-by-location rule + 別 base rule を追記。`build_screenplay` の post-processing に Rule A (wardrobe swap) と Rule B (重複 base drop) を実装。location_catalog と character_catalog を併用 |
| `tests/test_video_analyzer.py` | Rule A: dominant location に基づき wardrobe が swap される / 適合 wardrobe 無いと keep / recommended_wardrobes 不在で keep。Rule B: 同 base の 2 件目以降が drop され featured も同期                                       |

### Phase 3: docs 更新

| 対象                                 | 内容                                                                                          |
| ------------------------------------ | --------------------------------------------------------------------------------------------- |
| `docs/abstract-screenplay-design.md` | casting 節に「wardrobe は dominant location の recommended_wardrobes から選定」のルールを記載 |
| `CLAUDE.md`                          | ロケスキーマに `recommended_wardrobes` を追記                                                 |

## 不変条件 (= 守るべきルール)

1. **判定ロジックは graceful**: location に `recommended_wardrobes` 未設定 / 適合 wardrobe 無し / 計算不能なら何もしない (= Claude の選択を尊重)。analyze は fail しない
2. **video-wide consistency**: 1 キャラあたり 1 wardrobe / 1 動画。per-scene 変動は導入しない
3. **人間の訂正が最優先**: post-processing は提案を rule に寄せるだけ、人間が Stage 1 UI で訂正可能 (= 既存 UI 温存)
4. **distinct character**: 異なる speaker は異なる base character を持つ。重複検出時は drop して未マッピング状態に戻す (= 人間に判断を委ねる)

## 検証手順

### Phase 単位

各 phase は実装と同時にテストを書き、該当 test を pass させる。

### 統合検証 (= 全 phase 完了後)

1. **backend full test** — `pytest tests/` 全 green
2. **frontend build + test** — `npm run build` + `npm run test:ci`
3. **機能統合チェック**: `build_screenplay` を mock で呼び、dominant location に基づき wardrobe が swap される / Rule B が同 base 重複を drop することを確認
4. **graceful 確認**: recommended_wardrobes 不在 / location_catalog なしで rule が無効化されることを確認

## 関連ドキュメント

- `docs/plannings/2026-05-15_auto-casting-detection.md` — 本機能の前段。casting 提案の基本設計
- `docs/abstract-screenplay-design.md` — 抽象台本の全体設計。本機能で casting 節を更新
