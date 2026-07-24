import React, { Suspense } from "react";
import "./App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { NavGuardProvider } from "./context/NavGuardContext";
import { abortPendingReads } from "./lib/api";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Leads from "./pages/Leads";
import LeadDetail from "./pages/LeadDetail";
import FollowUps from "./pages/FollowUps";
import WhatsAppInbox from "./pages/WhatsAppInbox";
import Reports from "./pages/Reports";
import Templates from "./pages/Templates";
import WaTemplateDetail from "./pages/WaTemplateDetail";
import WaMessageList from "./pages/WaMessageList";
import WaMessageDetail from "./pages/WaMessageDetail";
import Admin from "./pages/Admin";
import ScreenPop from "./pages/ScreenPop";
import CallCenter from "./pages/CallCenter";
import Marketing from "./pages/Marketing";
import AiInsights from "./pages/AiInsights";
import KpiOverview from "./pages/KpiOverview";

// Code-split the Dashboard (it pulls in recharts). Callers now land on Leads, so this
// heavy chunk is no longer parsed on the initial app load for everyone.
const Dashboard = React.lazy(() => import("./pages/Dashboard"));

const FullSpinner = () => (
  <div className="flex h-screen items-center justify-center bg-slate-50">
    <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#4A90E2] border-t-transparent" />
  </div>
);

// On every route change, cancel the PREVIOUS route's still-pending reads so they don't hold the
// browser's limited per-host connections (which made tab-switching hang) or keep hammering a busy
// origin. Skips the very first render. Uses the request's tagged path so the new page's freshly
// fired requests are never cancelled.
function RouteChangeAborter() {
  const { pathname } = useLocation();
  const first = React.useRef(true);
  React.useEffect(() => {
    if (first.current) { first.current = false; return; }
    abortPendingReads();
  }, [pathname]);
  return null;
}

// Aborted requests reject with ERR_CANCELED — swallow those globally so cancelling reads on
// navigation never surfaces a console error or a stray toast.
if (typeof window !== "undefined" && !window.__hivfCancelGuard) {
  window.__hivfCancelGuard = true;
  window.addEventListener("unhandledrejection", (ev) => {
    const r = ev.reason;
    if (r && (r.code === "ERR_CANCELED" || r.name === "CanceledError")) ev.preventDefault();
  });
}

function Protected({ children }) {
  const { user } = useAuth();
  if (user === null) return <FullSpinner />;
  if (user === false) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
}

// Role-based landing: callers open straight into Leads (their workspace); admins & managers
// get the Dashboard. The target is picked from the routes the user can actually open (by
// permission), so if an admin has disabled a role's Dashboard/Leads permission the user lands
// on their first permitted page instead of bouncing in a Guard→"/"→Guard redirect loop.
const LANDING_PATHS = {
  dashboard: "/dashboard", leads: "/leads", followups: "/followups",
  call_center: "/call-center", whatsapp: "/whatsapp", reports: "/reports",
  marketing: "/marketing", templates: "/templates",
};
function RoleLanding() {
  const { user, can } = useAuth();
  if (user === null) return <FullSpinner />;
  if (user === false) return <Navigate to="/login" replace />;
  const order = user.role === "caller"
    ? ["leads", "dashboard", "followups", "call_center", "whatsapp", "templates"]
    : ["dashboard", "leads", "reports", "followups", "call_center", "whatsapp", "marketing", "templates"];
  const perm = order.find((p) => can(p));
  if (!perm) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-50 p-6 text-center" data-testid="no-access-landing">
        <div>
          <p className="font-display text-lg font-extrabold text-slate-800">No pages available</p>
          <p className="mt-1 text-sm text-slate-500">Your account has no accessible sections. Please contact your administrator.</p>
        </div>
      </div>
    );
  }
  return <Navigate to={LANDING_PATHS[perm]} replace />;
}

function Guard({ perm, children }) {
  const { user, can } = useAuth();
  if (user === null || user === false) return <Protected>{children}</Protected>;
  if (!can(perm)) return <Protected><Navigate to="/" replace /></Protected>;
  return <Protected>{children}</Protected>;
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <NavGuardProvider>
        <RouteChangeAborter />
        <Suspense fallback={<FullSpinner />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/screen-pop" element={<ScreenPop />} />
          <Route path="/" element={<RoleLanding />} />
          <Route path="/dashboard" element={<Guard perm="dashboard"><Dashboard /></Guard>} />
          <Route path="/leads" element={<Guard perm="leads"><Leads /></Guard>} />
          <Route path="/leads/:id" element={<Guard perm="leads"><LeadDetail /></Guard>} />
          <Route path="/followups" element={<Guard perm="followups"><FollowUps /></Guard>} />
          <Route path="/call-center" element={<Guard perm="call_center"><CallCenter /></Guard>} />
          <Route path="/whatsapp" element={<Guard perm="whatsapp"><WhatsAppInbox /></Guard>} />
          <Route path="/reports" element={<Guard perm="reports"><Reports /></Guard>} />
          <Route path="/kpi" element={<Guard perm="reports"><KpiOverview /></Guard>} />
          <Route path="/ai-insights" element={<Guard perm="reports"><AiInsights /></Guard>} />
          <Route path="/templates" element={<Guard perm="templates"><Templates /></Guard>} />
          <Route path="/templates/whatsapp/:id" element={<Guard perm="templates"><WaTemplateDetail /></Guard>} />
          <Route path="/templates/whatsapp/:id/messages" element={<Guard perm="templates"><WaMessageList /></Guard>} />
          <Route path="/wa/message/:trackId" element={<Guard perm="templates"><WaMessageDetail /></Guard>} />
          <Route path="/marketing" element={<Guard perm="marketing"><Marketing /></Guard>} />
          <Route path="/admin" element={<Guard perm="admin"><Admin /></Guard>} />
        </Routes>
        </Suspense>
        </NavGuardProvider>
      </BrowserRouter>
      <Toaster position="top-right" richColors />
    </AuthProvider>
  );
}

export default App;
