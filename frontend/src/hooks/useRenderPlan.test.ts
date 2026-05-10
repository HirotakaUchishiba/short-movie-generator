import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

// api をモジュールレベルで mock。ApiError class は実装をそのまま使う。
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    api: {
      renderPlan: vi.fn(),
    },
  };
});

import { api, ApiError } from "../api";
import { useRenderPlan } from "./useRenderPlan";

const mockedRenderPlan = api.renderPlan as unknown as ReturnType<typeof vi.fn>;

const samplePlan = {
  video: { width: 1080, height: 1920, fps: 60, duration_frames: 156 },
  scenes: [
    {
      index: 0,
      scene_video_path: "http://localhost:5555/asset/x/scene_000.mp4",
      offset_sec: 0,
      duration_sec: 2.6,
      subtitle_lines: [],
      parts: { subtitle_style: { id: "minimal", params: {} } },
    },
  ],
  global_parts: {},
  template: "base" as const,
};

beforeEach(() => {
  mockedRenderPlan.mockReset();
});

describe("useRenderPlan", () => {
  it("starts in loading state", async () => {
    mockedRenderPlan.mockResolvedValue({ plan: samplePlan });
    const { result } = renderHook(() => useRenderPlan("ts1"));
    expect(result.current.kind).toBe("loading");
    await waitFor(() => expect(result.current.kind).toBe("ready"));
  });

  it("returns ready with plan on success", async () => {
    mockedRenderPlan.mockResolvedValue({ plan: samplePlan });
    const { result } = renderHook(() => useRenderPlan("ts1"));
    await waitFor(() => expect(result.current.kind).toBe("ready"));
    if (result.current.kind === "ready") {
      expect(result.current.plan.video.duration_frames).toBe(156);
      expect(result.current.plan.scenes).toHaveLength(1);
    }
  });

  it("returns not_ready on 409 with backend message", async () => {
    mockedRenderPlan.mockRejectedValue(
      new ApiError(409, "x", {
        error_code: "scene_videos_not_ready",
        message: "Stage 5 (scene 合成) 完了後にプレビュー可能です",
        missing_scene_indices: [0, 1],
      }),
    );
    const { result } = renderHook(() => useRenderPlan("ts2"));
    await waitFor(() => expect(result.current.kind).toBe("not_ready"));
    if (result.current.kind === "not_ready") {
      expect(result.current.message).toMatch(/Stage 5/);
    }
  });

  it("returns not_ready on 409 with default message when body absent", async () => {
    // backend が message を返さない (= legacy fallback) ケース
    mockedRenderPlan.mockRejectedValue(new ApiError(409, "", null));
    const { result } = renderHook(() => useRenderPlan("ts2b"));
    await waitFor(() => expect(result.current.kind).toBe("not_ready"));
    if (result.current.kind === "not_ready") {
      expect(result.current.message).toMatch(/Stage 5/);
    }
  });

  it("does NOT match 409 by string in message body (= no false positive)", async () => {
    // 500 の本文に偶然 "409" が出ても not_ready 扱いにならない
    mockedRenderPlan.mockRejectedValue(
      new ApiError(500, "found 409 records", null),
    );
    const { result } = renderHook(() => useRenderPlan("ts2c"));
    await waitFor(() => expect(result.current.kind).toBe("error"));
    if (result.current.kind === "error") {
      expect(result.current.message).toMatch(/500/);
    }
  });

  it("returns error on other failures", async () => {
    mockedRenderPlan.mockRejectedValue(new ApiError(500, "boom", null));
    const { result } = renderHook(() => useRenderPlan("ts3"));
    await waitFor(() => expect(result.current.kind).toBe("error"));
    if (result.current.kind === "error") {
      expect(result.current.message).toMatch(/500/);
    }
  });

  it("refetches when bumpKey changes", async () => {
    mockedRenderPlan.mockResolvedValue({ plan: samplePlan });
    const { rerender } = renderHook(({ ts, bump }) => useRenderPlan(ts, bump), {
      initialProps: { ts: "ts4", bump: 0 },
    });
    await waitFor(() => expect(mockedRenderPlan).toHaveBeenCalledTimes(1));
    rerender({ ts: "ts4", bump: 1 });
    await waitFor(() => expect(mockedRenderPlan).toHaveBeenCalledTimes(2));
  });

  it("ignores stale responses when ts changes", async () => {
    let resolveFirst: (v: unknown) => void = () => {};
    const firstPromise = new Promise((r) => {
      resolveFirst = r;
    });
    mockedRenderPlan.mockReturnValueOnce(firstPromise).mockResolvedValueOnce({
      plan: {
        ...samplePlan,
        video: { ...samplePlan.video, duration_frames: 999 },
      },
    });

    const { result, rerender } = renderHook(({ ts }) => useRenderPlan(ts, 0), {
      initialProps: { ts: "ts5" },
    });
    expect(result.current.kind).toBe("loading");

    rerender({ ts: "ts6" });
    // ts6 の fetch を resolve
    await waitFor(() => expect(mockedRenderPlan).toHaveBeenCalledTimes(2));
    // 後から ts5 の旧 promise を resolve しても ignore される
    resolveFirst({ plan: samplePlan });

    await waitFor(() => expect(result.current.kind).toBe("ready"));
    if (result.current.kind === "ready") {
      // ts6 の plan (= 999) を見ているはず、ts5 (= 156) は反映しない
      expect(result.current.plan.video.duration_frames).toBe(999);
    }
  });
});
