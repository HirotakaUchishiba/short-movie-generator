import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { StageFailureAlert } from "./StageFailureAlert";
import type { StageErrorDetail } from "../../types";

const DETAIL: StageErrorDetail = {
  type: "credit_exhausted",
  message: "Your credit balance is too low to access the Anthropic API.",
  request_id: "req_011CavqQUq",
  actionable_hint:
    "API クレジットが不足しています。プロバイダのダッシュボードでクレジット購入後、リトライしてください。",
  retry_cost_estimate_usd: 3.3,
  occurred_at: "2026-05-11T22:09:22",
  failed_phase: "claude",
};

describe("StageFailureAlert", () => {
  it("renders nothing when errorDetail is null", () => {
    const { container } = render(
      <StageFailureAlert stageLabel="分析" errorDetail={null} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("displays type label, actionable_hint and failed_phase", () => {
    render(<StageFailureAlert stageLabel="分析" errorDetail={DETAIL} />);
    expect(screen.getByText(/分析 で失敗しました/)).toBeInTheDocument();
    expect(screen.getByText(/クレジット切れ/)).toBeInTheDocument();
    expect(screen.getByText(/claude phase/)).toBeInTheDocument();
    expect(screen.getByTestId("stage-failure-hint").textContent).toContain(
      "API クレジット",
    );
  });

  it("hides message details by default and reveals on click", () => {
    render(<StageFailureAlert stageLabel="分析" errorDetail={DETAIL} />);
    const summary = screen.getByText(/詳細を表示/);
    fireEvent.click(summary);
    expect(screen.getByTestId("stage-failure-message").textContent).toContain(
      "credit balance is too low",
    );
    expect(screen.getByText(/req_011CavqQUq/)).toBeInTheDocument();
    expect(screen.getByText(/2026-05-11T22:09:22/)).toBeInTheDocument();
    expect(screen.getByText(/\$3\.30/)).toBeInTheDocument();
  });

  it("invokes onRetry / onDelete / onDismiss callbacks", () => {
    const onRetry = vi.fn();
    const onDelete = vi.fn();
    const onDismiss = vi.fn();
    render(
      <StageFailureAlert
        stageLabel="分析"
        errorDetail={DETAIL}
        onRetry={onRetry}
        onDelete={onDelete}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /リトライ/ }));
    fireEvent.click(screen.getByRole("button", { name: /削除/ }));
    fireEvent.click(screen.getByRole("button", { name: /後で/ }));
    expect(onRetry).toHaveBeenCalledOnce();
    expect(onDelete).toHaveBeenCalledOnce();
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("does not render action row when no callbacks are passed", () => {
    render(<StageFailureAlert stageLabel="分析" errorDetail={DETAIL} />);
    expect(screen.queryByRole("button", { name: /リトライ/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /削除/ })).toBeNull();
  });

  it("shows retryHint as secondary text", () => {
    render(
      <StageFailureAlert
        stageLabel="分析"
        errorDetail={DETAIL}
        retryHint="retry は cache が効くので追加課金は最小"
      />,
    );
    expect(screen.getByText(/cache が効く/)).toBeInTheDocument();
  });

  it("falls back to type code when label is missing (e.g. unknown)", () => {
    const detail: StageErrorDetail = {
      type: "unknown",
      message: "Some novel error",
    };
    render(<StageFailureAlert stageLabel="TTS" errorDetail={detail} />);
    expect(screen.getByText(/不明/)).toBeInTheDocument();
  });

  it("does not crash when actionable_hint is missing", () => {
    const detail: StageErrorDetail = {
      type: "unknown",
      message: "x",
    };
    render(<StageFailureAlert stageLabel="TTS" errorDetail={detail} />);
    expect(screen.getByText(/TTS で失敗しました/)).toBeInTheDocument();
  });
});
