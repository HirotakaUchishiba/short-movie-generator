import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

import {
  resetPartCatalogCache,
  useCategoryEntries,
  useCategoryStatus,
  usePartCatalog,
  type PartCatalogResponse,
} from "./usePartCatalog";

const sampleResponse: PartCatalogResponse = {
  categories: {
    subtitle_styles: {
      category: "subtitle_styles",
      status: "ok",
      found: true,
      entries: [
        {
          id: "minimal",
          description: "シンプル",
          params_schema: {},
          valid_contexts: ["scene"],
          deprecated: false,
        },
        {
          id: "old",
          description: "deprecated",
          params_schema: {},
          valid_contexts: ["scene"],
          deprecated: true,
        },
      ],
    },
    visual_intents: {
      category: "visual_intents",
      status: "missing",
      found: false,
      entries: [],
    },
    stickers: {
      category: "stickers",
      status: "parse_error",
      found: false,
      entries: [],
    },
  },
};

const fetchMock = vi.fn();

beforeEach(() => {
  resetPartCatalogCache();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function mockOk(body: PartCatalogResponse) {
  fetchMock.mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  });
}

describe("usePartCatalog", () => {
  it("transitions loading → ready on successful fetch", async () => {
    mockOk(sampleResponse);
    const { result } = renderHook(() => usePartCatalog());
    expect(result.current.kind).toBe("loading");
    await waitFor(() => expect(result.current.kind).toBe("ready"));
  });

  it("returns error when fetch fails", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => "boom",
      json: async () => ({}),
    });
    const { result } = renderHook(() => usePartCatalog());
    await waitFor(() => expect(result.current.kind).toBe("error"));
    if (result.current.kind === "error") {
      expect(result.current.message).toMatch(/500/);
    }
  });

  it("uses module-level cache for second consumer (= no re-fetch)", async () => {
    mockOk(sampleResponse);
    const first = renderHook(() => usePartCatalog());
    await waitFor(() => expect(first.result.current.kind).toBe("ready"));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // 2nd hook 起動時には cache が hit して fetch されない
    const second = renderHook(() => usePartCatalog());
    await waitFor(() => expect(second.result.current.kind).toBe("ready"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("dedupes in-flight requests for concurrent consumers", async () => {
    let resolve: (v: unknown) => void = () => {};
    fetchMock.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    renderHook(() => usePartCatalog());
    renderHook(() => usePartCatalog());
    // まだ 1 回しか fetch されていない (= in-flight cache が deduplicate)
    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolve({
      ok: true,
      status: 200,
      json: async () => sampleResponse,
      text: async () => "",
    });
  });
});

describe("useCategoryEntries", () => {
  it("returns non-deprecated entries when status=ok", async () => {
    mockOk(sampleResponse);
    const { result } = renderHook(() => useCategoryEntries("subtitle_styles"));
    await waitFor(() => expect(result.current.length).toBe(1));
    expect(result.current[0].id).toBe("minimal");
  });

  it("returns empty array for missing category (= status=missing)", async () => {
    mockOk(sampleResponse);
    const { result } = renderHook(() => useCategoryEntries("visual_intents"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(result.current).toEqual([]);
  });

  it("returns empty array for parse_error category", async () => {
    mockOk(sampleResponse);
    const { result } = renderHook(() => useCategoryEntries("stickers"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(result.current).toEqual([]);
  });
});

describe("useCategoryStatus", () => {
  it("returns the backend status string", async () => {
    mockOk(sampleResponse);
    const { result } = renderHook(() => useCategoryStatus("subtitle_styles"));
    await waitFor(() => expect(result.current).toBe("ok"));
  });

  it("distinguishes missing from parse_error (= deploy 事故 vs ファイル破損)", async () => {
    mockOk(sampleResponse);
    const missing = renderHook(() => useCategoryStatus("visual_intents"));
    const parseErr = renderHook(() => useCategoryStatus("stickers"));
    await waitFor(() => expect(missing.result.current).toBe("missing"));
    expect(parseErr.result.current).toBe("parse_error");
  });

  it("returns 'missing' for unknown category", async () => {
    mockOk(sampleResponse);
    const { result } = renderHook(() => useCategoryStatus("nonexistent"));
    await waitFor(() => expect(result.current).toBe("missing"));
  });
});
