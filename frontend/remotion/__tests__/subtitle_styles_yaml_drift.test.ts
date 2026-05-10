import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { SUBTITLE_COMPONENTS } from "../parts/subtitles";

// Phase 4-A 以降、subtitle_styles.yaml と SUBTITLE_COMPONENTS の id 集合が
// 一致することを保証する drift test (= 片方だけ更新して片方が漏れるのを防ぐ)。
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §4

function loadYamlIds(): string[] {
  const __dirname = dirname(fileURLToPath(import.meta.url));
  // frontend/remotion/__tests__ → repo root → config/part_registry/subtitle_styles.yaml
  const yamlPath = resolve(
    __dirname,
    "..",
    "..",
    "..",
    "config",
    "part_registry",
    "subtitle_styles.yaml",
  );
  const text = readFileSync(yamlPath, "utf-8");
  // ナイーブパーサ: `  - id: <name>` 行だけ拾う (= yaml lib に依存しない)。
  // SSOT yaml はフラットな parts[] のみで入れ子の "id:" は出ない前提。
  const ids: string[] = [];
  for (const line of text.split("\n")) {
    const m = /^\s*-\s+id:\s*([\w_]+)\s*$/.exec(line);
    if (m) ids.push(m[1]);
  }
  return ids;
}

describe("subtitle_styles.yaml ↔ SUBTITLE_COMPONENTS drift", () => {
  it("yaml id set equals SUBTITLE_COMPONENTS keys", () => {
    const yamlIds = new Set(loadYamlIds());
    const codeIds = new Set(Object.keys(SUBTITLE_COMPONENTS));

    const missingInCode = [...yamlIds].filter((id) => !codeIds.has(id));
    const missingInYaml = [...codeIds].filter((id) => !yamlIds.has(id));

    expect(missingInCode, "yaml にあるが SUBTITLE_COMPONENTS に未実装").toEqual(
      [],
    );
    expect(missingInYaml, "実装はあるが yaml に未登録").toEqual([]);
  });
});
