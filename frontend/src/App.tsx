import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ActivityPage } from "./pages/ActivityPage";
import { CustomersPage } from "./pages/CustomersPage";
import { DashboardPage } from "./pages/DashboardPage";
import { InvoicesPage } from "./pages/InvoicesPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { RunsPage } from "./pages/RunsPage";
import { TicketsPage } from "./pages/TicketsPage";
import { WorkerPage } from "./pages/WorkerPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/worker" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/worker" element={<WorkerPage />} />
        <Route path="/customers" element={<CustomersPage />} />
        <Route path="/invoices" element={<InvoicesPage />} />
        <Route path="/tickets" element={<TicketsPage />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route path="/activity" element={<ActivityPage />} />
        <Route path="*" element={<Navigate to="/worker" replace />} />
      </Route>
    </Routes>
  );
}
