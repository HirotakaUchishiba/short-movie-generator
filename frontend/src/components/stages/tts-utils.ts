// StageTTS.tsx から抽出 (= §3.1.3 helper 分離)。
//
// ElevenLabs モデル ID → UI 表示メタ (色 / 文脈サポート / 品質ラベル) の
// 単純な lookup table。新規モデル追加時はここに 1 ケース追加するだけ。

export function modelMeta(model: string): {
  color: string;
  contextLabel: string;
  qualityLabel: string;
} {
  switch (model) {
    case "eleven_v3":
      return {
        color: "border-amber-500 bg-amber-500/15 text-amber-100",
        contextLabel: "文脈✗",
        qualityLabel: "alpha",
      };
    case "eleven_multilingual_v2":
      return {
        color: "border-emerald-500 bg-emerald-500/15 text-emerald-100",
        contextLabel: "文脈✓",
        qualityLabel: "日本語◎",
      };
    case "eleven_turbo_v2_5":
    case "eleven_turbo_v2":
      return {
        color: "border-sky-500 bg-sky-500/15 text-sky-100",
        contextLabel: "文脈✓",
        qualityLabel: "高速・低品質",
      };
    case "eleven_flash_v2_5":
    case "eleven_flash_v2":
      return {
        color: "border-violet-500 bg-violet-500/15 text-violet-100",
        contextLabel: "文脈✓",
        qualityLabel: "爆速・低品質",
      };
    default:
      return {
        color: "border-slate-500 bg-slate-500/15 text-slate-100",
        contextLabel: "文脈?",
        qualityLabel: "?",
      };
  }
}
