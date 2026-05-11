import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { DeleteProjectButton } from "./DeleteProjectButton";
import { api } from "../../api";

// confirm をテストごとに mock する
const confirmSpy = vi.spyOn(window, "confirm");

beforeEach(() => {
  confirmSpy.mockReset();
  vi.spyOn(api, "deleteProject").mockReset();
});

describe("DeleteProjectButton", () => {
  it("renders icon mode by default", () => {
    render(<DeleteProjectButton ts="20260511_220521" onDeleted={() => {}} />);
    expect(screen.getByRole("button").textContent).toContain("🗑");
    expect(screen.getByRole("button").textContent).not.toContain("削除");
  });

  it("renders label mode with 削除 text", () => {
    render(
      <DeleteProjectButton
        ts="20260511_220521"
        onDeleted={() => {}}
        mode="label"
      />,
    );
    expect(screen.getByRole("button").textContent).toContain("削除");
  });

  it("calls api.deleteProject + onDeleted when confirm OK", async () => {
    const onDeleted = vi.fn();
    confirmSpy.mockReturnValue(true);
    const deleteMock = vi
      .spyOn(api, "deleteProject")
      .mockResolvedValue({ ts: "20260511_220521", deleted: true });

    render(
      <DeleteProjectButton
        ts="20260511_220521"
        onDeleted={onDeleted}
        titleHint="My Project"
      />,
    );
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => {
      expect(deleteMock).toHaveBeenCalledWith("20260511_220521");
      expect(onDeleted).toHaveBeenCalledWith("20260511_220521");
    });
  });

  it("does NOT call api.deleteProject when confirm cancelled", () => {
    const onDeleted = vi.fn();
    confirmSpy.mockReturnValue(false);
    const deleteMock = vi.spyOn(api, "deleteProject");

    render(<DeleteProjectButton ts="20260511_220521" onDeleted={onDeleted} />);
    fireEvent.click(screen.getByRole("button"));
    expect(deleteMock).not.toHaveBeenCalled();
    expect(onDeleted).not.toHaveBeenCalled();
  });

  it("preserves card click suppression (preventDefault + stopPropagation)", () => {
    confirmSpy.mockReturnValue(false);
    const parentClick = vi.fn();
    render(
      <a href="/test" onClick={parentClick}>
        <DeleteProjectButton ts="20260511_220521" onDeleted={() => {}} />
      </a>,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(parentClick).not.toHaveBeenCalled();
  });

  it("shows ... during busy and re-enables after completion", async () => {
    confirmSpy.mockReturnValue(true);
    let resolveDelete: (v: { ts: string; deleted: true }) => void = () => {};
    const pending = new Promise<{ ts: string; deleted: true }>((res) => {
      resolveDelete = res;
    });
    vi.spyOn(api, "deleteProject").mockReturnValue(pending);

    render(<DeleteProjectButton ts="20260511_220521" onDeleted={() => {}} />);
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => {
      expect(screen.getByRole("button").textContent).toContain("...");
      expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(
        true,
      );
    });

    resolveDelete({ ts: "20260511_220521", deleted: true });
    await waitFor(() => {
      expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(
        false,
      );
    });
  });
});
