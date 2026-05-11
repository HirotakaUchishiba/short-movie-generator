import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import AnalyzeStage0Page from "./AnalyzeStage0Page";

// AnalyzeJobView は SSE + API を持つ重い component なので軽量 stub に差し替え。
// 本 page の責務 (= analyze_status による分岐) だけ検証する。
vi.mock("../components/AnalyzeJobView", () => ({
  default: ({ jobId, projectTs }: { jobId: string; projectTs: string }) => (
    <div data-testid="analyze-job-view">
      jobId={jobId} projectTs={projectTs}
    </div>
  ),
}));

vi.mock("../api", () => ({
  api: {
    project: vi.fn(),
    retryAnalyzeForProject: vi.fn(),
    deleteProject: vi.fn(),
  },
}));

import { api } from "../api";

const mockProject = api.project as ReturnType<typeof vi.fn>;

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/project/:ts/analyze" element={<AnalyzeStage0Page />} />
        <Route
          path="/project/:ts/script"
          element={<div data-testid="script-page">Stage 1</div>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

function makeDetail(overrides: Record<string, unknown> = {}) {
  return {
    timestamp: "20260510_120000",
    screenplay_name: null,
    screenplay: null,
    progress: { stages: {} },
    current_stage: null,
    analyze_job_id: "analyze_xyz",
    analyze_status: "running",
    ...overrides,
  };
}

describe("AnalyzeStage0Page", () => {
  beforeEach(() => {
    mockProject.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("analyze_status='running' なら AnalyzeJobView を projectTs 付きで描画", async () => {
    mockProject.mockResolvedValue(makeDetail({ analyze_status: "running" }));
    renderAt("/project/20260510_120000/analyze");

    await waitFor(() => {
      expect(screen.getByTestId("analyze-job-view")).toBeInTheDocument();
    });
    const view = screen.getByTestId("analyze-job-view");
    expect(view.textContent).toMatch(/jobId=analyze_xyz/);
    expect(view.textContent).toMatch(/projectTs=20260510_120000/);
  });

  it("analyze_status='failed' なら StageFailureAlert (retry/delete/back) を表示", async () => {
    mockProject.mockResolvedValue(makeDetail({ analyze_status: "failed" }));
    renderAt("/project/20260510_120000/analyze");

    await waitFor(() => {
      expect(screen.getByText(/分析 で失敗しました/)).toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: /リトライ/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /削除/ })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /後で \(TOP に戻る\)/ }),
    ).toBeInTheDocument();
    // failed 時は AnalyzeJobView を描画しない
    expect(screen.queryByTestId("analyze-job-view")).toBeNull();
  });

  it("analyze_status='completed' なら /project/<TS>/script に redirect", async () => {
    mockProject.mockResolvedValue(
      makeDetail({
        analyze_status: "completed",
        screenplay_name: "auto_x.json",
      }),
    );
    renderAt("/project/20260510_120000/analyze");

    await waitFor(() => {
      expect(screen.getByTestId("script-page")).toBeInTheDocument();
    });
  });

  it("analyze_status=null + screenplay_name あり (= legacy 経路) も Stage 1 に redirect", async () => {
    mockProject.mockResolvedValue(
      makeDetail({
        analyze_status: null,
        analyze_job_id: null,
        screenplay_name: "manual.json",
      }),
    );
    renderAt("/project/20260510_120000/analyze");

    await waitFor(() => {
      expect(screen.getByTestId("script-page")).toBeInTheDocument();
    });
  });
});
