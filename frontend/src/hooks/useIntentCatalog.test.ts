import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

import {
  resetIntentCatalogCache,
  useIntentCatalog,
  type IntentCatalogResponse,
} from "./useIntentCatalog";

const sampleResponse: IntentCatalogResponse = {
  category: "visual_intents",
  status: "ok",
  found: true,
  entries: [
    {
      id: "talking_head_calm",
      description: "落ち着いた喋り",
      params_schema: {},
      valid_contexts: ["scene"],
      deprecated: false,
      valid_start_emotions: ["中立", "喜び"],
      duration_buckets: [5, 10],
      compatible_with: [],
      motion_intensity_bucket: "low",
    },
    {
      id: "talking_head_excited",
      description: "deprecated",
      params_schema: {},
      valid_contexts: ["scene"],
      deprecated: true,
      valid_start_emotions: ["驚き"],
      duration_buckets: [5],
      compatible_with: [],
      motion_intensity_bucket: "medium",
    },
  ],
};

beforeEach(() => {
  resetIntentCatalogCache();
  vi.restoreAllMocks();
});

afterEach(() => {
  resetIntentCatalogCache();
});

describe("useIntentCatalog", () => {
  it("loading → ready で fetch 結果を返す", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => sampleResponse,
    } as unknown as Response);

    const { result } = renderHook(() => useIntentCatalog());
    expect(result.current.kind).toBe("loading");
    await waitFor(() => expect(result.current.kind).toBe("ready"));
    if (result.current.kind !== "ready") throw new Error("not ready");
    expect(result.current.data.category).toBe("visual_intents");
    expect(result.current.data.entries).toHaveLength(2);
  });

  it("fetch エラーで kind=error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => "boom",
    } as unknown as Response);

    const { result } = renderHook(() => useIntentCatalog());
    await waitFor(() => expect(result.current.kind).toBe("error"));
    if (result.current.kind !== "error") throw new Error("not error");
    expect(result.current.message).toContain("500");
  });
});
