# `speaker_to_ref` / `speaker_profiles` schema 撤廃 (= dead 抽象化の手術)

**日付**: 2026-05-17
**ブランチ**: `refactor/drop-speaker-mapping-schema`
**前提**: PR #200-#207 で speaker 周りの defensive 化を一通り完了

---

## 1. 背景と方針

### 現状の課題

`docs/abstract-screenplay-design.md` の **abstract 設計原則** に従って、analyze 出力は:

- `line.speaker = "speaker_1"` (= 匿名 ID)
- `speaker_to_ref = {"speaker_1": "f1__office"}` (= mapping)
- `speaker_profiles = {"speaker_1": {gender: "male", ...}}` (= hint)

の 3 つを書き出し、`compose` が読み出し時に `line.speaker` を resolved 形式に変換する。

設計時の狙い:

1. snapshot を abstract (= 匿名 speaker_N) で保ち、**「同じ台本で別キャラ版を作る」が容易になる**
2. analyze 提案と人間判定を分離
3. cache 鍵 (= identity) が手動入力に依存しない

### 現状の問題

| 狙い                                 | 達成状況                                                |
| ------------------------------------ | ------------------------------------------------------- |
| 元動画依存 bug 解消                  | ✅ 達成 (= identity / location_ref / annotation で完結) |
| **「casting 変えて別キャラ版」機能** | ❌ **一度も実装されていない** (= 1 年経過)              |
| 分離による拡張余地                   | ❌ **使われていない hypothetical**                      |

つまり **speaker 周りの抽象化レイヤだけが dead asset**。同時に:

