// types.ts から抽出 (= §3.1.3 type 分離)。
//
// 抽象台本 (Stage 1「素材」セクション編集用) 関連の型。完全 screenplay とは
// 別物。caption + scenes[].lines[] + シーンごとの設定。compose で完全
// screenplay に展開される。

import type { CameraDistance } from "../types";

export interface AbstractLine {
  text: string;
  start: number;
  end?: number;
  emotion?: string;
  delivery?: string;
  speaker?: string;
  rate?: string;
  pronunciation_hints?: Record<string, string>;
  // クライアント側で付与される React key 用 ID。API 送信時に strip される。
  _uid?: string;
}

// Layer 1 (clip library) hard match キー。4 フィールドすべて揃えば
// scene["identity"] として書き出され、cache lookup で hit すると AI 課金を回避。
// 1 つでも欠けると compose で identity が undefined になり cold path (AI 生成) が走る。
export interface Identity {
  character_refs: string[];
  location_ref: string;
  start_emotion: string;
  camera_distance: CameraDistance;
}

// Layer 1 soft rank に使う注釈。完全一致が無くても compatible_with 経由で fallback。
// 全 field optional (= 1 field でも書かれていれば送信)。
export interface Annotation {
  visual_intent_id?: string;
  duration_bucket?: 5 | 10;
  motion_intensity?: "low" | "medium" | "high";
  generation_seed?: number;
}

export interface AbstractScene {
  lines: AbstractLine[];
  duration?: number;
  // シーン別の人物指定 (= featured_characters の subset)
  //   未定義 = featured_characters 全員 (= 主に単一キャラ動画用のショートカット)
  //   []     = 0 人 (背景のみ)
  //   [...]  = 指定された ID のキャラだけ
  character_selection?: string[];
  camera_distance?: CameraDistance;
  location_ref?: string;
  animation_style?: "subtle" | "standard" | "expressive";
  // Layer 1 (clip library) identity + annotation
  identity?: Identity;
  annotation?: Annotation;
  // クライアント側で付与される React key 用 ID。API 送信時に strip される。
  _uid?: string;
}

export interface AbstractScreenplay {
  caption: string;
  scenes: AbstractScene[];
  // この動画に登場させる人物の characters/<id>.png キーのリスト。
  // シーンの登場人物・話者の候補として使われる。
  // 2026-05-17 schema 撤廃: speaker_to_ref / speaker_profiles は廃止。
  // analyze が line.speaker に resolved id を直書きするようになった。
  featured_characters?: string[];
  // future-proof で broadly に許容する。
  [k: string]: unknown;
}

export interface AbstractDiagnostics {
  // 2026-05-17 schema 撤廃: 旧 raw `speaker_N` 形式の残骸検出に使われる
  // (= migration 漏れの警告用)
  unmapped_speakers: string[];
  scenes_without_characters: number[];
  // location_ref が空のシーン idx (= analyze pre-fill 後、ユーザが意図的に
  // 空に戻したケースを CompletenessBanner で警告するため)
  scenes_without_location: number[];
  // camera_distance が enum 外のシーン (= 通常 analyze 経由では発生しないが
  // 旧データ / 手動編集の漏れを検知するため)
  invalid_camera_distance: { scene_idx: number; value: string }[];
  unknown_character_refs: {
    featured: string[];
    character_selection: { scene_idx: number; ref: string }[];
    speaker: { scene_idx: number; line_idx: number; ref: string }[];
  };
}

export interface AbstractScreenplayResponse {
  screenplay_path: string;
  abstract: AbstractScreenplay;
}
