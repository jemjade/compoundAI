// 인증된 애플리케이션 Route와 각 Page Component를 정의한다.
import { Navigate, Outlet, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { getToken } from "./lib/api";
import { ComparePage } from "./pages/ComparePage";
import { DashboardPage } from "./pages/DashboardPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { ExperimentPage } from "./pages/ExperimentPage";
import { LoginPage } from "./pages/LoginPage";
import { NewExperimentPage } from "./pages/NewExperimentPage";
import { ParsersPage } from "./pages/ParsersPage";
import { ParserFormPage } from "./pages/ParserFormPage";
import { TasksPage } from "./pages/TasksPage";

function Protected() {
  return getToken() ? <Outlet /> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<Protected />}>
        <Route element={<Layout />}>
          <Route index element={<DashboardPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/parsers" element={<ParsersPage />} />
          <Route path="/parsers/new" element={<ParserFormPage />} />
          <Route path="/parsers/:id" element={<ParserFormPage />} />
          <Route path="/experiments/new" element={<NewExperimentPage />} />
          <Route path="/experiments/:id" element={<ExperimentPage />} />
          <Route path="/experiments/:id/compare" element={<ComparePage />} />
          <Route path="/evaluation" element={<EvaluationPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
