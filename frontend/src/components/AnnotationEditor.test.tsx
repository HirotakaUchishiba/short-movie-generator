import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AnnotationEditor } from "./AnnotationEditor";
import {
  resetPartCatalogCache,
  type PartCatalogResponse,
} from "../hooks/usePartCatalog";

const fetchMock = vi.fn();

const sampleCatalog: PartCatalogResponse = {
  categories: {
    visual_intents: {
      category: "visual_intents",
      status: "ok",
      found: true,
      entries: [
        {
          id: "talking_head_calm",
          description: "穏やかに喋る",
          params_schema: {},
          valid_contexts: ["scene"],
          deprecated: false,
          valid_start_emotions: ["中立", "喜び", "満足", "困惑"],
          duration_buckets: [5, 10],
          motion_intensity_bucket: "low",
        },
        {
          id: "reaction_surprise",
          description: "驚きの反応",
          params_schema: {},
          valid_contexts: ["scene"],
          deprecated: false,
          valid_start_emotions: ["中立", "困惑"],
          duration_buckets: [5],
          motion_intensity_bucket: "low",
        },
      ],
    },
  },
};

beforeEach(() => {
  resetPartCatalogCache();
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => sampleCatalog,
    text: async () => JSON.stringify(sampleCatalog),
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AnnotationEditor", () => {
  it("visual_intent_id select で onChange", async () => {
    const onChange = vi.fn();
    render(<AnnotationEditor onChange={onChange} />);
    await waitFor(() =>
      expect(screen.getByText(/visual_intent_id/)).toBeInTheDocument(),
    );
    // catalog 読込完了を待つ
    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: "talking_head_calm" }),
      ).toBeInTheDocument(),
    );

    const user = userEvent.setup();
    const selects = screen.getAllByRole("combobox");
    // selects[0] = visual_intent_id
    await user.selectOptions(selects[0], "talking_head_calm");

    expect(onChange).toHaveBeenLastCalledWith({
      visual_intent_id: "talking_head_calm",
    });
  });

  it("全 field 空なら onChange(undefined)", async () => {
    const onChange = vi.fn();
    render(
      <AnnotationEditor
        annotation={{ visual_intent_id: "talking_head_calm" }}
        onChange={onChange}
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: "talking_head_calm" }),
      ).toBeInTheDocument(),
    );

    const user = userEvent.setup();
    const selects = screen.getAllByRole("combobox");
    // visual_intent_id を解除 → 全 field 空 → undefined
    await user.selectOptions(selects[0], "");
    expect(onChange).toHaveBeenLastCalledWith(undefined);
  });

  it("duration_bucket 単独でも onChange に annotation を渡す", async () => {
    const onChange = vi.fn();
    render(<AnnotationEditor onChange={onChange} />);
    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: "talking_head_calm" }),
      ).toBeInTheDocument(),
    );

    const user = userEvent.setup();
    const selects = screen.getAllByRole("combobox");
    // selects[1] = duration_bucket
    await user.selectOptions(selects[1], "10");
    expect(onChange).toHaveBeenLastCalledWith({ duration_bucket: 10 });
  });

  it("motion_intensity 単独でも onChange に annotation を渡す", async () => {
    const onChange = vi.fn();
    render(<AnnotationEditor onChange={onChange} />);
    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: "talking_head_calm" }),
      ).toBeInTheDocument(),
    );

    const user = userEvent.setup();
    const selects = screen.getAllByRole("combobox");
    // selects[2] = motion_intensity
    await user.selectOptions(selects[2], "high");
    expect(onChange).toHaveBeenLastCalledWith({ motion_intensity: "high" });
  });

  it("visual_intent_id 選択時に valid_start_emotions ヒントを表示", async () => {
    const onChange = vi.fn();
    render(
      <AnnotationEditor
        annotation={{ visual_intent_id: "talking_head_calm" }}
        onChange={onChange}
      />,
    );
    await waitFor(() => {
      expect(
        screen.getByText(/valid_start_emotions: 中立, 喜び, 満足, 困惑/),
      ).toBeInTheDocument();
    });
  });
});
