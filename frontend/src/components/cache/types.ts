// Stage 共通の cache decision UI で使う型定義 (= 単一責務: 型のみ)。
// stage 別差分は generic TMeta で吸収する。
import type { ReactNode } from "react";
import type { CacheCandidate, SceneDecision } from "../../types";

/** 1 scene の追加コンテキスト (= candidate との比較に使う、stage 共通の数値情報)。 */
export interface SceneContext {
  /** Stage 4: TTS 確定後の audio 長 (秒)。Stage 3: 不要 (= undefined)。 */
  newAudioDuration?: number;
}

/** stage 別の preview / metadata 描画ロジックを差し込むための contract。 */
export interface CachePresenter<TMeta> {
  /** preview 本体の描画 (img / video など、stage 別に切替可能)。 */
  renderPreview: (key: string) => ReactNode;
  /** candidate の metadata 行を描画 (元 audio / location / camera など stage 別)。 */
  renderCandidateMeta: (meta: TMeta, ctx: SceneContext) => ReactNode;
  /** 1 scene の judge UI 上に追加で表示する scene 別 extras (例: prompt preview)。 */
  renderSceneExtras?: (sceneIdx: number) => ReactNode;
  /** 1 scene 分の新規生成コスト (USD)。 */
  costForScene: (sceneIdx: number) => number;
  /** scene のコンテキスト (= duration 等を candidate と比較するため)。 */
  contextForScene: (sceneIdx: number) => SceneContext;
}

/** 上位コンポーネント間で共有する判断状態の薄い形 (= ロジック非依存)。 */
export interface DecisionsByIdx<TMeta> {
  cacheScannedAt: string | null;
  byIdx: Record<string, SceneDecision<TMeta>>;
}

export type { CacheCandidate, SceneDecision };
