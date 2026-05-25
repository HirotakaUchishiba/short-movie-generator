// 背景 (= location_ref) を preview.png のサムネカードで選ぶピッカー。
//
// `<select>` ドロップダウンの代替 (= LocationPicker の中身)。登場人物カード
// (= BaseCharacterCard size="sm" / w-16 × aspect-[9/16]) と縦幅を揃えた横長
// カード (= 縦幅同じ・横幅 2 倍 = w-32 × aspect-[9/8] で高さ ≈ 114px) を横一列に
// 並べ、横スクロールで選ぶ (= グリッドのように縦へ嵩張らない)。preview 未生成
// (= <img onError>) は画像を隠し id ラベルだけのプレースホルダにする (= 生成
// ボタンは Phase 2)。
//
// 設計書: `docs/plannings/2026-05-25_cast-follow-and-location-preview.md` §3.2。

import { useState } from "react";

import { locationPreviewUrl } from "../../api";

// 登場人物カード (w-16) の縦幅に合わせ、横幅を 2 倍にした横長サムネ。
const CARD_CLS = "aspect-[9/8] w-32 shrink-0";

function LocationThumbCard({
  id,
  selected,
  onSelect,
}: {
  id: string;
  selected: boolean;
  onSelect: () => void;
}) {
  const [hasImage, setHasImage] = useState(true);
  return (
    <button
      type="button"
      onClick={onSelect}
      title={id}
      className={`relative flex flex-col overflow-hidden rounded border text-left transition ${CARD_CLS} ${
        selected
          ? "border-emerald-400 ring-2 ring-emerald-400"
          : "border-slate-700 hover:border-slate-500"
      }`}
    >
      {hasImage ? (
        <img
          src={locationPreviewUrl(id)}
          alt={id}
          loading="lazy"
          className="h-full w-full object-cover"
          onError={() => setHasImage(false)}
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center bg-slate-800 text-[10px] text-slate-500">
          (preview なし)
        </div>
      )}
      <span className="absolute inset-x-0 bottom-0 truncate bg-black/60 px-1 py-0.5 text-[10px] text-slate-200">
        {id}
      </span>
    </button>
  );
}

export function LocationThumbPicker({
  locationIds,
  value,
  onChange,
}: {
  locationIds: string[];
  value: string | undefined;
  onChange: (id: string | undefined) => void;
}) {
  return (
    <div className="flex flex-row gap-2 overflow-x-auto pb-1">
      <button
        type="button"
        onClick={() => onChange(undefined)}
        title="(未設定)"
        className={`flex items-center justify-center rounded border text-[10px] transition ${CARD_CLS} ${
          value === undefined || value === ""
            ? "border-emerald-400 text-emerald-300 ring-2 ring-emerald-400"
            : "border-slate-700 text-slate-500 hover:border-slate-500"
        }`}
      >
        (未設定)
      </button>
      {locationIds.map((id) => (
        <LocationThumbCard
          key={id}
          id={id}
          selected={value === id}
          onSelect={() => onChange(id)}
        />
      ))}
    </div>
  );
}
