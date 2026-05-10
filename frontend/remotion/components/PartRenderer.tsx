import React from "react";
import { PartCategory, resolvePartComponent } from "../PartRegistry";

// Layer 2 part の generic dispatcher.
// screenplay の scene_parts.subtitle_style.id 等を受け、対応する React component
// を resolve して params を spread する。
//
// 不変条件: PartRenderer はディスパッチ専用。タイミング解決 / DOM 配置は
// 親 Composition (= ScreenplayBase / SceneSequence) が <Sequence> や
// <AbsoluteFill> で行う。

export type PartRendererProps = {
  category: PartCategory;
  id: string;
  params?: Record<string, unknown>;
};

export const PartRenderer: React.FC<PartRendererProps> = ({
  category,
  id,
  params,
}) => {
  const Component = resolvePartComponent(category, id);
  return <Component {...(params ?? {})} />;
};
