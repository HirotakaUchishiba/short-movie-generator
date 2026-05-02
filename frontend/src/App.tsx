import { Routes, Route, Navigate } from "react-router-dom";
import ProjectList from "./components/ProjectList";
import ProjectShell from "./components/ProjectShell";
import StageScript from "./components/stages/StageScript";
import StageTTS from "./components/stages/StageTTS";
import StageBG from "./components/stages/StageBG";
import StageKling from "./components/stages/StageKling";
import StageScene from "./components/stages/StageScene";
import StageOverlay from "./components/stages/StageOverlay";
import StageFinal from "./components/stages/StageFinal";
import AnalyzePage from "./pages/AnalyzePage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ProjectList />} />
      <Route path="/analyze" element={<AnalyzePage />} />
      <Route path="/project/:ts" element={<ProjectShell />}>
        <Route index element={<Navigate to="script" replace />} />
        <Route path="script" element={<StageScript />} />
        <Route path="tts" element={<StageTTS />} />
        <Route path="bg" element={<StageBG />} />
        <Route path="kling" element={<StageKling />} />
        <Route path="scene" element={<StageScene />} />
        <Route path="overlay" element={<StageOverlay />} />
        <Route path="final" element={<StageFinal />} />
      </Route>
    </Routes>
  );
}
