# Stage 2 TTS の per-character voice 化 (N 並列フル生成 → 切出 → マージ)

**日付**: 2026-05-17
**ブランチ**: `feat/per-character-tts`
**前提**: PR #200 (= speaker auto-fill) + PR #201 (= 5 キャラに voice_id 割当) 完了済み

---

## 1. 目的と背景

### 現状

Stage 2 は `scene_gen.py:1534 generate_screenplay_tts_one_shot()` が **screenplay 全体を 1 ElevenLabs API call** で生成する。

- 利点: char-level timestamps による silence-snap で line 境界が正確、screenplay 全体に渡る prosody continuity (= 抑揚・間・pacing の連続性) が保たれる
- 制約: `voice_id` は `config.ELEVENLABS_VOICE_ID` 一つ固定、全 line が同じ声で再生される

`characters/<base>/voice.json` に PR #201 で `voice_id` を割り当て済だが、scene_gen が読まないため **dead field** のまま。

### ゴール

複数キャラが登場する screenplay で **各キャラを異なる ElevenLabs voice で発話** させる。ただし:

- **prosody continuity を最大限維持** (= 各キャラが screenplay 全体の文脈を「読んだ」結果から自分のセリフを切り出す)
- **後方互換**: 単独キャラ動画 (= 既存 screenplay) は完全に同じ挙動・同じコスト
- **既存の下流契約を破らない**: 出力アーティファクト (`tts_full.mp3` / `audio_<S>.m4a` / `tts_meta.json`) のスキーマと使い方は変わらない

### 手法 (= ユーザ提案の "N 並列フル生成 → 切出 → マージ")

n 人の登場人物がいるとき:

1. **n 回 ElevenLabs API を並列に呼ぶ**。各 call は同じ screenplay 全文を別 voice_id で生成
2. 各 voice の char-level timestamps から line 境界を silence-snap
3. line 順に「その line の話者の voice」から該当区間を切出して concat
4. 最終 `tts_full.mp3` は人によって違う声が混在した形になる

この方式の優位性:

- voice A も voice B も **screenplay 全体を読んだ上で** 各自の line を発話している → 「相手が喋ったあと自分が引き取る」抑揚が自然
- block 分割方式 (= 別案) と比べて各キャラの prosody が分断されない

代償:

- API 課金が n 倍 (= 単独キャラの 2 倍 / 3 倍 ...)。短尺動画では絶対値は小さい (= 1 動画あたり ~\$0.04 〜 \$0.12)
- per-voice の intermediate file が増える (= `tts_full.<base>.mp3` × n)

---

## 2. 設計

### 2.1 データフロー

```
[screenplay snapshot]
  ├ scenes[].lines[].speaker  ← compose-resolved base id (例: "f1")
  └ featured_characters       ← resolved ref list

         ↓ (1) speaker 集約
[unique speakers]  = sorted set of all line.speaker (= base id)
                     ※ speaker 未設定 line は "primary speaker" (= 最頻出 base) に fall-back

         ↓ (2) speaker 毎に voice 解決 (= 3 段 fallback)
[voice spec per speaker]
  base → (voice_id, voice_overrides)
    優先順: line.voice_overrides > characters/<base>/voice.json > config.ELEVENLABS_VOICE_ID

         ↓ (3) per-voice 並列フル生成 (= ThreadPool)
[per-voice artifacts]
  tts_full.<base>.mp3          ← その voice で screenplay 全文を発話した音声
  tts_full.<base>.json         ← char-level timestamps
  tts_full.<base>.text_meta.json ← per-voice cache (text_hash)

         ↓ (4) per-voice silence-snap (= 既存ロジックを per-voice で再利用)
[per-voice line bounds]
  bounds[base][line_idx] = (start_sec, end_sec)  ← その voice の audio 内の絶対時刻

         ↓ (5) line 順に cut & concat
[final merged audio]
  tts_full.mp3 = concat([
    cut(tts_full.<line.speaker>.mp3, bounds[line.speaker][line_idx])
    for line in all_lines
  ])
                + line 境界に短い silence (~50ms) を speaker 切替時のみ挿入

         ↓ (6) merged timeline で line.start/end を再計算
[downstream artifacts (= 既存契約と同一)]
  tts_full.mp3
  per-line: tts_<S>_<L>.mp3        ← merged tts_full.mp3 から切出 (= 既存ロジック)
  per-scene: audio_<S>.m4a         ← per-line を concat (= 既存ロジック)
  tts_meta.json                    ← {scenes: [{duration, lines: [{start, end}]}]}
```

### 2.2 単独話者ケース (= 完全後方互換)

`unique speakers` が **1 つだけ** (= 単独キャラ動画) または **0 個** (= speaker 未設定で fallback も無効) の場合、**既存の one-shot path をそのまま実行** する:

