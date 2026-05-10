import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import AnalyzeJobView from "./AnalyzeJobView";

vi.mock("../api", () => ({
  api: {
    getAnalyzeJob: vi.fn(),
    cancelAnalyzeJob: vi.fn(),
    confirmAnalyzeJob: vi.fn(),
    createProject: vi.fn(),
    analyzeJobEventSource: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    body: unknown;
    constructor(status: number, body: unknown) {
      super(`HTTP ${status}`);
      this.status = status;
      this.body = body;
    }
  },
}));

import { api } from "../api";

interface FakeEventSource {
  addEventListener: (
    type: string,
    listener: (ev: { data: string }) => void,
  ) => void;
  close: () => void;
  onerror: ((this: EventSource, ev: Event) => unknown) | null;
  readyState: number;
  emit: (type: string, data: unknown) => void;
}

function makeFakeEventSource(): FakeEventSource {
  const listeners: Record<string, ((ev: { data: string }) => void)[]> = {};
  return {
    addEventListener: (type, listener) => {
      (listeners[type] ||= []).push(listener);
    },
    close: () => {},
    onerror: null,
    readyState: 0,
    emit: (type, data) => {
      const ls = listeners[type] || [];
      for (const l of ls) l({ data: JSON.stringify(data) });
    },
  };
}

const mockGetJob = api.getAnalyzeJob as ReturnType<typeof vi.fn>;
const mockEventSource = api.analyzeJobEventSource as ReturnType<typeof vi.fn>;

function baseJobDetail() {
  return {
    id: "job_test_1",
    video_sha256: "deadbeef",
    options: {},
    status: "running",
    current_phase: "save",
    error: null,
    estimated_cost_usd: null,
    actual_cost_usd: null,
    screenplay_path: null,
    style_name: null,
    created_at: "2026-05-10T00:00:00Z",
    started_at: "2026-05-10T00:00:00Z",
    finished_at: null,
    cancellation_requested: false,
    phases: [],
  };
}

