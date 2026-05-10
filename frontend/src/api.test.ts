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

  it("project() レスポンスの screenplay に _uid を注入する", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(
        JSON.stringify({
          timestamp: "1",
          screenplay_name: "x",
          screenplay: {
            scenes: [
              {
                duration: 1,
                lines: [
                  {
                    text: "x",
                    start: 0,
                    subtitles: [{ text: "x" }],
                  },
                ],
              },
            ],
          },
          progress: { stages: {} },
          current_stage: null,
          analyze_job_id: null,
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
    const { api } = await import("./api");
    const r = await api.project("1");
    expect(r.screenplay!.scenes[0]._uid).toBeTruthy();
    expect(r.screenplay!.scenes[0].lines![0]._uid).toBeTruthy();
    expect(r.screenplay!.scenes[0].lines![0].subtitles![0]._uid).toBeTruthy();
  });

  it("saveScreenplay() は _uid を strip して送信する", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { api } = await import("./api");
    await api.saveScreenplay("1", {
      scenes: [
        {
          duration: 1,
          _uid: "should-strip",
          lines: [{ text: "x", start: 0, _uid: "should-strip-2" }],
        },
      ],
    });
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const init = call[1] as RequestInit;
    const sent = JSON.parse(init.body as string);
    expect(sent.screenplay.scenes[0]._uid).toBeUndefined();
    expect(sent.screenplay.scenes[0].lines[0]._uid).toBeUndefined();
  });

  it("getProjectAbstract() レスポンスの abstract に _uid を注入する", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(
        JSON.stringify({
          screenplay_path: "p",
          abstract: {
            caption: "c",
            scenes: [{ lines: [{ text: "a", start: 0 }] }],
          },
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
    const { api } = await import("./api");
    const r = await api.getProjectAbstract("1");
    expect(r.abstract.scenes[0]._uid).toBeTruthy();
    expect(r.abstract.scenes[0].lines[0]._uid).toBeTruthy();
  });

  it("putProjectAbstract() は _uid を strip して送信する", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ screenplay_path: "p", scenes: 1 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { api } = await import("./api");
    await api.putProjectAbstract("1", {
      caption: "c",
      _uid: "x" as unknown as undefined,
      scenes: [
        {
          _uid: "drop-scene",
          lines: [{ text: "a", start: 0, _uid: "drop-line" }],
        },
      ],
    });
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const init = call[1] as RequestInit;
    const sent = JSON.parse(init.body as string);
    expect(sent.abstract._uid).toBeUndefined();
    expect(sent.abstract.scenes[0]._uid).toBeUndefined();
    expect(sent.abstract.scenes[0].lines[0]._uid).toBeUndefined();
  });

  it("retryAnalyzeForProject() は POST /api/projects/<ts>/retry-analyze を呼ぶ", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(
        JSON.stringify({ ok: true, new_analyze_job_id: "analyze_xyz" }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
    const { api } = await import("./api");
    const r = await api.retryAnalyzeForProject("20260510_120000");
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toMatch(/\/api\/projects\/20260510_120000\/retry-analyze$/);
    expect((call[1] as RequestInit).method).toBe("POST");
    expect(r.ok).toBe(true);
    expect(r.new_analyze_job_id).toBe("analyze_xyz");
  });

  it("deleteProject() は DELETE /api/projects/<ts> を呼ぶ", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ ts: "20260510_120000", deleted: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const { api } = await import("./api");
    const r = await api.deleteProject("20260510_120000");
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toMatch(/\/api\/projects\/20260510_120000$/);
    expect((call[1] as RequestInit).method).toBe("DELETE");
    expect(r.deleted).toBe(true);
  });
});