- `tts_full.mp3` を 1 call で生成 (= per-voice 中間ファイルは作らない)
- 既存の cache key (`text_hash`) もそのまま再利用 → **既存 project の cache hit が壊れない**

この分岐により、現行 screenplay (= 単独キャラがほとんど) に対しては zero-cost / zero-behavior-change が保証される。

### 2.3 voice 解決の 3 段フォールバック

```python
def resolve_voice_for_line(line: dict, sp: dict) -> tuple[str, dict]:
    """line と screenplay から (voice_id, voice_overrides) を引く。

    優先順位:
      1. line.voice_overrides.voice_id (= ナレーター行などの例外)
      2. characters/<base>/voice.json.voice_id (= キャラ既定)
      3. config.ELEVENLABS_VOICE_ID (= グローバル既定)

    voice_overrides (stability/style/similarity_boost) も同じ階層で merge:
      character.voice_overrides をベースに line.voice_overrides を上書き、
      最後に config 既定 (= ELEVENLABS_VOICE_STABILITY 等) を欠落補完。
    """
```

`load_character_meta()` (`analyze/character_meta.py:161`) は現状 `voice_overrides` のみ読むので、**`voice_id` field を追加で読む** ように `CharacterMeta` dataclass を拡張する。

### 2.4 cache 戦略

| アーティファクト                          | cache key                                              | 影響範囲                                        |
| ----------------------------------------- | ------------------------------------------------------ | ----------------------------------------------- |
| `tts_full.<base>.text_meta.json`          | sha256(full_text + voice_id + voice_overrides + speed) | per-voice。voice_id 変更で当該 voice のみ regen |
| 単独話者の `tts_full.text_meta.json`      | sha256(full_text + voice_id + speed) (= 既存と同じ)    | 既存 project とビット互換                       |
| 最終 `tts_full.mp3` (= multi-voice merge) | 派生 (= 都度ビルド)                                    | per-voice cache 全 hit なら数秒で再ビルド       |

multi-voice の最終 mp3 は**毎回 cut & concat で再ビルド** する設計。理由:

- 入力 (= per-voice mp3 群 + screenplay の line 順) からは決定論的
- ffmpeg concat は秒オーダ、ElevenLabs call (= 数十秒) と比較して無視できる
- screenplay の line 並び順や speaker 割当を変えた場合に cache invalidation が複雑になるのを避ける

### 2.5 並列化

`concurrent.futures.ThreadPoolExecutor(max_workers=min(n, 4))` で並列実行。

- ElevenLabs API は voice_id 単位で並列呼出可能 (= レート制限内なら)
- N=5 の上限は本プロジェクトのキャラ数 (= 現実的に動画 1 本に 3 人以上は稀)
- 1 voice 失敗時は **fail-fast** で全体 retry (= 部分的なリトライは cache 複雑度を上げる)

### 2.6 speaker 切替境界の自然さ

speaker が切り替わる line 境界では:

- 既存の silence-snap が各 voice の audio 内で **line 末尾に短い silence を残す** → concat で自然な間ができる
- 追加で **50ms の無音 buffer** を speaker 切替境界のみ挿入 (= click 音 / 急な声色変化を緩和)
- 同 speaker の連続 line は無音 buffer 無し (= 既存の per-line cut & concat と同じ挙動)

将来エンハンス候補: 20-30ms の linear crossfade (= 必要なら audio_dynamics.py に utility 追加)。

### 2.7 line.speaker の fall-back

`line.speaker` が空 / unknown の line に対しては:

- screenplay 全体で最も多く登場する speaker (= "primary speaker") を当てる
- 単独話者ケースと同様、`unique speakers` が結局 1 になるなら旧 path を選ぶ

これにより analyze 出力で稀に speaker 欠落が起きても fail せず動く。

---

## 3. 触る module / 触らない module

### 触る (= 新規 + 修正)

| ファイル                                     | 修正内容                                                                                                       |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `analyze/character_meta.py`                  | `CharacterMeta.voice_id` field 追加 + load/save 対応                                                           |
| `scene_gen.py`                               | per-character orchestrator 新設、`_full_screenplay_voice_settings()` を per-voice に置換、cut & merge ロジック |
| 新規 `tts/per_character.py` (= 関数群を分離) | `resolve_voice_for_line()` / `collect_unique_speakers()` / `merge_per_voice_to_final()` 等                     |
| `tests/test_screenplay_tts_one_shot.py`      | 既存 single-speaker テストは保持、multi-speaker テスト追加                                                     |
| 新規 `tests/test_per_character_tts.py`       | helper 関数単体テスト                                                                                          |

### 触らない (= 契約維持)

