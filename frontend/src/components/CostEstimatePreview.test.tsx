import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { CostEstimatePreview } from "./CostEstimatePreview";

vi.mock("../api", () => ({
  api: {
    cost: {
      estimate: vi.fn(),
    },
  },
}));

import { api } from "../api";

const mockEstimate = api.cost.estimate as ReturnType<typeof vi.fn>;

describe("CostEstimatePreview", () => {
  beforeEach(() => {
    mockEstimate.mockReset();
  });

  it("history confidence のときに金額と n を表示する", async () => {
    mockEstimate.mockResolvedValue({
      cost_usd: 0.812,
      cost_jpy: 130,
      confidence: "history",
      sample_size: 12,
      breakdown: {},
      note: "",
    });
    render(
      <CostEstimatePreview
        stage="kling"
        params={{ duration_sec: 5, model: "kling" }}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/\$0\.812/)).toBeInTheDocument();
    });
    expect(screen.getByText(/履歴 median/)).toBeInTheDocument();
    expect(screen.getByText(/n=12/)).toBeInTheDocument();
  });

  it("insufficient のときは履歴不足ラベルを出す", async () => {
    mockEstimate.mockResolvedValue({
      cost_usd: null,
      cost_jpy: null,
      confidence: "insufficient",
      sample_size: 0,
      breakdown: {},
      note: "履歴がありません",
    });
    render(
      <CostEstimatePreview
        stage="bg"
        params={{ image_count: 1, model: "imagen" }}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/履歴不足/)).toBeInTheDocument();
    });
    expect(screen.getByText(/見積不可/)).toBeInTheDocument();
  });

  it("disabled のとき fetch しないし何も描画しない", () => {
    const { container } = render(
      <CostEstimatePreview
        stage="kling"
        params={{ duration_sec: 5, model: "kling" }}
        disabled
      />,
    );
    expect(mockEstimate).not.toHaveBeenCalled();
    expect(container.textContent).toBe("");
  });
});
