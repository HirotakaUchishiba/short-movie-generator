import { Routes, Route, Navigate } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import ProjectList from "./components/ProjectList";
import ProjectShell from "./components/ProjectShell";
import StageScript from "./components/stages/StageScript";
import StageTTS from "./components/stages/StageTTS";
import StageBG from "./components/stages/StageBG";
import StageKling from "./components/stages/StageKling";
import StageScene from "./components/stages/StageScene";
import StageOverlay from "./components/stages/StageOverlay";
import StageBGM from "./components/stages/StageBGM";
import StageFinalImport from "./components/stages/StageFinalImport";
import StagePublish from "./components/stages/StagePublish";
import AnalyzeStage0Page from "./pages/AnalyzeStage0Page";
import IntentCatalogPage from "./pages/IntentCatalogPage";

export default function App() {
  return (
    <Routes>
      <Route
        path="/"
        element={
          <ErrorBoundary context="ProjectList">
            <ProjectList />
          </ErrorBoundary>
        }
      />
      <Route
        path="/intent-catalog"
        element={
          <ErrorBoundary context="IntentCatalog">
            <IntentCatalogPage />
          </ErrorBoundary>
        }
      />
      {/* Stage 0 page (= ProjectShell の outlet ではない、独立 layout) */}
      <Route
        path="/project/:ts/analyze"
        element={
          <ErrorBoundary context="AnalyzeStage0">
            <AnalyzeStage0Page />
          </ErrorBoundary>
        }
      />
      <Route
        path="/project/:ts"
        element={
          <ErrorBoundary context="ProjectShell">
            <ProjectShell />
          </ErrorBoundary>
        }
      >
        <Route index element={<Navigate to="script" replace />} />
        <Route
          path="script"
          element={
            <ErrorBoundary context="StageScript">
              <StageScript />
            </ErrorBoundary>
          }
        />
        <Route
          path="tts"
          element={
            <ErrorBoundary context="StageTTS">
              <StageTTS />
            </ErrorBoundary>
          }
        />
        <Route
          path="bg"
          element={
            <ErrorBoundary context="StageBG">
              <StageBG />
            </ErrorBoundary>
          }
        />
        <Route
          path="kling"
          element={
            <ErrorBoundary context="StageKling">
              <StageKling />
            </ErrorBoundary>
          }
        />
        <Route
          path="scene"
          element={
            <ErrorBoundary context="StageScene">
              <StageScene />
            </ErrorBoundary>
          }
        />
        <Route
          path="overlay"
          element={
            <ErrorBoundary context="StageOverlay">
              <StageOverlay />
            </ErrorBoundary>
          }
        />
        <Route
          path="bgm"
          element={
            <ErrorBoundary context="StageBGM">
              <StageBGM />
            </ErrorBoundary>
          }
        />
        <Route
          path="final_import"
          element={
            <ErrorBoundary context="StageFinalImport">
              <StageFinalImport />
            </ErrorBoundary>
          }
        />
        <Route
          path="publish"
          element={
            <ErrorBoundary context="StagePublish">
              <StagePublish />
            </ErrorBoundary>
          }
        />
      </Route>
    </Routes>
  );
}
