import { Suspense, lazy, useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { refreshSession } from "../lib/http";
import { useAuth } from "../lib/auth-store";
import { RequireAdmin, RequireAuth } from "./guards";
import AppShell from "./AppShell";
import { Skeleton } from "../components/ui";

const LoginPage = lazy(() => import("./LoginPage"));
const ChatPage = lazy(() => import("./chat/ChatPage"));
const DashboardPage = lazy(() => import("./dashboard/DashboardPage"));
const CatalogPage = lazy(() => import("./workspace/WorkspacePages").then((m) => ({ default: m.CatalogPage })));
const HistoryPage = lazy(() => import("./workspace/WorkspacePages").then((m) => ({ default: m.HistoryPage })));
const SavedPage = lazy(() => import("./workspace/WorkspacePages").then((m) => ({ default: m.SavedPage })));
const AuditPage = lazy(() => import("./admin/AdminPages").then((m) => ({ default: m.AuditPage })));
const UsersPage = lazy(() => import("./admin/AdminPages").then((m) => ({ default: m.UsersPage })));
const OperationsPage = lazy(() => import("./admin/AdminPages").then((m) => ({ default: m.OperationsPage })));
const EvaluationPage = lazy(() => import("./admin/AdminPages").then((m) => ({ default: m.EvaluationPage })));

function Fallback() {
  return <div className="p-6" aria-busy="true" aria-label="Loading"><Skeleton className="h-8 w-1/3" /><Skeleton className="mt-6 h-64 w-full" /></div>;
}

export default function AppRoutes() {
  const status = useAuth((state) => state.status);
  useEffect(() => {
    if (status === "loading") void refreshSession();
  }, [status]);

  return (
    <Suspense fallback={<Fallback />}>
      <Routes>
        <Route path="login" element={<LoginPage />} />
        <Route
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="chat" replace />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="catalog" element={<CatalogPage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="saved" element={<SavedPage />} />
          <Route path="admin/audit" element={<RequireAdmin><AuditPage /></RequireAdmin>} />
          <Route path="admin/users" element={<RequireAdmin><UsersPage /></RequireAdmin>} />
          <Route path="admin/operations" element={<RequireAdmin><OperationsPage /></RequireAdmin>} />
          <Route path="admin/evaluation" element={<RequireAdmin><EvaluationPage /></RequireAdmin>} />
          <Route path="*" element={<Navigate to="chat" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
