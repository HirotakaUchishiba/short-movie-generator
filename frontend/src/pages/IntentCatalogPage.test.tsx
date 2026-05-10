import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  render,
  screen,
  waitFor,
  act,
  fireEvent,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import IntentCatalogPage from "./IntentCatalogPage";

// 設計 doc: docs/plannings/2026-05-10_intent-suggestion-flow.md §4

type FetchSpec = {
  ok: boolean;
  status?: number;
  json?: unknown;
  text?: string;
};

function buildFetchMock(
  spec: Record<string, FetchSpec | (() => FetchSpec)>,
): typeof fetch {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    // pathname + query を 1 key にまとめて lookup
    const key = Object.keys(spec).find((k) => url.startsWith(k));
    if (!key) {
      throw new Error(`unexpected fetch: ${url}`);
    }
    const raw = spec[key];
    const s = typeof raw === "function" ? raw() : raw;
    return {
      ok: s.ok,
      status: s.status ?? (s.ok ? 200 : 500),
      json: async () => s.json ?? {},
      text: async () => s.text ?? "",
    } as Response;
  }) as typeof fetch;
}

const baseSuggestion = {
  id: "abc1234567890abc",
  proposed_id: "frantic_typing",
  description: "subject types furiously",
  rationale: "no good match",
  scene_indices: [3, 7],
  source_screenplay: "screenplays/auto_x.json",
  source_analyze_job_id: "job-x",
  status: "new" as const,
  dismissed_reason: null,
  occurrences: 1,
  created_at: "2026-05-10T00:00:00Z",
  updated_at: "2026-05-10T00:00:00Z",
};

const emptyClipsResponse = { enabled: true, entries: [] };
const emptyPartCatalogResponse = { categories: {} };

describe("IntentCatalogPage > IntentSuggestionsSection", () => {
  beforeEach(() => {
    // navigator.clipboard を stub (= happy-dom 既定では未提供 / read-only getter
    // のため defineProperty で上書き)
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: vi.fn(async () => {}),
      },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("空 inbox なら 'entry なし' プレースホルダを表示", async () => {
    global.fetch = buildFetchMock({
      "/api/intent-suggestions": {
        ok: true,
        json: { entries: [], counts: {} },
      },
      "/api/clips": { ok: true, json: emptyClipsResponse },
      "/api/parts/catalog": { ok: true, json: emptyPartCatalogResponse },
    });
    render(
      <MemoryRouter>
        <IntentCatalogPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      const section = screen.getByTestId("intent-suggestions-section");
      expect(section.textContent).toMatch(/該当 entry なし/);
      expect(section.textContent).toMatch(/analyze 実行で/);
    });
  });

  it("entries が乗っていればカードを表示する", async () => {
    global.fetch = buildFetchMock({
      "/api/intent-suggestions": {
        ok: true,
        json: {
          entries: [baseSuggestion],
          counts: {
            new: 1,
            reviewing: 0,
            accepted: 0,
            dismissed: 0,
            merged: 0,
          },
        },
      },
      "/api/clips": { ok: true, json: emptyClipsResponse },
      "/api/parts/catalog": { ok: true, json: emptyPartCatalogResponse },
    });
    render(
      <MemoryRouter>
        <IntentCatalogPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getAllByTestId("suggestion-card").length).toBe(1);
    });
    expect(screen.getByText("frantic_typing")).toBeInTheDocument();
    expect(screen.getByText(/subject types furiously/)).toBeInTheDocument();
  });

  it("yaml snippet 取得ボタンで accept API が呼ばれ clipboard にコピーされる", async () => {
    const yamlSnippet =
      "- id: frantic_typing\n  description: |\n    typing\n  pool_target_size: 8\n";
    let acceptCallCount = 0;
    global.fetch = buildFetchMock({
      "/api/intent-suggestions/abc1234567890abc/accept": {
        ok: true,
        json: {
          ok: true,
          record: { ...baseSuggestion, status: "accepted" },
          yaml_snippet: yamlSnippet,
        },
      },
      "/api/intent-suggestions": () => {
        acceptCallCount += 1;
        // 1 回目 = ボタン表示用、2 回目以降 = accept 後の reload
        if (acceptCallCount === 1) {
          return {
            ok: true,
            json: {
              entries: [baseSuggestion],
              counts: {
                new: 1,
                reviewing: 0,
                accepted: 0,
                dismissed: 0,
                merged: 0,
              },
            },
          };
        }
        return {
          ok: true,
          json: {
            entries: [{ ...baseSuggestion, status: "accepted" }],
            counts: {
              new: 0,
              reviewing: 0,
              accepted: 1,
              dismissed: 0,
              merged: 0,
            },
          },
        };
      },
      "/api/clips": { ok: true, json: emptyClipsResponse },
      "/api/parts/catalog": { ok: true, json: emptyPartCatalogResponse },
    });

    render(
      <MemoryRouter>
        <IntentCatalogPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText("📋 yaml snippet 取得")).toBeInTheDocument();
    });
    await act(async () => {
      fireEvent.click(screen.getByText("📋 yaml snippet 取得"));
    });
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(yamlSnippet);
    });
    // toast 通知が出る
    await waitFor(() => {
      expect(screen.getByText(/snippet をコピーしました/)).toBeInTheDocument();
    });
  });

  it("却下ボタンは reason prompt が空なら API を呼ばない", async () => {
    const dismissFetch = vi.fn(
      async () =>
        ({
          ok: true,
          status: 200,
          json: async () => ({}),
          text: async () => "",
        }) as Response,
    );
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/dismiss")) {
        return dismissFetch();
      }
      if (url.startsWith("/api/intent-suggestions")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            entries: [baseSuggestion],
            counts: {
              new: 1,
              reviewing: 0,
              accepted: 0,
              dismissed: 0,
              merged: 0,
            },
          }),
          text: async () => "",
        } as Response;
      }
      if (url.startsWith("/api/clips")) {
        return {
          ok: true,
          status: 200,
          json: async () => emptyClipsResponse,
          text: async () => "",
        } as Response;
      }
      if (url.startsWith("/api/parts/catalog")) {
        return {
          ok: true,
          status: 200,
          json: async () => emptyPartCatalogResponse,
          text: async () => "",
        } as Response;
      }
      throw new Error(`unexpected: ${url}`);
    }) as typeof fetch;

    // window.prompt が空文字を返すと API 呼び出しが skip される
    vi.spyOn(window, "prompt").mockReturnValue("");

    render(
      <MemoryRouter>
        <IntentCatalogPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText("❌ 却下")).toBeInTheDocument();
    });
    await act(async () => {
      fireEvent.click(screen.getByText("❌ 却下"));
    });
    expect(dismissFetch).not.toHaveBeenCalled();
  });

  it("occurrences > 1 なら ×N バッジが出る", async () => {
    global.fetch = buildFetchMock({
      "/api/intent-suggestions": {
        ok: true,
        json: {
          entries: [{ ...baseSuggestion, occurrences: 3 }],
          counts: {
            new: 1,
            reviewing: 0,
            accepted: 0,
            dismissed: 0,
            merged: 0,
          },
        },
      },
      "/api/clips": { ok: true, json: emptyClipsResponse },
      "/api/parts/catalog": { ok: true, json: emptyPartCatalogResponse },
    });
    render(
      <MemoryRouter>
        <IntentCatalogPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText("×3")).toBeInTheDocument();
    });
  });
});
