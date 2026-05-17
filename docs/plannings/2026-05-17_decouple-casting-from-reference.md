# Casting を参考動画から切り離す (= 元動画に寄せない自由な割当)

**日付**: 2026-05-17
**ブランチ**: `chore/decouple-casting-from-reference`
**前提**: PR #200 (= speaker auto-fill) + PR #202 (= per-character TTS) の上で動く

---

## 1. 背景と方針

PR #200 で「Claude が speaker_profiles を character.appearance と突合して
speaker_to_ref を提案、空欄は Phase D fallback (= gender hard reject + age
preference + distinct rule) で補完」という機構を入れた。これは「参考動画
で **女性が話している** なら同じく女性キャラを割当」という appearance
matching 思想に基づく。

ユーザ方針: **「話者や登場人物を元動画に寄せる必要はなく、台本作成時に
自由に決めていい」**。

つまり、参考動画の登場人物の見た目 / 声と、生成動画のキャラ割当を
**意図的に分離する** ことになる。matching に頼らず、analyze は構成 /
セリフ / 感情 / location のみを抽出して、キャラ割当は **Stage 1 UI で人間
が自由に選ぶ** 方式へ。

## 2. スコープ (= 案 B: UI ヒント維持 + 順番割当)

| 機構                                                         | 現状                                                    | 変更                                                        |
| ------------------------------------------------------------ | ------------------------------------------------------- | ----------------------------------------------------------- |
| `speaker_profiles` 検出 (= gender / age_range / description) | Claude が frame + 音響から推定                          | **維持** (= Stage 1 UI のヒント表示用に有用)                |
| Claude の `speaker_to_ref` 提案 (appearance 突合)            | SYSTEM_PROMPT で「appearance と突合せよ」と指示         | **撤廃** → 「catalog 先頭から順番に割当」に変更             |
| Rule A (wardrobe-by-location)                                | dominant location の `recommended_wardrobes` に合わせる | **維持** (= location に依存、参考動画は無関係)              |
| Rule B (distinct character)                                  | 同 base を複数 speaker に割り当てない                   | **維持** (= 重複防止は引き続き有用)                         |
| Phase D (unmapped fallback)                                  | gender hard reject + age preference + distinct          | **簡素化** → 単純な「未使用 base を alphabetical 順に割当」 |
| `characters/<base>/voice.json.appearance`                    | matching 用データ                                       | **dead field 化** (= 後続 PR で削除可)                      |
| Stage 1 UI (`SpeakerMappingSection`)                         | profile ヒント表示 + analyze 推定バッジ + 自由編集      | **維持** (= 動作も UI も変えない)                           |

### 撤廃しない理由 (= 残すもの)

- **`speaker_profiles` 検出**: Claude 呼出 1 回で副産物的に取れる。UI で「speaker_1 は女性 20 代の声」というヒントを表示できる → ユーザがキャラを選ぶ速度向上
- **Rule B (distinct)**: 「2 人の speaker に同じキャラを割当てない」は元動画と無関係に有用
- **Rule A (wardrobe-by-location)**: location に合わせた wardrobe 選択は元動画と無関係
- **Stage 1 UI ヒント**: 動作は変わらない (= 表示のみ)

## 3. 簡素化後の post-process ロジック

```python
# 旧: 3 stage (Rule B → Rule A → Phase D with appearance matching)
# 新: 3 stage (Rule B → Rule A → Phase D with simple order assignment)

def _fill_unmapped_speakers_simple(
    *, speaker_profiles, cleaned_s2r, character_catalog,
    base_to_refs, loc_to_wardrobes, speaker_to_locs,
):
    """Claude が埋め残した speaker を deterministic に補完。

    アルゴリズム (= appearance に依存しない):
      1. unmapped = speaker_profiles のキー - cleaned_s2r のキー
      2. 各 unmapped speaker を sorted 順に処理 (= 決定論性)
      3. 未使用 base を alphabetical 順に割当
      4. 枯渇したら distinct rule を緩めて先頭から再利用
      5. wardrobe は dominant location の recommended_wardrobes を加味
    """
```

gender 一致 / age 一致 / appearance match score は **全て撤廃**。

## 4. Claude SYSTEM_PROMPT の変更

### 旧 (= appearance 突合)

> speaker_to_ref: speaker_N → resolved id のマッピング。各 speaker の
> speaker_profiles を catalog の appearance と突合し、最も近いキャラを
> 選ぶ。

### 新 (= 単純割当)

> speaker_to_ref: speaker_N → resolved id のマッピング。catalog 内の
> base から順番に 1 つずつ割当てる (= distinct character rule のみ守る)。
> 参考動画の登場人物に寄せる必要は無い (= 台本作成時に Stage 1 UI で
> 人間が自由に選び直す前提)。

prompt が短くなる + Claude の判断負担が減る → 提案精度のブレが減る (= 結局
ユーザが直すなら最初から決定論的な順番割当の方が予測可能)。

## 5. 不変条件 (= 守ること)

1. **後方互換**: 既存 screenplay snapshot の `speaker_to_ref` 値は触らない (= 旧 analyze 出力もそのまま動く)
2. **Phase D は常に全 speaker を埋める**: `speaker_profiles` を持つ全 speaker に必ず 1 entry が入る (= UI で「未選択」が出ない)
3. **distinct rule + wardrobe-by-location は維持**: 元動画と無関係なロジックなので影響しない
4. **per-character TTS は無変更**: speaker → voice_id resolution は変わらない (= `characters/<base>/voice.json.voice_id` 参照のまま)
5. **Stage 1 UI は無変更**: 表示も編集動作も変わらない

## 6. フェーズ分割

| Phase | 内容                                                                                                         |
| ----- | ------------------------------------------------------------------------------------------------------------ |
| 1     | `video_analyzer.py` SYSTEM_PROMPT 簡素化 + `_fill_unmapped_speakers` 簡素化 + `_appearance_match_score` 削除 |
| 2     | 既存テストの appearance 関連 assert を「順番割当」に書換 / 撤廃                                              |
| 3     | `CLAUDE.md` / `docs/abstract-screenplay-design.md` の casting セクション更新                                 |
| 4     | セルフレビュー + PR + squash merge                                                                           |

## 7. ROI

- Claude prompt が短くなる (= token cost 微減)
- post-process が単純化 (= 保守容易性向上)
- 自動 casting が決定論的になる (= 「Claude の気分で f1 / f2 が入れ替わる」現象が消える)
- ユーザは結局 Stage 1 UI で選び直すので、無駄な「賢い推定」は労力の無駄

---

最終更新: 2026-05-17
