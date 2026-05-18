# Clip Library — 動画キャッシュの階層判定

Stage 3 (= 背景画像) / Stage 4 (= Kling V3 動画) で生成された raw asset を
別 project でも使い回すための階層キャッシュ。コスト削減 (= Imagen / fal.ai
の API 課金を回避) + 速度向上が目的。

実装は `bg_cache.py` / `kling_cache.py` に対称構造で配置されている。
本ドキュメントは特に L2 の fitness formula を中心に、判定階層と設計上の
不変条件を明文化する (= 計画書 §5 透明化要請)。

---

## 1. 全体像

cache 構造 (`cache/<kind>/`):

```
cache/kling_videos/<hash16>.mp4    raw 動画 (5s or 10s)
cache/kling_videos/<hash16>.json   メタ (prompt / model / hit_count /
                                        created_at / last_used_at /
                                        original_audio_duration /
                                        frontload_ratio / quality 状態)
cache/bg_images/<hash16>.png       背景画像
cache/bg_images/<hash16>.json      同 (= 入力 prompt / file sha 群)
```

判定階層 (L1-L4):

| 階層 | 役割                         | 実装                                               |
| ---- | ---------------------------- | -------------------------------------------------- |
| L1   | cache key 完全一致           | `build_cache_key()` の hash 比較                   |
| L2   | 適合度判定 (= fitness score) | `_evaluate_fitness()`                              |
| L3   | 品質ガード                   | `_evaluate_quality()` (= blacklist / TTL / 承認)   |
| L4   | ユーザ override              | `force_fresh` / project disable / scene 個別 fresh |

L1 で hit しない asset は L2 / L3 を見ずに **必ず** 新規生成。L1 hit
した asset でも L2 / L3 / L4 のいずれかで reject されれば新規生成に
fall through する。

---

## 2. L2 fitness formula (= Kling 動画)

`kling_cache._evaluate_fitness()` は 4 項目を順次判定し、いずれかで
reject されれば fitness = 0.0 になる (= cache hit せず新規生成へ)。
全項目を通過した場合のみ fitness は音声乖離率から導出 (= 最大 1.0)。

### 判定項目

| #   | 項目            | 判定式 (= 通過条件)                          | 失敗時     | 設定定数                                        |
| --- | --------------- | -------------------------------------------- | ---------- | ----------------------------------------------- | ------ | ------------------------------------------------ |
| 1   | 動作完了点      | `new_dur >= kling_dur × frontload - 0.05`    | reject     | `config.ACTION_FRONTLOAD_RATIO`                 |
| 2   | slow_mo 上限    | `new_dur <= kling_dur × tol + 0.05`          | reject     | `config.KLING_DURATION_TOLERANCE_RATIO` (= 1.2) |
| 3   | 乖離率 (reject) | `                                            | new − orig | / orig <= threshold`                            | reject | `config.KLING_CACHE_MISMATCH_THRESHOLD` (= 0.30) |
| 4   | 乖離率 (warn)   | `> threshold × 0.5 かつ <= threshold`        | warning    | 同上                                            |
| 5   | camera_distance | `cached == scene` (両者が定義されているとき) | reject     | (なし、enum 不一致は構図破綻のため)             |

### fitness 値の計算式

```
diff_ratio = |new_audio_duration - original_audio_duration| / original_audio_duration
fitness    = max(0.0, 1.0 - diff_ratio)
if rejected: fitness = 0.0
```

| fitness   | 意味                                                  |
| --------- | ----------------------------------------------------- |
| `1.0`     | 完全一致 (= 音声長が cache 時と全く同じ)              |
| `0.7-0.9` | 軽微な乖離 (= subtitle 自動分割で吸収可能な範囲)      |
| `0.5-0.7` | 中程度の乖離 (warning 領域、運用者判断)               |
| `0.0`     | reject (= 4 項目のいずれかで失敗、または乖離率 100%+) |

### 設計上の不変条件 (= 各項目の理由)

- **動作完了点**: 動画の主要モーション (= フロントロード比率分まで) が音声尺
  に収まらないと「動画が途中で切れる」ため再生不能。reject 必須
- **slow_mo 上限**: 音声が映像より長すぎると、slow_mo 延長の限界を超えて
  字幕が映像範囲外にはみ出す。reject 必須
- **乖離率 30% 超**: 動きと音声が合わず違和感が顕著になるため reject。
  15-30% は警告のみで運用者が判断
- **camera_distance**: cached video の被写体サイズと現 scene の意図が
  違うため reject (= close-up cache を medium scene で使うと顔が大きすぎる)

`-0.05` の epsilon は ffprobe の浮動小数誤差を吸収するため。

---

## 3. L3 品質ガード (= Kling 動画)

`_evaluate_quality()` は cache entry の品質 metadata に基づいて reject
判定する:

| 判定         | 条件                                           | 失敗時 |
| ------------ | ---------------------------------------------- | ------ |
| blacklisted  | `quality.blacklisted = true`                   | reject |
| TTL 期限切れ | `quality.ttl_expired_at` 経過                  | reject |
| 未承認       | `quality.approved = false` の状態で TTL 半分超 | reject |
| verify 失敗  | ffprobe で読込不能 / 0 byte                    | reject |

詳細は `kling_cache._evaluate_quality()` および
`docs/plannings/2026-05-10_clip-library-architecture.md` の L3 節を参照。

---

## 4. L4 ユーザ override

- **`force_fresh` (= scene 個別)**: UI で「キャッシュを無視して再生成」を
  選択した scene は L1 hit しても skip する
- **project disable**: `metadata.json.kling_cache_disabled = true` の
  project は cache lookup を完全 skip (= 全 scene 新規生成)
- **bulk decisions**: `bgCache.decisionsBulk(ts, "all-fresh")` / 同 kling
  で全 scene を一括 force_fresh にできる (= StageBG / StageKling の
  「すべて新規生成」ボタン)

---

## 5. 関連設計ドキュメント

- `docs/plannings/2026-05-10_clip-library-architecture.md` — L1-L3 の
  詳細設計、novel intent 提案フロー
- `docs/abstract-screenplay-design.md` — Clip Library の cache lookup key
  (= identity + annotation.visual_intent_id) との関係
- `config.py` の `KLING_*` / `BG_CACHE_*` / `CLIP_*` 関連定数
- `bg_cache.py` / `kling_cache.py` — 実装本体

---

最終更新: 2026-05-18
