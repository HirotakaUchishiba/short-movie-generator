import { describe, expect, it } from "vitest";
import {
  isKnownPart,
  PART_REGISTRY,
  resolvePartComponent,
} from "../PartRegistry";

describe("PART_REGISTRY", () => {
  it("contains subtitle_styles category", () => {
    expect("subtitle_styles" in PART_REGISTRY).toBe(true);
  });

  it("registers minimal subtitle component", () => {
    expect("minimal" in PART_REGISTRY.subtitle_styles).toBe(true);
  });

  it("registers fade_in subtitle component (Phase 4-A)", () => {
    expect("fade_in" in PART_REGISTRY.subtitle_styles).toBe(true);
  });

  it("registers karaoke_bold subtitle component (Phase 4-A)", () => {
    expect("karaoke_bold" in PART_REGISTRY.subtitle_styles).toBe(true);
  });

  it("contains stickers category (Phase 4-B)", () => {
    expect("stickers" in PART_REGISTRY).toBe(true);
  });

  it("registers all 5 sticker components (Phase 4-B)", () => {
    for (const id of [
      "exclaim_red",
      "question_mark",
      "sparkle",
      "thumbs_up",
      "fire",
    ]) {
      expect(id in PART_REGISTRY.stickers).toBe(true);
    }
  });

  it("contains filter_presets category (Phase 4-C)", () => {
    expect("filter_presets" in PART_REGISTRY).toBe(true);
  });

  it("registers all 5 filter_preset components (Phase 4-C)", () => {
    for (const id of [
      "none",
      "warm_cinematic",
      "cool_blue",
      "monochrome",
      "vintage",
    ]) {
      expect(id in PART_REGISTRY.filter_presets).toBe(true);
    }
  });

  it("contains camera_moves category (Phase 4-D)", () => {
    expect("camera_moves" in PART_REGISTRY).toBe(true);
  });

  it("registers all 4 camera_move components (Phase 4-D)", () => {
    for (const id of [
      "none",
      "subtle_zoom_in",
      "ken_burns",
      "dolly_pull_back",
    ]) {
      expect(id in PART_REGISTRY.camera_moves).toBe(true);
    }
  });

  it("contains lower_thirds category (Phase 4-E)", () => {
    expect("lower_thirds" in PART_REGISTRY).toBe(true);
  });

  it("registers all 3 lower_third components (Phase 4-E)", () => {
    for (const id of ["name_banner", "role_caption", "quote_box"]) {
      expect(id in PART_REGISTRY.lower_thirds).toBe(true);
    }
  });

  it("contains title_cards category (Phase 4-F)", () => {
    expect("title_cards" in PART_REGISTRY).toBe(true);
  });

  it("registers all 3 title_card components (Phase 4-F)", () => {
    for (const id of ["simple_intro", "subscribe_outro", "section_break"]) {
      expect(id in PART_REGISTRY.title_cards).toBe(true);
    }
  });

  it("contains transitions category (Phase 4-G)", () => {
    expect("transitions" in PART_REGISTRY).toBe(true);
  });

  it("registers all 4 transition components (Phase 4-G)", () => {
    for (const id of ["cut", "dip_to_black", "dip_to_white", "fade_quick"]) {
      expect(id in PART_REGISTRY.transitions).toBe(true);
    }
  });

  it("contains frame_layouts category (Phase 4-H)", () => {
    expect("frame_layouts" in PART_REGISTRY).toBe(true);
  });

  it("registers all 3 frame_layout components (Phase 4-H)", () => {
    for (const id of ["full", "letterbox_top_bottom", "centered_with_blur"]) {
      expect(id in PART_REGISTRY.frame_layouts).toBe(true);
    }
  });
});

describe("isKnownPart", () => {
  it("returns true for known part", () => {
    expect(isKnownPart("subtitle_styles", "minimal")).toBe(true);
    expect(isKnownPart("subtitle_styles", "fade_in")).toBe(true);
    expect(isKnownPart("subtitle_styles", "karaoke_bold")).toBe(true);
  });

  it("returns false for unknown id", () => {
    expect(isKnownPart("subtitle_styles", "nonexistent")).toBe(false);
  });

  it("returns false for unknown category", () => {
    expect(isKnownPart("nonexistent_category", "minimal")).toBe(false);
  });
});

describe("resolvePartComponent", () => {
  it("returns component for known part", () => {
    for (const id of ["minimal", "fade_in", "karaoke_bold"]) {
      const cmp = resolvePartComponent("subtitle_styles", id);
      expect(cmp).toBeDefined();
      expect(typeof cmp).toBe("function");
    }
  });

  it("throws with helpful message for unknown id", () => {
    expect(() => resolvePartComponent("subtitle_styles", "ghost")).toThrow(
      /unknown part.*subtitle_styles.*ghost/,
    );
  });
});
