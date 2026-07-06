import React from "react";
import "./App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "./context/AuthContext";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Leads from "./pages/Leads";
import LeadDetail from "./pages/LeadDetail";
import FollowUps from "./pages/FollowUps";
import WhatsAppInbox from "./pages/WhatsAppInbox";
import Reports from "./pages/Reports";
import Templates from "./pages/Templates";
import Admin from "./pages/Admin";
import ScreenPop from "./pages/ScreenPop";
import CallCenter from "./pages/CallCenter";
import Marketing from "./pages/Marketing";

function Protected({ children }) {
  const { user } = useAuth();
  if (user === null)
    return (
      <div className="flex h-screen items-center justify-center bg-slate-50">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#4A90E2] border-t-transparent" />
      </div>
    );
  if (user === false) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
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
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/screen-pop" element={<ScreenPop />} />
          <Route path="/" element={<Protected><Dashboard /></Protected>} />
          <Route path="/leads" element={<Guard perm="leads"><Leads /></Guard>} />
          <Route path="/leads/:id" element={<Guard perm="leads"><LeadDetail /></Guard>} />
          <Route path="/followups" element={<Guard perm="followups"><FollowUps /></Guard>} />
          <Route path="/call-center" element={<Guard perm="call_center"><CallCenter /></Guard>} />
          <Route path="/whatsapp" element={<Guard perm="whatsapp"><WhatsAppInbox /></Guard>} />
          <Route path="/reports" element={<Guard perm="reports"><Reports /></Guard>} />
          <Route path="/templates" element={<Guard perm="templates"><Templates /></Guard>} />
          <Route path="/marketing" element={<Guard perm="marketing"><Marketing /></Guard>} />
          <Route path="/admin" element={<Guard perm="admin"><Admin /></Guard>} />
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" richColors />
    </AuthProvider>
  );
}

export default App;
