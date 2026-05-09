import { useSyncExternalStore } from "react";
import { api } from "./api";

export interface PresetData {
  libraries: Record<string, Record<string, string>>;
  labels_ja: Record<string, Record<string, string>>;
  category_labels_ja: Record<string, string>;
  emotion_default_preset_ids: Record<string, Record<string, string>>;
}

let cached: PresetData | null = null;
let inflight: Promise<PresetData> | null = null;
let lastError: string | null = null;
const subs = new Set<() => void>();

function notify(): void {
  for (const cb of subs) cb();
}

function ensureFetching(): void {
  if (cached !== null || inflight !== null) return;
  inflight = api
    .presets()
    .then((d) => {
      cached = d as PresetData;
      lastError = null;
      return cached;
    })
    .catch((e) => {
      lastError = String(e);
      throw e;
    })
    .finally(() => {
      inflight = null;
      notify();
    });
}

function subscribe(cb: () => void): () => void {
  subs.add(cb);
  ensureFetching();
  return () => {
    subs.delete(cb);
  };
}

function getSnapshot(): PresetData | null {
  return cached;
}

export function usePresets(): {
  data: PresetData | null;
  error: string | null;
} {
  const data = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  return { data, error: lastError };
}