| ファイル                                | 理由                                                                           |
| --------------------------------------- | ------------------------------------------------------------------------------ |
| `elevenlabs_client.py`                  | 1 call API client は再利用、変更不要                                           |
| `staged_pipeline.py`                    | `regen("tts", ...)` のエントリは不変 (= scene_gen の関数名のみ refactor)       |
| `routes/stages.py`                      | POST /api/projects/<ts>/regen は不変                                           |
| `analyze/compose.py`                    | line.voice_overrides の merge ロジックは既に正しい (= dead field を生かすだけ) |
| Stage 4-6 の audio chain                | per-scene `audio_<S>.m4a` の生成契約は不変                                     |
| frontend (Stage 1 UI / Stage 2 preview) | 既存 UI のまま、speaker mapping は既に編集可能                                 |

---

## 4. テスト戦略

### 単体テスト (`tests/test_per_character_tts.py`)

| 関数                              | テスト観点                                                  |
| --------------------------------- | ----------------------------------------------------------- |
| `resolve_voice_for_line`          | 3 段 fallback (line override → char → config)               |
| `collect_unique_speakers`         | 0 / 1 / N 人ケース、speaker 欠落 line の fall-back          |
| `compute_per_voice_cache_key`     | voice_id 違いで異なる key、voice_overrides 違いで異なる key |
| `_cut_voice_segment`              | char_ts から start/end を引いて ffmpeg trim できる          |
| `_merge_concat_with_speaker_gaps` | 同 speaker 連続 = gap なし、speaker 切替 = 50ms silence     |

### 統合テスト (`tests/test_screenplay_tts_one_shot.py` 拡張)

| シナリオ                 | assertion                                                                                                    |
| ------------------------ | ------------------------------------------------------------------------------------------------------------ |
| 単独 speaker (= 既存)    | 既存テストが全て pass、tts_full.<base>.mp3 は作られない                                                      |
| 2 speaker                | API mock が **2 回** 呼ばれる、tts_full.f1.mp3 / tts_full.m1.mp3 が作られる、最終 tts_full.mp3 は merge 結果 |
| speaker 切替境界         | speaker が変わる line の start に 50ms silence が入っている                                                  |
| キャラ voice_id 不在     | config.ELEVENLABS_VOICE_ID にフォールバック、cache key も config voice_id                                    |
| cost 記録                | record_tts() が n 回呼ばれる、各 call の characters 数が full_text length                                    |
| force=False で部分 regen | 1 voice の cache が valid なら再呼出しスキップ                                                               |

### Mock 戦略

既存テストと同じく `elevenlabs_client.generate_speech_with_timestamps` を mock し、voice*id 別に異なる stub を返す。`_extract_audio_segment` / `\_concat_audios*\*` も既存と同じく dummy file + dict tracking で検証する。

---

## 5. フェーズ分割 (= 各 phase 1 commit)

| Phase | 内容                                                                                 | 期待 diff size |
| ----- | ------------------------------------------------------------------------------------ | -------------- |
| 1     | `CharacterMeta.voice_id` 拡張 + load_character_meta 改修 + tests                     | ~80 LOC        |
| 2     | per-voice full TTS 生成関数 (`_generate_per_voice_full_audios`) + cache + tests      | ~250 LOC       |
| 3     | cut & merge ロジック (`_merge_per_voice_to_final`) + tests                           | ~200 LOC       |
| 4     | orchestrator refactor (= `generate_screenplay_tts_one_shot` を分岐) + 後方互換 tests | ~150 LOC       |
| 5     | docs (CLAUDE.md / abstract-screenplay-design / overview / 本 doc)                    | ~50 LOC        |

各 phase で:

- 既存テストが全て pass
- 新規テストが pass
- 単独話者シナリオの bit-exact 互換を verify

---

## 6. 不変条件 (= 崩れたら危険)

1. **後方互換**: 単独話者の挙動・出力・cache は **bit-exact で同一** (= 既存 project の tts_full.mp3 が cache hit する)
2. **下流契約**: `tts_full.mp3` / `audio_<S>.m4a` / `tts_meta.json` のスキーマと意味は不変。Stage 4-6 は無変更
3. **silence-snap は per-voice**: voice A の line 5 を cut するとき voice A の timestamps + voice A の silence-snap を使う。voice B のを流用してはいけない
4. **コスト記録の正確性**: n 並列なら record_tts() が n 回。1 回だけだと cost dashboard が壊れる
5. **fail-fast**: 1 voice の API call が失敗したら全体を fail (= 部分的な mp3 を出さない)。retry は呼出元 (`staged_pipeline.regen`) に任せる

---

## 7. 関連 PR / 履歴

- PR #200 (= speaker auto-fill in analyze) — multi-speaker 検出の前提
- PR #201 (= 5 キャラに voice_id 割当) — voice_id データの前提
- 本 PR で **dead field だった voice.json.voice_id を生かす** → ようやく per-character TTS が動く

---

最終更新: 2026-05-17
