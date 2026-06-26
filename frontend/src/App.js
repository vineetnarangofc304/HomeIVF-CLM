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

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/screen-pop" element={<ScreenPop />} />
          <Route path="/" element={<Protected><Dashboard /></Protected>} />
          <Route path="/leads" element={<Protected><Leads /></Protected>} />
          <Route path="/leads/:id" element={<Protected><LeadDetail /></Protected>} />
          <Route path="/followups" element={<Protected><FollowUps /></Protected>} />
          <Route path="/call-center" element={<Protected><CallCenter /></Protected>} />
          <Route path="/whatsapp" element={<Protected><WhatsAppInbox /></Protected>} />
          <Route path="/reports" element={<Protected><Reports /></Protected>} />
          <Route path="/templates" element={<Protected><Templates /></Protected>} />
          <Route path="/marketing" element={<Protected><Marketing /></Protected>} />
          <Route path="/admin" element={<Protected><Admin /></Protected>} />
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" richColors />
    </AuthProvider>
  );
}

export default App;
