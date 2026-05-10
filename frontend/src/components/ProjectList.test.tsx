import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import ProjectList from "./ProjectList";

vi.mock("../api", () => ({
  api: {
    projects: vi.fn(),
    createProject: vi.fn(),
    createProjectFromReferenceVideo: vi.fn(),
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
    await waitFor(() => {
      expect(screen.getByText(/⚠ 分析失敗/)).toBeInTheDocument();
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
