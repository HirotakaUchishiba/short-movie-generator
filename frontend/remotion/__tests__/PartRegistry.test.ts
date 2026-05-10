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
});

describe("isKnownPart", () => {
  it("returns true for known part", () => {
    expect(isKnownPart("subtitle_styles", "minimal")).toBe(true);
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
    const cmp = resolvePartComponent("subtitle_styles", "minimal");
    expect(cmp).toBeDefined();
    expect(typeof cmp).toBe("function");
  });

  it("throws with helpful message for unknown id", () => {
    expect(() => resolvePartComponent("subtitle_styles", "ghost")).toThrow(
      /unknown part.*subtitle_styles.*ghost/,
    );
  });
});
