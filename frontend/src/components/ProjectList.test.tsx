import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import ProjectList from "./ProjectList";

vi.mock("../api", () => ({
  api: {
    projects: vi.fn(),
    createProject: vi.fn(),
    createProjectFromReferenceVideo: vi.fn(),
    deleteProject: vi.fn(),
    bulkDeleteProjects: vi.fn(),
  },
  bgAssetUrl: () => "/fake-bg.png",
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

const mockProjects = api.projects as ReturnType<typeof vi.fn>;

function makeProject(overrides: Record<string, unknown> = {}) {
  return {
    timestamp: "20260510_120000",
    screenplay_name: "auto_x.json",
    display_title: "Demo title",
    caption_hashtags: "",
    scene_count: 3,
    has_bg_thumbnail: false,
    created_at: "2026-05-10T12:00:00Z",
    current_stage: "tts",
    progress: { stages: {} },
    ...overrides,
  };
}

function renderList() {
  return render(
    <MemoryRouter>
      <ProjectList />
    </MemoryRouter>,
  );
}

describe("ProjectList Stage 0 badges + CTA reorg", () => {
  beforeEach(() => {
    mockProjects.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("主動作 CTA = CreateFromReferenceVideoSection が表示され、legacy section は折りたたみ", async () => {
    mockProjects.mockResolvedValue({ projects: [], screenplays: [] });
    renderList();
    await waitFor(() => {
      expect(
        screen.getByTestId("create-from-reference-video-section"),
      ).toBeInTheDocument();
    });
    const legacy = screen.getByTestId("legacy-template-section");
    expect(legacy.tagName.toLowerCase()).toBe("details");
    expect(legacy.hasAttribute("open")).toBe(false);
  });

  it("analyze_status='running' なら 📹 分析中 + /project/<TS>/analyze にリンク", async () => {
    mockProjects.mockResolvedValue({
      projects: [
        makeProject({
          screenplay_name: null,
          analyze_status: "running",
          analyze_job_id: "analyze_xyz",
          current_stage: null,
        }),
      ],
      screenplays: [],
    });
    renderList();
    await waitFor(() => {
      expect(screen.getByText(/📹 分析中/)).toBeInTheDocument();
    });
    const link = screen.getByText(/Demo title/).closest("a");
    expect(link?.getAttribute("href")).toBe("/project/20260510_120000/analyze");
  });

  it("analyze_status='failed' なら ⚠ 分析失敗 + /project/<TS>/analyze にリンク", async () => {
    mockProjects.mockResolvedValue({
      projects: [
        makeProject({
          screenplay_name: null,
          analyze_status: "failed",
        }),
      ],
      screenplays: [],
    });
    renderList();
    // badge は <span> なので button (= bulk-delete) と区別される
    await waitFor(() => {
      const badge = Array.from(document.querySelectorAll("span")).find(
        (el) => el.textContent === "⚠ 分析失敗",
      );
      expect(badge).toBeTruthy();
    });
    const link = screen.getByText(/Demo title/).closest("a");
    expect(link?.getAttribute("href")).toBe("/project/20260510_120000/analyze");
  });

  it("analyze_status='completed' なら通常 stage badge + /project/<TS> にリンク", async () => {
    mockProjects.mockResolvedValue({
      projects: [
        makeProject({
          analyze_status: "completed",
          current_stage: "tts",
        }),
      ],
      screenplays: [],
    });
    renderList();
    await waitFor(() => {
      expect(screen.getByText("TTS")).toBeInTheDocument();
    });
    const link = screen.getByText(/Demo title/).closest("a");
    expect(link?.getAttribute("href")).toBe("/project/20260510_120000");
  });
});

describe("ProjectList bulk-delete failed button", () => {
  const mockBulkDelete = api.bulkDeleteProjects as ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockProjects.mockReset();
    mockBulkDelete.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("失敗 0 件なら button は表示されない", async () => {
    mockProjects.mockResolvedValue({
      projects: [makeProject({ analyze_status: "completed" })],
      screenplays: [],
    });
    renderList();
    await waitFor(() => {
      expect(screen.getByText(/Demo title/)).toBeInTheDocument();
    });
    expect(screen.queryByTestId("bulk-delete-failed")).toBeNull();
  });

  it("失敗 1+ 件で N 件 表示、click で bulkDeleteProjects 呼ぶ", async () => {
    mockProjects.mockResolvedValue({
      projects: [
        makeProject({
          timestamp: "20260511_220521",
          analyze_status: "failed",
        }),
        makeProject({
          timestamp: "20260511_220522",
          analyze_status: "failed",
        }),
        makeProject({
          timestamp: "20260511_220523",
          analyze_status: "completed",
        }),
      ],
      screenplays: [],
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mockBulkDelete.mockResolvedValue({ deleted: [], failed: [] });

    renderList();
    await waitFor(() => {
      const btn = screen.getByTestId("bulk-delete-failed");
      expect(btn.textContent).toContain("2 件");
    });
    fireEvent.click(screen.getByTestId("bulk-delete-failed"));

    await waitFor(() => {
      expect(mockBulkDelete).toHaveBeenCalledWith([
        "20260511_220521",
        "20260511_220522",
      ]);
    });
  });

  it("confirm キャンセルなら API 呼ばない", async () => {
    mockProjects.mockResolvedValue({
      projects: [makeProject({ analyze_status: "failed" })],
      screenplays: [],
    });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderList();
    await waitFor(() => {
      expect(screen.getByTestId("bulk-delete-failed")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("bulk-delete-failed"));
    expect(mockBulkDelete).not.toHaveBeenCalled();
  });

  it("部分失敗 を inline error として表示", async () => {
    mockProjects.mockResolvedValue({
      projects: [
        makeProject({
          timestamp: "20260511_220521",
          analyze_status: "failed",
        }),
        makeProject({
          timestamp: "20260511_220522",
          analyze_status: "failed",
        }),
      ],
      screenplays: [],
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mockBulkDelete.mockResolvedValue({
      deleted: ["20260511_220521"],
      failed: [
        {
          ts: "20260511_220522",
          error_code: "PROJECT_DELETE_FAILED",
          message: "disk error",
        },
      ],
    });

    renderList();
    await waitFor(() => {
      expect(screen.getByTestId("bulk-delete-failed")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("bulk-delete-failed"));

    await waitFor(() => {
      const err = screen.getByTestId("bulk-delete-error");
      expect(err.textContent).toContain("1 件失敗");
      expect(err.textContent).toContain("PROJECT_DELETE_FAILED");
    });
  });
});
