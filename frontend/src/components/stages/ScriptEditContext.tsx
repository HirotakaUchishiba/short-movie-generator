// Stage 1 (ScriptEditPanel) で共有される編集 state を Context 化する。
//
// 現状の ScriptEditPanel.tsx (= 1651 行) は SceneEditor などの sub-component
// に 12+ props を drill しているため、Context 経由でアクセスできるよう
// するための下地。将来 PR で SceneGridView.tsx / CaptionEditor.tsx /
// SpeakerMappingSection.tsx を抽出する際に各 sub-component が
// useScriptEdit() で必要な state だけ pick できるようにする。
//
// 参照: docs/plannings/2026-05-17_comprehensive-refactoring-plan.md §3.1.3-a

import { createContext, useContext } from "react";

import type {
  AbstractDiagnostics,
  AbstractScreenplay,
  AnalyzeJobDetail,
} from "../../types";

export interface ScriptEditContextValue {
  ts: string;
  jobId: string;
  job: AnalyzeJobDetail | null;
  abstract: AbstractScreenplay | null;
  setAbstract: (next: AbstractScreenplay | null) => void;
  diagnostics: AbstractDiagnostics | null;
  characterRefs: string[];
  locationIds: string[];
  dirty: boolean;
  setDirty: (next: boolean) => void;
}

export const ScriptEditContext = createContext<ScriptEditContextValue | null>(
  null,
);

export function useScriptEdit(): ScriptEditContextValue {
  const ctx = useContext(ScriptEditContext);
  if (!ctx) {
    throw new Error(
      "useScriptEdit() must be called inside <ScriptEditContext.Provider>",
    );
  }
  return ctx;
}