describe("AnalyzeJobView annotation_stats", () => {
  let fakeEs: FakeEventSource;

  beforeEach(() => {
    fakeEs = makeFakeEventSource();
    mockGetJob.mockReset();
    mockEventSource.mockReset();
    mockEventSource.mockReturnValue(fakeEs);
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("phase_complete:save に annotation_stats が乗っていれば hit / by_intent_id / demoted を表示", async () => {
    mockGetJob.mockResolvedValue(baseJobDetail());

    render(
      <MemoryRouter>
        <AnalyzeJobView jobId="job_test_1" />
      </MemoryRouter>,
    );

    // 初回ロード完了
    await waitFor(() => {
      expect(mockGetJob).toHaveBeenCalled();
    });

    // SSE event 流す: save 完了 (annotation_stats 同梱) + completed
    act(() => {
      fakeEs.emit("phase_complete", {
        phase: "save",
        output_path: "/tmp/screenplays/auto_x.json",
        annotation_stats: {
          total_scenes: 5,
          with_visual_intent_id: 3,
          low_confidence_demoted: 2,
          by_intent_id: {
            talking_head_calm: 2,
            reaction_surprise: 1,
          },
        },
      });
      fakeEs.emit("completed", {
        output_path: "/tmp/screenplays/auto_x.json",
      });
    });

    await waitFor(() => {
      expect(screen.getByTestId("annotation-stats")).toBeInTheDocument();
    });
    const statsEl = screen.getByTestId("annotation-stats");
    expect(statsEl.textContent).toMatch(/3/); // hit
    expect(statsEl.textContent).toMatch(/5 scenes/);
    expect(statsEl.textContent).toMatch(/talking_head_calm: 2/);
    expect(statsEl.textContent).toMatch(/reaction_surprise: 1/);
    expect(statsEl.textContent).toMatch(/low conf demoted: 2/);
  });

  it("annotation_stats が無い phase_complete:save では UI に出さない", async () => {
    mockGetJob.mockResolvedValue(baseJobDetail());

    render(
      <MemoryRouter>
        <AnalyzeJobView jobId="job_test_1" />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(mockGetJob).toHaveBeenCalled();
    });

    act(() => {
      fakeEs.emit("phase_complete", {
        phase: "save",
        output_path: "/tmp/x.json",
      });
      fakeEs.emit("completed", { output_path: "/tmp/x.json" });
    });

    // 完了サマリは出ているが annotation-stats は出ていない
    await waitFor(() => {
      expect(screen.getByText(/台本作成完了/)).toBeInTheDocument();
    });
    expect(screen.queryByTestId("annotation-stats")).toBeNull();
  });

  it("suggested_intents が乗っていれば 候補件数 + IntentCatalog へのリンクを表示", async () => {
    mockGetJob.mockResolvedValue(baseJobDetail());

    render(
      <MemoryRouter>
        <AnalyzeJobView jobId="job_test_1" />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(mockGetJob).toHaveBeenCalled();
    });

    act(() => {
      fakeEs.emit("phase_complete", {
        phase: "save",
        output_path: "/tmp/x.json",
        annotation_stats: {
          total_scenes: 5,
          with_visual_intent_id: 2,
          low_confidence_demoted: 3,
          by_intent_id: { talking_head_calm: 2 },
        },
        suggested_intents: [
          {
            proposed_id: "proposed_subject_is_gardenin",
            description: "subject is gardening with tools",
            scene_indices: [1, 2],
            rationale: "2 consecutive scenes had no good match",
          },
        ],
      });
      fakeEs.emit("completed", { output_path: "/tmp/x.json" });
    });

    await waitFor(() => {
      expect(screen.getByTestId("suggested-intents")).toBeInTheDocument();
    });
    const el = screen.getByTestId("suggested-intents");
    expect(el.textContent).toMatch(/1 件/);
    const link = el.querySelector("a");
    expect(link).not.toBeNull();
    expect(link?.getAttribute("href")).toBe("/intent-catalog#suggestions");
  });

  it("suggested_intents が空 list なら表示しない", async () => {
    mockGetJob.mockResolvedValue(baseJobDetail());

    render(
      <MemoryRouter>
        <AnalyzeJobView jobId="job_test_1" />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(mockGetJob).toHaveBeenCalled();
    });

    act(() => {
      fakeEs.emit("phase_complete", {
        phase: "save",
        output_path: "/tmp/x.json",
        suggested_intents: [],
      });
      fakeEs.emit("completed", { output_path: "/tmp/x.json" });
    });

    await waitFor(() => {
      expect(screen.getByText(/台本作成完了/)).toBeInTheDocument();
    });
    expect(screen.queryByTestId("suggested-intents")).toBeNull();
  });

  it("全シーンが demoted (= by_intent_id 空) でも demoted 件数だけは表示", async () => {
    mockGetJob.mockResolvedValue(baseJobDetail());

    render(
      <MemoryRouter>
        <AnalyzeJobView jobId="job_test_1" />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(mockGetJob).toHaveBeenCalled();
    });

    act(() => {
      fakeEs.emit("phase_complete", {
        phase: "save",
        output_path: "/tmp/x.json",
        annotation_stats: {
          total_scenes: 4,
          with_visual_intent_id: 0,
          low_confidence_demoted: 4,
          by_intent_id: {},
        },
      });
      fakeEs.emit("completed", { output_path: "/tmp/x.json" });
    });

    await waitFor(() => {
      expect(screen.getByTestId("annotation-stats")).toBeInTheDocument();
    });
    const statsEl = screen.getByTestId("annotation-stats");
    expect(statsEl.textContent).toMatch(/0/);
    expect(statsEl.textContent).toMatch(/4 scenes/);
    expect(statsEl.textContent).toMatch(/low conf demoted: 4/);
  });
});
