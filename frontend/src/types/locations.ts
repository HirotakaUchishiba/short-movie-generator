// types.ts から抽出 (= §3.1.3 type 分離)。
//
// グローバル素材カタログ (= locations/<id>.json / characters/<id>.json) の型。
// CameraDistance は Identity でも参照されるため、ここを single source of truth
// にして abstract-screenplay も import する。

export type CameraDistance = "close-up" | "medium-close" | "medium" | "wide";

// グローバルなロケ集 (locations/<id>.json)。
export interface Location {
  id: string;
  decor: string;
  lighting: string;
  color_palette: string;
  props: string;
  camera_distance: CameraDistance;
}

// グローバルなキャラ voice メタ (characters/<id>.json)。<id> は衣装込みの
// 焼き込みキャラ ID。
export interface CharacterMeta {
  id: string;
  voice_overrides?: Record<string, unknown>;
}
