// StageBG.tsx から抽出 (= §3.1.3 helper 分離)。
//
// 背景画像 (Imagen) のコスト表示用フォーマッタ。tts-cost / kling-utils
// と同じ "$N.NN or 履歴不足" semantics。

export function formatBgCost(usd: number | null): string {
  return usd == null ? "履歴不足" : `$${usd.toFixed(2)}`;
}
