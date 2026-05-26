# 字幕タイミングを TTS char_ts ベースにする設計

最終更新: 2026-05-26
ステータス: ドラフト (= レビュー待ち)

## 1. 背景と目的

### 現状の課題

1. 1 line を複数 chunk に分割すると、各 chunk の表示位置・長さが実発話とずれる。
2. 原因: `compositor._allocate_chunk_timings` が line.start〜end を **文字数比例** で配分している。実音声は文字数では分布しない (漢字は短く、長音 / 促音 / 句読点は長い) ため、分割するほどずれる。
3. 加えて感情タグ (`[happy]` 等) による char_ts のズレ (実音声より最大 ~0.4s 後ろ) も残る。

### 解決策

- TTS 生成時に得られる **char-level timestamp (char_ts)** を使う。これは eleven_v3 がその合成音声に対して返す forced alignment で、字幕タイミングの正解に最も近い (±10〜30ms)。
- chunk 境界を「文字数比例」でなく「各 chunk の文字が実際に発話される時刻 (char_ts)」で決める。
- char_ts の保存先: 単独話者 `temp/<TS>/tts_full.json`、per-voice `temp/<TS>/tts_full.<base>.json` (= 既存)。

### 今回のスコープ

やること:

- chunk の auto 配分を char_ts 実時刻ベースにする (`compositor`)。
- char_ts (tts_full 全体の絶対時刻) → line 表示窓への座標変換・比率スケール。
- char_ts 不在 / 読込失敗時は従来の文字数比例に fallback (後方互換)。

やらないこと:

