// AnalyzeJobView.tsx から抽出 (= §3.1.3 helper 分離)。
//
// analyze ジョブの phase / status の Japanese ラベル / 進捗順序 / 経過秒の
// 整形を提供する pure utility 群。React 非依存で test 容易。

import type { AnalyzePhase, AnalyzeStatus } from "../types";

export const PHASE_LABELS: Record<AnalyzePhase, string> = {
  frames: "フレーム抽出",
  audio: "音声抽出",
  whisper: "文字起こし (Whisper)",
  acoustic: "音響特徴 (librosa)",
  claude: "Claude 分析 (Vision)",
  save: "台本保存",
};

export const PHASE_HINTS: Record<AnalyzePhase, string> = {
  frames: "ffmpeg で動画から静止画を切り出し中",
  audio: "ffmpeg で 16kHz mono の音声トラックを抽出中",
  whisper:
    "Whisper で word 単位の文字起こしを生成中 (動画長依存、数秒〜数十秒)",
  acoustic: "librosa で各セグメントの pitch / RMS / wpm を抽出中",
  claude: "Claude Opus 4.7 にフレーム+音声情報を送って台本生成中",
  save: "screenplay JSON を screenplays/auto_*.json に書き出し中",
};

export const STATUS_LABELS: Record<AnalyzeStatus, string> = {
  pending: "待機中",
  dryrunning: "ドライラン中",
  awaiting_confirm: "コスト確認待ち",
  running: "実行中",
  completed: "完了",
  failed: "失敗",
  cancelled: "キャンセル済み",
};

export const TERMINAL: AnalyzeStatus[] = ["completed", "failed", "cancelled"];

export const PHASE_ORDER: AnalyzePhase[] = [
  "frames",
  "audio",
  "whisper",
  "acoustic",
  "claude",
  "save",
];

export function formatDuration(ms: number): string {
  if (ms < 0) ms = 0;
  const totalSec = ms / 1000;
  if (totalSec < 60) return `${totalSec.toFixed(1)}s`;
  const m = Math.floor(totalSec / 60);
  const s = Math.floor(totalSec % 60);
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}
