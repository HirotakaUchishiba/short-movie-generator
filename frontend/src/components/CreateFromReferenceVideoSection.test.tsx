import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import CreateFromReferenceVideoSection from "./CreateFromReferenceVideoSection";

vi.mock("../api", () => ({
  api: {
    createProjectFromReferenceVideo: vi.fn(),
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

import { api, ApiError } from "../api";

const mockCreate = api.createProjectFromReferenceVideo as ReturnType<
  typeof vi.fn
>;

function getInput(): HTMLInputElement {
  return screen.getByLabelText("参考動画を選択") as HTMLInputElement;
}

function uploadFile(name = "ref.mp4") {
  const file = new File([new Uint8Array([0])], name, { type: "video/mp4" });
  fireEvent.change(getInput(), { target: { files: [file] } });
  return file;
}

describe("CreateFromReferenceVideoSection", () => {
  beforeEach(() => {
    mockCreate.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("動画未選択で submit すると validation エラーが出る", async () => {
    const onSuccess = vi.fn();
    render(<CreateFromReferenceVideoSection onSuccess={onSuccess} />);
    // file 無しだとボタン disabled なので、内部 onSubmit を直接トリガするため
    // 1) file 選択 → 2) クリア (= setFile(null)) ... は input 経由では難しい。
    // 代わりに「ファイル選択前はボタンが disabled」を確認する。
    const button = screen.getByRole("button", {
      name: /作成して分析を開始/,
    });
    expect(button).toBeDisabled();
  });

  it("ファイル選択後、submit で API を呼び onSuccess が発火する", async () => {
    mockCreate.mockResolvedValue({
      ts: "20260510_120000",
      analyze_job_id: "analyze_xyz",
    });
    const onSuccess = vi.fn();
    render(<CreateFromReferenceVideoSection onSuccess={onSuccess} />);

    const file = uploadFile();
    const button = screen.getByRole("button", {
      name: /作成して分析を開始/,
    });
    expect(button).not.toBeDisabled();
    fireEvent.click(button);

    await waitFor(() => {
      expect(mockCreate).toHaveBeenCalledTimes(1);
    });
    const args = mockCreate.mock.calls[0];
    expect(args[0]).toBe(file);
    expect(args[1]).toEqual({ fps: 2.0 });

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalledWith("20260510_120000", "analyze_xyz");
    });
  });

  it("fps が options に乗る", async () => {
    mockCreate.mockResolvedValue({ ts: "x", analyze_job_id: "y" });
    render(<CreateFromReferenceVideoSection onSuccess={vi.fn()} />);

    uploadFile();

    fireEvent.click(screen.getByText(/高度な設定/));
    const fpsInput = screen.getByLabelText(/フレーム抽出 fps/);
    fireEvent.change(fpsInput, { target: { value: "1.5" } });

    fireEvent.click(screen.getByRole("button", { name: /作成して分析を開始/ }));
    await waitFor(() => {
      expect(mockCreate).toHaveBeenCalled();
    });
    const args = mockCreate.mock.calls[0];
    expect(args[1]).toEqual({ fps: 1.5 });
  });

  it("ApiError は body.message でメッセージを表示する", async () => {
    mockCreate.mockRejectedValue(
      new ApiError(400, "ignored raw text", {
        error_code: "REFERENCE_VIDEO_UNSUPPORTED_EXT",
        message: "unsupported extension",
      }),
    );
    render(<CreateFromReferenceVideoSection onSuccess={vi.fn()} />);

    uploadFile();
    fireEvent.click(screen.getByRole("button", { name: /作成して分析を開始/ }));
    await waitFor(() => {
      expect(screen.getByText("unsupported extension")).toBeInTheDocument();
    });
  });
});
