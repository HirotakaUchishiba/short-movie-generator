import { describe, expect, it } from "vitest";
import { ScreenplayBaseProps } from "../compositions/ScreenplayBase";

describe("ScreenplayBaseProps schema", () => {
  it("accepts a minimal RenderPlan with one scene", () => {
    const parsed = ScreenplayBaseProps.parse({
      plan: {
        video: { width: 1080, height: 1920, fps: 60, duration_frames: 156 },
        scenes: [
          {
            index: 0,
            scene_video_path: "_smoke/scene_000.mp4",
            offset_sec: 0,
            duration_sec: 2.6,
            subtitle_lines: [
              {
                line_idx: 0,
                emotion: "中立",
                chunks: [
                  {
                    text: "テスト",
                    start_abs_sec: 0.5,
                    end_abs_sec: 2.0,
                  },
                ],
              },
            ],
            parts: {
              subtitle_style: { id: "minimal" },
            },
          },
        ],
      },
    });
    expect(parsed.plan.template).toBe("base");
    expect(parsed.plan.scenes).toHaveLength(1);
    expect(parsed.plan.scenes[0].parts.subtitle_style.id).toBe("minimal");
    expect(parsed.plan.scenes[0].subtitle_lines[0].chunks[0].anchor_kind).toBe(
      "auto",
    );
  });

  it("accepts multi-scene plans", () => {
    const parsed = ScreenplayBaseProps.parse({
      plan: {
        video: { width: 1080, height: 1920, fps: 60, duration_frames: 600 },
        scenes: [
          {
            index: 0,
            scene_video_path: "a.mp4",
            offset_sec: 0,
            duration_sec: 5,
            subtitle_lines: [],
            parts: { subtitle_style: { id: "minimal" } },
          },
          {
            index: 1,
            scene_video_path: "b.mp4",
            offset_sec: 5,
            duration_sec: 5,
            subtitle_lines: [],
            parts: { subtitle_style: { id: "minimal" } },
          },
        ],
      },
    });
    expect(parsed.plan.scenes).toHaveLength(2);
    expect(parsed.plan.scenes[1].offset_sec).toBe(5);
  });

  it("rejects missing scene_video_path", () => {
    expect(() =>
      ScreenplayBaseProps.parse({
        plan: {
          video: { width: 1080, height: 1920, fps: 60, duration_frames: 60 },
          scenes: [
            {
              index: 0,
              // scene_video_path missing
              offset_sec: 0,
              duration_sec: 5,
              subtitle_lines: [],
              parts: { subtitle_style: { id: "minimal" } },
            },
          ],
        },
      }),
    ).toThrow();
  });

  it("rejects missing subtitle_style", () => {
    expect(() =>
      ScreenplayBaseProps.parse({
        plan: {
          video: { width: 1080, height: 1920, fps: 60, duration_frames: 60 },
          scenes: [
            {
              index: 0,
              scene_video_path: "x.mp4",
              offset_sec: 0,
              duration_sec: 5,
              subtitle_lines: [],
              parts: {},
            },
          ],
        },
      }),
    ).toThrow();
  });

  it("preserves manual anchor_kind through schema", () => {
    const parsed = ScreenplayBaseProps.parse({
      plan: {
        video: { width: 1080, height: 1920, fps: 60, duration_frames: 60 },
        scenes: [
          {
            index: 0,
            scene_video_path: "x.mp4",
            offset_sec: 0,
            duration_sec: 5,
            subtitle_lines: [
              {
                line_idx: 0,
                chunks: [
                  {
                    text: "manual",
                    start_abs_sec: 1,
                    end_abs_sec: 2,
                    anchor_kind: "manual",
                  },
                ],
              },
            ],
            parts: { subtitle_style: { id: "minimal" } },
          },
        ],
      },
    });
    expect(parsed.plan.scenes[0].subtitle_lines[0].chunks[0].anchor_kind).toBe(
      "manual",
    );
  });

  it("defaults global_parts to empty object", () => {
    const parsed = ScreenplayBaseProps.parse({
      plan: {
        video: { width: 1080, height: 1920, fps: 60, duration_frames: 60 },
        scenes: [],
      },
    });
    expect(parsed.plan.global_parts).toEqual({});
    expect(parsed.plan.template).toBe("base");
  });
});