- 手動 `subtitles[]` の start/end 明示指定の挙動変更 (= 引き続き優先。`_resolve_subtitle_timings` はそのまま)。
- analyze の Whisper 出力の流用 (= 参考動画の別音声なので使えない。§6 参照)。
- line 単位の start/end (snap 後) の算出ロジック変更 (= 前回の頭切れ修正 PR #351/#352 のまま)。
- **per-voice (複数話者) の char_ts 解決は Phase 2** (今回は単独話者のみ char_ts 経路、複数話者は文字数比例 fallback)。
- Whisper / MFA 等の forced aligner 新規導入。

## 2. アーキテクチャ設計

### 改修箇所

```
compositor.py
  _build_overlay_filter             ← char_ts 読込 + position map 構築を追加
  _compute_line_chunks_and_timings  ← pos_to_time / char_start を opt-in で受け取る
  _allocate_chunk_timings_from_char_ts  ← 新規 (char_ts 実時刻で配分)
  _allocate_chunk_timings           ← fallback として残置 (文字数比例)
config/                             ← SUBTITLE_TIMING_FROM_CHAR_TS フラグ
```

### 依存 (既存資産の再利用)

- `stages/text_mapping.build_screenplay_text(screenplay)` → full_text + line_specs (各 line の char_start/end)。
- `stages/text_mapping.build_position_to_time_map(full_text, char_ts)` → 文字位置 → {start,end} マップ。感情タグの char_ts ズレはこの順次マッチングで吸収される。
- 新規 API / 外部依存は無し。

## 3. 実装設計

### 3.1 char_ts の読込 (`_build_overlay_filter`)

- **責務**: overlay 開始時に `tts_full.json` を読み、`build_position_to_time_map` で `pos_to_time` を構築。各 line の `char_start` を `build_screenplay_text` の line_specs から得て、line ごとに渡す。
- 読込失敗 (ファイル無し / 壊れ / 複数話者) は `pos_to_time=None` とし、全 line を文字数比例 fallback に倒す (= 安全側)。

### 3.2 chunk 境界の char_ts 配分 (`_allocate_chunk_timings_from_char_ts`)

- **責務**: chunks、line の char_start、pos_to_time、line 表示窓 (line_start_abs, line_end_abs) から各 chunk の (start, end) を返す。
- **HOW**:
  1. 各 chunk の文字範囲 `[cursor, cursor+len)` に対応する char_ts の最初の start / 最後の end を引く (= line 内相対の実発話時刻)。
  2. line 全体の char_ts 範囲 (先頭 chunk start 〜 末尾 chunk end) を基準に、各 chunk 境界を比率化する。
  3. その比率を line 表示窓 (line_start_abs 〜 line_end_abs) にスケールして絶対時刻へ変換する。snap や実尺リスケールで char_ts 総長と表示窓長が一致しないため、直接代入でなくスケールする。
  4. 末尾 chunk は line_end_abs に揃える (浮動小数誤差回避)。
- 文字数比例との違いは、配分の重みを「`len(c) / total_chars`」から「`char_ts 時刻幅 / 総時刻幅`」に置き換える点だけ。

### 3.3 fallback と切替

- `pos_to_time` が None、または line の char_ts が引けない場合は `_allocate_chunk_timings` (文字数比例) に委譲する。
- config フラグ `SUBTITLE_TIMING_FROM_CHAR_TS` (既定 True) で全体を切替可能にし、退行時に即座に旧挙動へ戻せるようにする。

## 4. テスト方針

- **単体**: `_allocate_chunk_timings_from_char_ts` が char_ts の時刻幅比で chunk を配分し、line 表示窓にスケールすること。char_ts gap で fallback すること。
- **単体**: 感情タグ付き line で tag 部分が char_ts マッチングで skip され、本文先頭から配分されること。
- **統合**: tts_full.json をモックして `_build_overlay_filter` が char_ts 経路を通り、読込失敗で文字数比例に落ちること。
- **手動**: 分割した字幕が実発話に追従することを実プロジェクトで確認 (overlay 再合成のみ、AI 課金なし)。

## 5. 実装タスク

### Phase 1 (今回実装)

- [ ] 1. `_allocate_chunk_timings_from_char_ts` 新規 + 単体テスト
- [ ] 2. `_compute_line_chunks_and_timings` に `pos_to_time` / `char_start` を opt-in 追加 (無ければ従来配分)
- [ ] 3. `_build_overlay_filter` で char_ts 読込 + position map 構築 + **単独話者**で配線
- [ ] 4. `config.SUBTITLE_TIMING_FROM_CHAR_TS` フラグ + fallback
- [ ] 5. 統合テスト

### Phase 2 (将来)

- [ ] per-voice (複数話者) の `line.speaker` → `tts_full.<base>.json` 解決
- [ ] auto 分割 (`_split_into_chunks`) の分割位置自体を char_ts の無音境界に寄せる

## 6. analyze の Whisper を使わない理由

- analyze の Whisper transcript は **参考動画 (元素材) の人間の音声** のタイミング。字幕は **TTS 生成音声 (合成音)** に焼く。
- 両者は話者・話速が異なり、さらに Gemini 言い換えでテキストも変わる (翻案対策)。話者も別キャラに差し替わる。
- → 参考動画の word timestamps を TTS 字幕に流用すると数百 ms の誤差。char_ts (= TTS 自身の forced alignment) が正解値で、Whisper を再実行する必要もない。

## 7. リスクと対策

- **char_ts 総長 ≠ line 表示窓長** (snap / 実尺リスケール): 比率スケールで吸収する (§3.2)。
- **per-voice の speaker 解決**: Phase 1 は単独話者のみ char_ts 経路。複数話者は文字数比例 fallback で従来通り動かし、Phase 2 で対応する。
- **char_ts の gap** (一部文字に timestamp が無い): 該当 chunk は範囲内の有効 timestamp で補間し、無理なら文字数比例 fallback。
- **退行リスク**: line 単位の start/end (snap 後) は変えず chunk 内配分のみ改善するため、影響は「分割された字幕」に限定。config フラグで即時 OFF 可能。

## 8. 参考資料

- `docs/plannings/2026-05-17_per-character-tts.md` — per-voice TTS / `tts_full.<base>.json`
- PR #351 / #352 — char_ts の感情タグズレと silence snap tolerance (前回の頭切れ修正)
- `CLAUDE.md`「字幕の手動チャンク制御」 — `subtitles[]` / `_resolve_subtitle_timings` のアンカー方式
