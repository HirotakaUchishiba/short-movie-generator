import { Routes, Route, Navigate } from "react-router-dom";
import ProjectList from "./components/ProjectList";
import ProjectShell from "./components/ProjectShell";
import StageScript from "./components/stages/StageScript";
import StageTTS from "./components/stages/StageTTS";
import StageBG from "./components/stages/StageBG";
import StageKling from "./components/stages/StageKling";
import StageScene from "./components/stages/StageScene";
import StageOverlay from "./components/stages/StageOverlay";
import StageFinalImport from "./components/stages/StageFinalImport";
import StagePublish from "./components/stages/StagePublish";
import AnalyzeStage0Page from "./pages/AnalyzeStage0Page";
import IntentCatalogPage from "./pages/IntentCatalogPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ProjectList />} />
      <Route path="/intent-catalog" element={<IntentCatalogPage />} />
      {/* Stage 0 page (= ProjectShell の outlet ではない、独立 layout) */}
      <Route path="/project/:ts/analyze" element={<AnalyzeStage0Page />} />
      <Route path="/project/:ts" element={<ProjectShell />}>
        <Route index element={<Navigate to="script" replace />} />
        <Route path="script" element={<StageScript />} />
        <Route path="tts" element={<StageTTS />} />
        <Route path="bg" element={<StageBG />} />
        <Route path="kling" element={<StageKling />} />
        <Route path="scene" element={<StageScene />} />
        <Route path="overlay" element={<StageOverlay />} />
        <Route path="final_import" element={<StageFinalImport />} />
        <Route path="publish" element={<StagePublish />} />
      </Route>
    </Routes>
  );
}
