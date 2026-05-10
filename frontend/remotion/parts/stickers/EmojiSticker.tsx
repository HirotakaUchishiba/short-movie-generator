import React from "react";
import {
  AbsoluteFill,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

// すべての sticker は本コンポーネントの薄いラッパとして表現できる
// (= 内容は emoji 文字列、見た目の差は color filter / size / 位置で決める)。
//
// 出現時は spring で scale 0 → 1 にポップ。
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §4.3

export type EmojiStickerProps = {
  // 内容 (例: "❗", "✨", "❓")。emoji 1 文字想定
  emoji: string;
  // 表示位置: AbsoluteFill 上の {top, left, right, bottom} を 0-1 比率で指定。
  // どれか必須。1 軸ずつ指定すれば反対側は自動 (= flexbox で center)。
  top?: number;
  left?: number;
  right?: number;
  bottom?: number;
  // emoji フォントサイズ (px)。1080×1920 想定で 200px が画面 1/5 くらい
  size?: number;
  // pop-in animation の長さ (frame)。0 で無効
  popInFrames?: number;
  // 出現 frame 以降に rotation で揺らす振幅 (deg)。0 で静止
  wobbleDeg?: number;
};

export const EmojiSticker: React.FC<EmojiStickerProps> = ({
  emoji,
  top,
  left,
  right,
  bottom,
  size = 220,
  popInFrames = 12,
  wobbleDeg = 0,
}) => {
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();
  const scale =
    popInFrames > 0
      ? spring({
          frame,
          fps,
          from: 0,
          to: 1,
          durationInFrames: popInFrames,
          config: { damping: 9, mass: 0.5 },
        })
      : 1;
  const rot =
    wobbleDeg > 0 ? Math.sin((frame / fps) * Math.PI * 2 * 1.2) * wobbleDeg : 0;

  const positionStyle: React.CSSProperties = {
    position: "absolute",
    ...(top !== undefined ? { top: `${top * 100}%` } : {}),
    ...(left !== undefined ? { left: `${left * 100}%` } : {}),
    ...(right !== undefined ? { right: `${right * 100}%` } : {}),
    ...(bottom !== undefined ? { bottom: `${bottom * 100}%` } : {}),
  };

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          ...positionStyle,
          transform: `translate(-50%, -50%) scale(${scale}) rotate(${rot}deg)`,
          fontSize: size,
          lineHeight: 1,
          // emoji がデフォルトの絵文字 font に解決されるよう、フォント指定は外す
          filter:
            "drop-shadow(0 4px 8px rgba(0,0,0,0.35)) drop-shadow(0 0 2px rgba(0,0,0,0.5))",
        }}
      >
        {emoji}
      </div>
    </AbsoluteFill>
  );
};

// ───────────── プリセット sticker (= yaml の id とマップする薄い wrapper) ─────────────

export const ExclaimRed: React.FC<Omit<EmojiStickerProps, "emoji">> = (
  props,
) => <EmojiSticker emoji="❗" wobbleDeg={3} {...props} />;

export const QuestionMark: React.FC<Omit<EmojiStickerProps, "emoji">> = (
  props,
) => <EmojiSticker emoji="❓" wobbleDeg={2} {...props} />;

export const Sparkle: React.FC<Omit<EmojiStickerProps, "emoji">> = (props) => (
  <EmojiSticker emoji="✨" wobbleDeg={1} {...props} />
);

export const ThumbsUp: React.FC<Omit<EmojiStickerProps, "emoji">> = (props) => (
  <EmojiSticker emoji="👍" wobbleDeg={2} {...props} />
);

export const Fire: React.FC<Omit<EmojiStickerProps, "emoji">> = (props) => (
  <EmojiSticker emoji="🔥" wobbleDeg={2} {...props} />
);
