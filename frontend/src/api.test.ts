import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("api fetch wrapper", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.resetModules();
    globalThis.fetch = vi.fn();
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("VITE_PREVIEW_TOKEN 未設定なら Authorization を付与しない", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ projects: [], screenplays: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { api } = await import("./api");
    await api.projects();
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const init = call[1] as RequestInit;
    expect(
      (init.headers as Record<string, string>).Authorization,
    ).toBeUndefined();
  });

  it("HTTP エラーは status と body を含む例外を投げる", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response("upstream broke", { status: 503 }),
    );
    const { api } = await import("./api");
    await expect(api.projects()).rejects.toThrow(/503/);
  });
});
