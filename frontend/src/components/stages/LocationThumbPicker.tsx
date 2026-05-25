// 背景 (= location_ref) を preview.png のサムネカードグリッドで選ぶピッカー。
//
// `<select>` ドロップダウンの代替 (= LocationPicker の中身)。9:16 縦長サムネを
// grid で並べ、クリックで onChange。preview 未生成 (= <img onError>) は画像を
// 隠し id ラベルだけのプレースホルダにする (= 生成ボタンは Phase 2)。
//
// 設計書: `docs/plannings/2026-05-25_cast-follow-and-location-preview.md` §3.2。

import { useState } from "react";

import { locationPreviewUrl } from "../../api";

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
      className={`relative flex aspect-[9/16] flex-col overflow-hidden rounded border text-left transition ${
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
    <div className="grid grid-cols-3 gap-2">
      <button
        type="button"
        onClick={() => onChange(undefined)}
        title="(未設定)"
        className={`flex aspect-[9/16] items-center justify-center rounded border text-[10px] transition ${
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
