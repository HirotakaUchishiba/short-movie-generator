import React from "react";
import { AbsoluteFill } from "remotion";

// "minimal" subtitle part.
// 既存 ffmpeg compositor (compositor.py) の drawtext と同等の見た目を Remotion で再現する。
// アニメーションなし、白文字 + 黒縁取り、画面下端から固定 Y 位置。
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §4.3

export type MinimalSubtitleProps = {
  text: string;
  fontSize?: number;
  fontColor?: string;
  borderColor?: string;
  borderWidth?: number;
  // 画面下端からの px 位置 (= ffmpeg drawtext y_from_bottom 慣例と一致)。
  // compositor_remotion.py は screenplay の subtitle_y_from_bottom 経由で上書きする。
  yFromBottom?: number;
  // emotion ラベル (= 将来 emotion 別カラー化する際の hook、minimal では無視)
  emotion?: string;
};

export const MinimalSubtitle: React.FC<MinimalSubtitleProps> = ({
  text,
  fontSize = 76,
  fontColor = "#FFFFFF",
  borderColor = "#000000",
  borderWidth = 6,
  yFromBottom = 950,
}) => {
  // ffmpeg drawtext の `y` パラメータは **テキスト box の TOP** の pixel 位置 (= 画面 top 起点)。
  // compositor.py では `sub_y = H - y_from_bottom`、つまり「画面下から y_from_bottom 上に
  // テキスト top が来る」運用。Remotion で同じ位置にするには paddingBottom を
  // (y_from_bottom - fontSize) にして、justifyContent: flex-end でテキスト bottom を
  // (画面下から y_from_bottom - fontSize) に置く = テキスト top が画面下から y_from_bottom
  // 上に揃う。
  const paddingBottom = Math.max(0, yFromBottom - fontSize);

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
        paddingBottom,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          fontFamily:
            "'ヒラギノ角ゴシック W7', 'Hiragino Sans', 'Yu Gothic', sans-serif",
          fontWeight: 700,
          fontSize,
          color: fontColor,
          // CSS text-stroke で縁取り。Chromium が描く順序を fill より stroke を
          // 先にすることで文字内側まで黒が侵食しない (= ffmpeg drawtext の
          // borderw と同等の見た目)。
          WebkitTextStroke: `${borderWidth}px ${borderColor}`,
          paintOrder: "stroke fill",
          textAlign: "center",
          lineHeight: 1.2,
          // ffmpeg drawtext は **自動折返ししない** (= text 内 \n のみ line break)。
          // Remotion 側も同じ挙動にするため `pre` を採用 (= \n は line break、
          // それ以外の自動 wrap なし)。chunk_enabled モードでは chunks に \n は含まれず、
          // chunk_disabled モードでは _wrap_subtitle_text が \n を入れて渡してくる。
          whiteSpace: "pre",
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};
