import { describe, expect, it } from "vitest";
import { HelloWorldProps } from "../compositions/HelloWorld";
import { RenderPlan } from "../schemas/renderPlan";

describe("HelloWorldProps schema", () => {
  it("accepts minimal props", () => {
    const parsed = HelloWorldProps.parse({ videoSrc: "scene.mp4" });
    expect(parsed.videoSrc).toBe("scene.mp4");
    expect(parsed.subtitleText).toBe("Hello, Remotion!");
    expect(parsed.subtitleStart).toBe(0.5);
    expect(parsed.subtitleEnd).toBe(2.5);
  });

  it("accepts custom subtitle range", () => {
    const parsed = HelloWorldProps.parse({
      videoSrc: "x.mp4",
      subtitleText: "テスト",
      subtitleStart: 1.0,
      subtitleEnd: 3.0,
    });
    expect(parsed.subtitleStart).toBe(1.0);
    expect(parsed.subtitleEnd).toBe(3.0);
  });

  it("rejects missing videoSrc", () => {
    expect(() => HelloWorldProps.parse({})).toThrow();
  });
});

describe("RenderPlan schema", () => {
  it("validates a minimal plan", () => {
    const plan = RenderPlan.parse({
      video: { width: 1080, height: 1920, fps: 60, duration_frames: 480 },
      scenes: [
        {
          index: 0,
          scene_video_path: "/abs/path/scene_000.mp4",
          offset_sec: 0,
          duration_sec: 7.5,
          subtitle_lines: [
            {
              line_idx: 0,
              chunks: [
                {
                  text: "やばい",
                  start_abs_sec: 0.5,
                  end_abs_sec: 1.0,
                },
              ],
            },
          ],
          parts: {
            subtitle_style: { id: "minimal" },
          },
        },
      ],
    });

    expect(plan.template).toBe("base");
    expect(plan.scenes[0].subtitle_lines[0].chunks[0].anchor_kind).toBe("auto");
    expect(plan.scenes[0].parts.subtitle_style.params).toEqual({});
  });

  it("rejects invalid template", () => {
    expect(() =>
      RenderPlan.parse({
        video: { width: 1080, height: 1920, fps: 60, duration_frames: 480 },
        scenes: [],
        global_parts: {},
        template: "nonexistent",
      }),
    ).toThrow();
  });

  it("preserves manual anchor_kind", () => {
    const plan = RenderPlan.parse({
      video: { width: 1080, height: 1920, fps: 60, duration_frames: 480 },
      scenes: [
        {
          index: 0,
          scene_video_path: "/x.mp4",
          offset_sec: 0,
          duration_sec: 5,
          subtitle_lines: [
            {
              line_idx: 0,
              chunks: [
                {
                  text: "a",
                  start_abs_sec: 0,
                  end_abs_sec: 1,
                  anchor_kind: "manual",
                },
              ],
            },
          ],
          parts: { subtitle_style: { id: "minimal" } },
        },
      ],
    });
    expect(plan.scenes[0].subtitle_lines[0].chunks[0].anchor_kind).toBe(
      "manual",
    );
  });
});
