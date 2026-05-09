import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  api: {
    qaTags: vi.fn(),
  },
}));

import { api } from "./api";
import { _resetQaTagsCache, fetchQaTags } from "./qaCategories";

const mockQaTags = api.qaTags as ReturnType<typeof vi.fn>;

const SAMPLE = {
  failure_tags: [{ value: "audio_silence", label: "無音", stage: "tts" }],
  emotions: ["驚き"],
};

describe("fetchQaTags", () => {
  beforeEach(() => {
    _resetQaTagsCache();
    mockQaTags.mockReset();
  });
  afterEach(() => {
    _resetQaTagsCache();
  });

  it("初回 fetch 後はキャッシュから返る (= 2 回目は API を呼ばない)", async () => {
    mockQaTags.mockResolvedValue(SAMPLE);
    const a = await fetchQaTags();
    const b = await fetchQaTags();
    expect(a).toBe(b);
    expect(mockQaTags).toHaveBeenCalledTimes(1);
  });

  it("並行呼出しは inflight Promise を共有して 1 回だけ fetch する", async () => {
    type Resolver = (v: typeof SAMPLE) => void;
    let resolveQa: Resolver | undefined;
    mockQaTags.mockImplementation(
      () =>
        new Promise<typeof SAMPLE>((res) => {
          resolveQa = res;
        }),
    );
    const p1 = fetchQaTags();
    const p2 = fetchQaTags();
    // mockImplementation で渡した Promise の executor は同期実行されるので
    // ここに到達した時点で resolveQa は必ず set 済み。TS narrowing が
    // closure を超えて伝播しないので明示的に assert する。
    (resolveQa as Resolver)(SAMPLE);
    const [r1, r2] = await Promise.all([p1, p2]);
    expect(r1).toBe(r2);
    expect(mockQaTags).toHaveBeenCalledTimes(1);
  });

  it("失敗したらキャッシュを残さない (= 次回再 fetch される)", async () => {
    mockQaTags.mockRejectedValueOnce(new Error("net"));
    await expect(fetchQaTags()).rejects.toThrow();
    mockQaTags.mockResolvedValueOnce(SAMPLE);
    const second = await fetchQaTags();
    expect(second).toEqual(SAMPLE);
    expect(mockQaTags).toHaveBeenCalledTimes(2);
  });
});
