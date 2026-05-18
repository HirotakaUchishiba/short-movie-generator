// ScriptEditPanel.tsx から抽出 (= §3.1.3-c sub-component 分離)。
// 既存名 `Row` は generic すぎるため公開時に ScriptEditRow に rename。
// dt/dd の 2 列レイアウトでラベル + 値を 1 行表示する。

export function ScriptEditRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex gap-2">
      <dt className="text-slate-500 w-28 shrink-0">{label}</dt>
      <dd className={mono ? "font-mono text-slate-300" : "text-slate-300"}>
        {value}
      </dd>
    </div>
  );
}
