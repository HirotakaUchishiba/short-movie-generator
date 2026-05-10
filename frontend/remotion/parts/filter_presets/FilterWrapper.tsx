import React from "react";
import { AbsoluteFill } from "remotion";

// 全 filter_preset の共通 base。children に screenplay-wide で CSS filter を被せる。
// 本体は parts/filter_presets/index.ts の preset 群が薄い wrapper で渡してくる。
//
// ScreenplayBase 側は global_parts.filter_preset があれば PartRenderer 経由で
// 本コンポーネントを呼び、children に scene 群を渡す形になる (= ScreenplayBase 側
// で wrap 配置する)。
//
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §4.1, §5.1

export type FilterWrapperProps = {
  // CSS filter プロパティの値。例: "saturate(1.2) hue-rotate(-10deg)"
  cssFilter: string;
  children: React.ReactNode;
};

export const FilterWrapper: React.FC<FilterWrapperProps> = ({
  cssFilter,
  children,
}) => {
  return (
    <AbsoluteFill style={{ filter: cssFilter, pointerEvents: "none" }}>
      {children}
    </AbsoluteFill>
  );
};

// ───────────── プリセット ─────────────
// 各 preset は cssFilter 値だけが違う薄い wrapper。
// PART_REGISTRY 経由 dispatch のために named React component として export する。

const presetWith =
  (cssFilter: string): React.FC<{ children?: React.ReactNode }> =>
  ({ children }) => (
    <FilterWrapper cssFilter={cssFilter}>{children}</FilterWrapper>
  );

export const NoneFilter = presetWith("none");

// 暖色寄り (= シネマティック)
export const WarmCinematic = presetWith(
  "saturate(1.15) contrast(1.05) sepia(0.12) hue-rotate(-6deg)",
);

// 寒色寄り (= 朝 / 夜)
export const CoolBlue = presetWith(
  "saturate(0.9) contrast(1.05) hue-rotate(8deg) brightness(0.97)",
);

// モノクロ
export const Monochrome = presetWith("grayscale(1) contrast(1.08)");

// ヴィンテージ (= 退色 + 黄ばみ)
export const Vintage = presetWith(
  "sepia(0.4) saturate(0.85) contrast(0.95) brightness(1.02)",
);
