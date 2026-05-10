import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { IdentityEditor } from "./IdentityEditor";
import type { Identity } from "../types";

vi.mock("../api", () => ({
  api: {
    listCharacters: vi.fn(),
    listLocations: vi.fn(),
  },
}));

import { api } from "../api";

const mockListCharacters = api.listCharacters as ReturnType<typeof vi.fn>;
const mockListLocations = api.listLocations as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockListCharacters.mockReset();
  mockListLocations.mockReset();
  mockListCharacters.mockResolvedValue({ characters: ["f1", "m1"] });
  mockListLocations.mockResolvedValue({
    locations: [
      {
        id: "home_office",
        decor: "",
        lighting: "",
        color_palette: "",
        props: "",
        camera_distance: "medium",
      },
      {
        id: "kitchen",
        decor: "",
        lighting: "",
        color_palette: "",
        props: "",
        camera_distance: "medium",
      },
    ],
  });
});

describe("IdentityEditor", () => {
  it("4 fields すべて揃った時に onChange が完全 dict で呼ばれる", async () => {
    const onChange = vi.fn();
    render(<IdentityEditor onChange={onChange} />);
    await waitFor(() => expect(mockListCharacters).toHaveBeenCalled());
    // characters の button が描画されるまで待つ
    await waitFor(() => expect(screen.getByText("f1")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByText("f1"));
    // 1 field 揃った段階では undefined
    expect(onChange).toHaveBeenLastCalledWith(undefined);

    const selects = screen.getAllByRole("combobox");
    // selects[0] = location, selects[1] = start_emotion, selects[2] = camera_distance
    await user.selectOptions(selects[0], "home_office");
    expect(onChange).toHaveBeenLastCalledWith(undefined);

    await user.selectOptions(selects[1], "中立");
    expect(onChange).toHaveBeenLastCalledWith(undefined);

    await user.selectOptions(selects[2], "medium-close");

    const expected: Identity = {
      character_refs: ["f1"],
      location_ref: "home_office",
      start_emotion: "中立",
      camera_distance: "medium-close",
    };
    expect(onChange).toHaveBeenLastCalledWith(expected);
  });

  it("1 field 欠けた時に warning text 表示 + onChange(undefined)", async () => {
    const onChange = vi.fn();
    render(
      <IdentityEditor
        identity={{
          character_refs: ["f1"],
          location_ref: "home_office",
          start_emotion: "中立",
          camera_distance: "medium-close",
        }}
        onChange={onChange}
      />,
    );
    await waitFor(() => expect(screen.getByText("f1")).toBeInTheDocument());
    // 完全なので warning は出ない
    expect(screen.queryByText(/identity 不完全/)).not.toBeInTheDocument();

    const user = userEvent.setup();
    // location_ref を解除 (= 不完全化)
    const selects = screen.getAllByRole("combobox");
    await user.selectOptions(selects[0], "");

    expect(onChange).toHaveBeenLastCalledWith(undefined);
    expect(screen.getByText(/identity 不完全/)).toBeInTheDocument();
  });

  it("リセットボタンで onChange(undefined)", async () => {
    const onChange = vi.fn();
    render(
      <IdentityEditor
        identity={{
          character_refs: ["f1"],
          location_ref: "home_office",
          start_emotion: "中立",
          camera_distance: "medium-close",
        }}
        onChange={onChange}
      />,
    );
    await waitFor(() => expect(screen.getByText("f1")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByTitle(/identity を削除/));
    expect(onChange).toHaveBeenLastCalledWith(undefined);
    expect(screen.getByText(/identity 不完全/)).toBeInTheDocument();
  });

  it("identity prop が更新されたら draft も同期する", async () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <IdentityEditor identity={undefined} onChange={onChange} />,
    );
    await waitFor(() => expect(screen.getByText("f1")).toBeInTheDocument());
    expect(screen.getByText(/identity 不完全/)).toBeInTheDocument();

    await act(async () => {
      rerender(
        <IdentityEditor
          identity={{
            character_refs: ["f1"],
            location_ref: "home_office",
            start_emotion: "中立",
            camera_distance: "medium-close",
          }}
          onChange={onChange}
        />,
      );
    });
    expect(screen.queryByText(/identity 不完全/)).not.toBeInTheDocument();
  });
});
