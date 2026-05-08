// QA failure タグの表示メタを backend SSOT (/api/config/qa-tags) から取得する。
// `qa/categories.py` を唯一の真実とし、frontend で列挙を二重管理しない。
//
// 1 セッション内で結果をモジュール変数にキャッシュする。プロセス起動時に
// in-flight Promise を共有して重複 fetch を防ぐ。
import { useEffect, useState } from "react";
import { api } from "./api";
import type { QaFailureTagDef, QaTagsConfig } from "./types";

export type { QaFailureTagDef, QaTagsConfig };

let _cache: QaTagsConfig | null = null;
let _inFlight: Promise<QaTagsConfig> | null = null;

export async function fetchQaTags(): Promise<QaTagsConfig> {
  if (_cache) return _cache;
  if (!_inFlight) {
    _inFlight = api
      .qaTags()
      .then((res) => {
        _cache = res;
        return res;
      })
      .finally(() => {
        _inFlight = null;
      });
  }
  return _inFlight;
}

export function useQaTags(): QaTagsConfig | null {
  const [data, setData] = useState<QaTagsConfig | null>(_cache);
  useEffect(() => {
    if (data) return;
    let cancelled = false;
    fetchQaTags()
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        // fetch 失敗時は null のまま。RejectModal 側で「読み込み失敗」を表示する。
      });
    return () => {
      cancelled = true;
    };
  }, [data]);
  return data;
}

// テスト用: モジュールキャッシュをリセットする。
export function _resetQaTagsCache(): void {
  _cache = null;
  _inFlight = null;
}
