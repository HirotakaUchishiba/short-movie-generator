import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { PART_REGISTRY, type PartCategory } from "../PartRegistry";

// 全 part_registry/*.yaml と PART_REGISTRY の各 category の id 集合が
// 一致することを保証する drift test。Phase 4-A の subtitle 専用 drift test を
// generalize した形で、Phase 4-B 以降に追加されたカテゴリも自動的にカバーする。
//
// 詳細: docs/plannings/2026-05-10_compositional-architecture.md §4

function loadYamlIds(category: PartCategory): string[] {
  const __dirname = dirname(fileURLToPath(import.meta.url));
  const yamlPath = resolve(
    __dirname,
    "..",
    "..",
    "..",
    "config",
    "part_registry",
    `${category}.yaml`,
  );
  const text = readFileSync(yamlPath, "utf-8");
  // ナイーブパーサ: `  - id: <name>` 行だけ拾う。
  const ids: string[] = [];
  for (const line of text.split("\n")) {
    const m = /^\s*-\s+id:\s*([\w_]+)\s*$/.exec(line);
    if (m) ids.push(m[1]);
  }
  return ids;
}

const CATEGORIES = Object.keys(PART_REGISTRY) as PartCategory[];

describe("part_registry/*.yaml ↔ PART_REGISTRY drift", () => {
  for (const category of CATEGORIES) {
    it(`${category}: yaml id set equals component keys`, () => {
      const yamlIds = new Set(loadYamlIds(category));
      const codeIds = new Set(
        Object.keys(PART_REGISTRY[category] as Record<string, unknown>),
      );

      const missingInCode = [...yamlIds].filter((id) => !codeIds.has(id));
      const missingInYaml = [...codeIds].filter((id) => !yamlIds.has(id));

      expect(
        missingInCode,
        `${category}: yaml にあるが component に未実装`,
      ).toEqual([]);
      expect(missingInYaml, `${category}: 実装はあるが yaml に未登録`).toEqual(
        [],
      );
    });
  }
});