- UI に冗長な SpeakerMappingSection が残る (= ユーザの「冗長」report)
- compose の resolution step が必要 (= 複雑性)
- snapshot を見た開発者が「speaker_1 とは? どこで resolve される?」と学習コスト
- `speaker_to_ref` と `line.speaker` の drift bug リスク (= 過去 PR #205-#207 で実際に発生)

### 解決方針 (= 部分的な抽象化撤廃手術)

**「abstract 設計原則」全体は維持** (= identity / location_ref / annotation / Gemini rewrite 等は実用されている)。
**speaker 周りの dead 抽象化のみ撤廃**:

- `analyze` 出力は `line.speaker = "f1__office"` (= resolved 形式) を直接書く
- `speaker_to_ref` / `speaker_profiles` 出力を撤廃
- `compose` の speaker resolution step は撤去 (= dead code 化)
- UI から `SpeakerMappingSection` 撤去、per-line picker に「同 base の全 line に適用」ボタンを追加
- 既存 snapshot の migration script を 1 本提供

---

## 2. 不変条件 (= 守ること)

1. **TTS 出力の bit-exact 同等性**: 同じ caster で同じ screenplay を生成したとき、撤廃前後で audio が一致する
2. **per-character TTS pipeline (PR #202 で実装) は無変更**: `line.speaker` の値が同じなら、TTS の経路と結果は同じ
3. **Stage 3-8 の下流契約は無変更**: location / identity / annotation / 全 stage の generation は無影響
4. **Gemini rewrite phase (PR #204) は無変更**: line.text 置換は speaker 撤廃と直交
5. **既存 project の互換性**: migration script で `temp/<TS>/screenplay.json` を再書き込みすれば動く
6. **character voice.json は無変更**: voice_id / appearance / voice_overrides 共に保持
7. **段階的ゲート方式の強化**: speaker / featured_characters 変更で Stage 2 承認を自動 reset (= PR B)

---

## 3. データ schema の変化

### Before (= 撤廃前)

```jsonc
{
  "caption": "...",
  "featured_characters": ["f1__office"],
  "speaker_to_ref": { "speaker_1": "f1__office" }, // 削除対象
  "speaker_profiles": { "speaker_1": { "gender": "male" } }, // 削除対象
  "scenes": [
    {
      "lines": [
        {
          "text": "...",
          "speaker": "speaker_1", // ← raw 匿名 ID
          "emotion": "中立",
        },
      ],
    },
  ],
}
```

### After (= 撤廃後)

```jsonc
{
  "caption": "...",
  "featured_characters": ["f1__office"],
  "scenes": [
    {
      "lines": [
        {
          "text": "...",
          "speaker": "f1__office", // ← resolved 形式を直接書く
          "emotion": "中立",
        },
      ],
    },
  ],
}
```

### `line.speaker` の許可値

- 撤廃後: **resolved id のみ** (= `"f1"` または `"f1__office"`)
- `speaker_1` などの raw 匿名 ID は **禁止** (= validator で reject)

---

## 4. フェーズ分割

| Phase | 内容                                                                                                                                                                                                                                                 | 期待 diff   |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| 0     | 本 doc                                                                                                                                                                                                                                               | +200        |
| 1     | `video_analyzer.SYSTEM_PROMPT` を resolved 直書き方式に。output schema 例から speaker_profiles / speaker_to_ref 撤廃                                                                                                                                 | ~-150       |
| 2     | `video_analyzer` post-process 撤去: `_fill_unmapped_speakers` / `_appearance_match_score` / casting normalization block / `_compute_speaker_to_locs` 関連、`_apply_speaker_backfill` (PR #206) も削除                                                | ~-300       |
| 3     | `analyze/compose.py` の speaker resolution step 撤去 (= dead code)。`_resolve_speaker_to_ref` 削除、line.speaker を pass-through に                                                                                                                  | ~-100       |
| 4     | `screenplay_validator.py`: speaker_profiles / speaker_to_ref フィールド検証撤去、line.speaker は resolved id のみ許可                                                                                                                                | ~+30 / -50  |
| 5     | `scripts/migrate_speaker_schema.py`: 既存 temp/<TS>/screenplay.json を読み、speaker_to_ref で line.speaker を resolved 形式に焼き込み、speaker_to_ref / speaker_profiles を削除して書き戻し                                                          | +120        |
| 6     | Frontend: `SpeakerMappingSection` 撤去、per-line picker に「同 base の全 line に適用」ボタン追加、`AbstractScreenplay` 型から speaker_to_ref / speaker_profiles 削除、`collectRawSpeakers` / `hasAnalyzeSpeakerProfiles` / `resolveLineSpeaker` 整理 | -300 / +150 |
| 7     | PR B: `staged_pipeline` または `routes/projects` で speaker / featured_characters 変更を検知し Stage 2 承認を自動 reset                                                                                                                              | +80         |
| 8     | docs: `CLAUDE.md` / `abstract-screenplay-design.md` / `overview.md` の関連箇所書換。`abstract-screenplay-design.md` には「speaker 周りの抽象化撤廃」history を追記                                                                                   | +50         |
| 9     | テスト全更新 + ローカル / CI 通過確認 + PR + merge                                                                                                                                                                                                   | -100 / +50  |

**net diff: ~-300 LOC** (= 簡素化が増分を上回る)

---

## 5. 互換性と migration

### analyze 出力の互換性

- 新 analyze: 直接 resolved 形式で書き出す
- 旧 `screenplays/auto_*.json` (= raw + mapping 形式) は **template loader で読込時にその場で migration** する (= ad-hoc compose)
- 旧 template から新規 project 作成は引き続き動く

### snapshot の互換性

- 既存 `temp/<TS>/screenplay.json` は raw / mapping 形式が残っている
- migration script `scripts/migrate_speaker_schema.py` を 1 回実行することで resolved 形式に変換
- migration script は **idempotent** (= 既に resolved なら no-op)

### 既存 project の動作

- migration script 実行前: validator が「raw speaker_N は禁止」で reject → Stage 1 が起動しない
- migration script 実行後: 正常動作

`README` / `CLAUDE.md` に migration 手順を記載。

---

## 6. テスト戦略

### 撤去するテスト

- `tests/test_video_analyzer.py::TestFillUnmappedSpeakers` (= 全 8 件)
- `tests/test_video_analyzer.py::TestBuildScreenplayFillsAllSpeakers` (= 全 3 件)
- `tests/test_video_analyzer.py::TestSpeakerBackfillIntegrity` (= 全 5 件)
- `tests/test_analyze_compose.py` の speaker resolution 関連 (= 数件)
- frontend `tests/test_*.tsx` の SpeakerMappingSection 関連

### 維持するテスト

- per-character TTS (= `test_per_character_tts.py` / `test_build_audios_from_per_voice.py` 全件)
- compose の identity / annotation / location_ref 関連
- screenplay_validator の text / emotion 関連

### 新規追加するテスト

- migration script: raw + mapping → resolved 変換が正しい、idempotent
- screenplay_validator: raw speaker_N を含む snapshot を reject
- frontend SpeakerPicker: bulk-apply ボタンが全 line を更新
- PR B: speaker 変更で Stage 2 承認が unlock

---

## 7. 不変条件のテスト方法

1. **同 screenplay の TTS bit-exact**:
   - 撤廃前に 1 video を run、bytes hash を記録
   - 撤廃後に migration → 同 screenplay → bytes hash 比較
   - 一致を確認
2. **per-character voice 経路の正当性**:
   - 既存 test_build_audios_from_per_voice.py 全 9 件 + test_per_character_tts.py 28 件が pass

---

## 8. リスクと緩和

| リスク                                   | 緩和                                                          |
| ---------------------------------------- | ------------------------------------------------------------- |
| migration script の bug で snapshot 破損 | dry-run mode + バックアップ作成 + idempotent                  |
| 既存 project が起動不能                  | migration を CLI で 1 行実行、エラー時は元に戻す簡易 rollback |
| analyze 旧 template 出力との互換         | template loader で 旧形式 → 新形式の自動変換を 1 リリース挟む |
| frontend type の cascade 影響            | 段階的に削除、各 phase で tsc / vitest pass を強制            |
| 私の見落とし                             | phase 単位 commit、各 phase で全テスト + CI pass を強制       |

---

## 9. 完了条件

- [ ] analyze 出力に `speaker_to_ref` / `speaker_profiles` が含まれない
- [ ] compose に speaker resolution step が存在しない
- [ ] migration script で既存 project 全件が変換できる
- [ ] frontend に SpeakerMappingSection が存在しない
- [ ] per-line picker で bulk-apply できる
- [ ] PR B が動作 (= speaker 変更で Stage 2 unlock)
- [ ] backend tests / frontend tests / CI 全 job pass
- [ ] grep で speaker_to_ref / speaker_profiles の不要参照ゼロ
- [ ] docs (CLAUDE.md / abstract-screenplay-design / overview) が schema 撤廃を反映

---

最終更新: 2026-05-17
