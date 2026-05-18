// ScriptEditPanel.tsx から抽出 (= §3.1.3-c sub-component 分離)。
//
// compose の不整合をユーザに見せる警告バナー。すべての項目がクリーンなら緑、
// 1 つでも問題があれば琥珀色で警告表示。frontend が abstract / characterRefs から
// live 計算した diagnostics を受け取って、未マッピング speaker / 人物 0 人 /
// 未定義キャラ ref を一覧化する。

import type { AbstractDiagnostics } from "../../types";

export function CompletenessBanner({
  diag,
  captionEmpty,
  featuredEmpty,
}: {
  diag: AbstractDiagnostics;
  captionEmpty: boolean;
  featuredEmpty: boolean;
}) {
  const issues: string[] = [];
  if (captionEmpty) issues.push("caption が空");
  if (featuredEmpty) issues.push("動画全体の登場人物が未指定");
  if (diag.unmapped_speakers.length > 0) {
    issues.push(`未マッピング話者: ${diag.unmapped_speakers.join(", ")}`);
  }
  if (diag.scenes_without_characters.length > 0) {
    const ids = diag.scenes_without_characters
      .map((i) => `#${i + 1}`)
      .join(", ");
    issues.push(
      `人物 0 人 ${diag.scenes_without_characters.length} シーン (${ids})`,
    );
  }
  if (diag.scenes_without_location.length > 0) {
    const ids = diag.scenes_without_location.map((i) => `#${i + 1}`).join(", ");
    issues.push(
      `背景未設定 ${diag.scenes_without_location.length} シーン (${ids})`,
    );
  }
  if (diag.invalid_camera_distance.length > 0) {
    const t = diag.invalid_camera_distance
      .map((x) => `#${x.scene_idx + 1}='${x.value}'`)
      .join(", ");
    issues.push(`不正なカメラ距離: ${t}`);
  }
  const u = diag.unknown_character_refs;
  if (u) {
    if (u.featured.length > 0) {
      issues.push(`未定義キャラ (登場人物): ${u.featured.join(", ")}`);
    }
    if (u.character_selection.length > 0) {
      const t = u.character_selection
        .map((x) => `#${x.scene_idx + 1}=${x.ref}`)
        .join(", ");
      issues.push(`未定義キャラ (シーン登場人物): ${t}`);
    }
    if (u.speaker.length > 0) {
      const t = u.speaker
        .map((x) => `#${x.scene_idx + 1}/L${x.line_idx + 1}=${x.ref}`)
        .join(", ");
      issues.push(`未定義キャラ (line.speaker): ${t}`);
    }
  }
  if (issues.length === 0) {
    return (
      <div className="rounded p-2 text-xs bg-emerald-900/30 text-emerald-200 border border-emerald-500/40">
        ✅ 抽象台本に未解決の不整合はありません (compose 入力 OK)
      </div>
    );
  }
  return (
    <div className="rounded p-2 text-xs bg-amber-900/30 text-amber-100 border border-amber-500/40">
      <div className="font-semibold mb-1">
        ⚠️ {issues.length} 件の未解決項目があります (このまま compose すると
        意図と違う結果になる可能性):
      </div>
      <ul className="list-disc list-inside space-y-0.5">
        {issues.map((m) => (
          <li key={m}>{m}</li>
        ))}
      </ul>
    </div>
  );
}
