import { useEffect, useState } from "react";
import { api } from "./api";

export interface PresetData {
  libraries: Record<string, Record<string, string>>;
  labels_ja: Record<string, Record<string, string>>;
  category_labels_ja: Record<string, string>;
  emotion_default_preset_ids: Record<string, Record<string, string>>;
}

let cached: PresetData | null = null;
let inflight: Promise<PresetData> | null = null;

export function usePresets() {
  const [data, setData] = useState<PresetData | null>(cached);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (cached) {
      setData(cached);
      return;
    }
    if (!inflight) {
      inflight = api.presets().then((d) => {
        cached = d as PresetData;
        return cached;
      });
    }
    let alive = true;
    inflight
      .then((d) => {
        if (alive) setData(d);
      })
      .catch((e) => {
        if (alive) setError(String(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  return { data, error };
}
