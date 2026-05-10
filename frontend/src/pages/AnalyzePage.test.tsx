import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import AnalyzePage from "./AnalyzePage";

vi.mock("../api", () => ({
  api: {
    listReferenceVideos: vi.fn(),
    listAnalyzeJobs: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    bodyText: string;
    body: unknown;
    constructor(status: number, bodyText: string, body: unknown) {
      super(`${status}: ${bodyText}`);
      this.status = status;
      this.bodyText = bodyText;
      this.body = body;
    }
  },
}));

import { api } from "../api";

describe("AnalyzePage deprecation banner", () => {
  beforeEach(() => {
    (api.listReferenceVideos as ReturnType<typeof vi.fn>).mockResolvedValue({
      reference_videos: [],
    });
    (api.listAnalyzeJobs as ReturnType<typeof vi.fn>).mockResolvedValue({
      jobs: [],
    });
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("Phase D banner: TOP の主動作 CTA への誘導が表示される", async () => {
    render(
      <MemoryRouter>
        <AnalyzePage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(
        screen.getByTestId("standalone-analyze-deprecation-banner"),
      ).toBeInTheDocument();
    });
    const banner = screen.getByTestId("standalone-analyze-deprecation-banner");
    expect(banner.textContent).toMatch(/Stage 0 として project に統合/);
    expect(banner.textContent).toMatch(/参考動画から作成/);
  });
});
