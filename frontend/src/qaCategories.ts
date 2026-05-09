// QA failure タグの表示メタを backend SSOT (/api/config/qa-tags) から取得する。
// `qa/categories.py` を唯一の真実とし、frontend で列挙を二重管理しない。
//
// 1 セッション内で結果をモジュール変数にキャッシュする。プロセス起動時に
// in-flight Promise を共有して重複 fetch を防ぐ。
import { useSyncExternalStore } from "react";
import { api } from "./api";
import type { QaFailureTagDef, QaTagsConfig } from "./types";

export type { QaFailureTagDef, QaTagsConfig };

let _cache: QaTagsConfig | null = null;
let _inFlight: Promise<QaTagsConfig> | null = null;
const _subs = new Set<() => void>();

function _notify(): void {
  for (const cb of _subs) cb();
}

export async function fetchQaTags(): Promise<QaTagsConfig> {
  if (_cache) return _cache;
  if (!_inFlight) {
    _inFlight = api
      .qaTags()
      .then((res) => {
        _cache = res;
        _notify();
        return res;
      })
      .finally(() => {
        _inFlight = null;
      });
  }
  return _inFlight;
}

function _subscribe(cb: () => void): () => void {
  _subs.add(cb);
  if (_cache === null) {
    void fetchQaTags().catch(() => {
      // fetch 失敗時は null のまま。RejectModal 側で「読み込み失敗」を表示する。
    });
  }
  return () => {
    _subs.delete(cb);
  };
}

function _getSnapshot(): QaTagsConfig | null {
  return _cache;
}

export function useQaTags(): QaTagsConfig | null {
  return useSyncExternalStore(_subscribe, _getSnapshot, _getSnapshot);
}

// テスト用: モジュールキャッシュをリセットする。
export function _resetQaTagsCache(): void {
  _cache = null;
  _inFlight = null;
  _notify();
}
