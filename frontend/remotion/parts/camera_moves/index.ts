// camera_moves parts の id → component map。
// SSOT は config/part_registry/camera_moves.yaml の `component` フィールドと一致させる。

import {
  DollyPullBack,
  KenBurns,
  NoneCameraMove,
  SubtleZoomIn,
} from "./CameraMove";

export {
  DollyPullBack,
  KenBurns,
  NoneCameraMove,
  SubtleZoomIn,
} from "./CameraMove";
export type {
  CameraMoveBaseProps,
  DollyPullBackProps,
  KenBurnsProps,
  SubtleZoomInProps,
} from "./CameraMove";

export const CAMERA_MOVE_COMPONENTS = {
  none: NoneCameraMove,
  subtle_zoom_in: SubtleZoomIn,
  ken_burns: KenBurns,
  dolly_pull_back: DollyPullBack,
} as const;

export type CameraMoveId = keyof typeof CAMERA_MOVE_COMPONENTS;
