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
